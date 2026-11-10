"""Generación del gancho de las ofertas con IA y respaldo sin IA."""

import asyncio
import logging
import os
import random
import re
import time
from typing import Optional

from config import Config

try:
    from google import genai
    from google.genai import types
except ImportError:  # pragma: no cover - depende del entorno
    genai = None
    types = None

try:
    from groq import AsyncGroq
except ImportError:  # pragma: no cover - depende del entorno
    AsyncGroq = None

logger = logging.getLogger(__name__)

# {clave: timestamp hasta el que está en cooldown}
_key_cooldowns: dict[str, float] = {}
_last_used_key_index = 0

# Caché simple de ganchos para no pagar dos veces la misma generación.
_cache: dict[tuple[str, str, str], str] = {}
_CACHE_MAX = 300
_sin_ia_avisado = False

_estado: dict[str, object] = {
    "ultimo_proveedor": None,
    "ultimo_exito_ts": None,
    "ultimo_error": None,
    "ultimo_error_origen": None,
    "ultimo_error_ts": None,
    "exitos": 0,
    "fallos": 0,
}


def estado_ia() -> dict[str, object]:
    """Estado resumido del último intento de IA (para /diagnostico)."""
    return dict(_estado)


def _registrar_exito(proveedor: str) -> None:
    _estado["ultimo_proveedor"] = proveedor
    _estado["ultimo_exito_ts"] = int(time.time())
    _estado["exitos"] = int(_estado["exitos"]) + 1


def _registrar_fallo(origen: str, error: object) -> None:
    _estado["ultimo_error"] = str(error)[:300]
    _estado["ultimo_error_origen"] = origen
    _estado["ultimo_error_ts"] = int(time.time())
    _estado["fallos"] = int(_estado["fallos"]) + 1


def registrar_error_ia(origen: str, error: object) -> None:
    _registrar_fallo(origen, error)


def get_all_gemini_keys() -> list[str]:
    """Recupera todas las claves de Gemini disponibles en la configuración."""
    keys: list[str] = []
    config_keys = getattr(Config, "GEMINI_API_KEYS", "") or os.getenv(
        "GEMINI_API_KEYS", ""
    )
    if config_keys:
        keys.extend([k.strip() for k in str(config_keys).split(",") if k.strip()])

    for variable in ("GEMINI_API_KEY", "GEMINI_API_KEY_BACKUP"):
        value = getattr(Config, variable, "") or os.getenv(variable, "")
        if value and value.strip() and value.strip() not in keys:
            keys.append(value.strip())
    return keys


def get_next_available_key(keys: list[str]) -> tuple[Optional[str], float]:
    """
    Busca la siguiente clave disponible (round-robin) que no esté en cooldown.

    Retorna (clave, espera_minima) donde la espera solo aplica si todas están
    bloqueadas temporalmente.
    """
    global _last_used_key_index
    if not keys:
        return None, 0.0

    now = time.time()
    for offset in range(len(keys)):
        index = (_last_used_key_index + offset) % len(keys)
        key = keys[index]
        if now >= _key_cooldowns.get(key, 0.0):
            _last_used_key_index = (index + 1) % len(keys)
            return key, 0.0

    min_wait = min(_key_cooldowns.get(key, now) - now for key in keys)
    return None, max(min_wait, 1.0)


def gancho_respaldo(titulo: str, precio: str, original: Optional[str]) -> str:
    """Gancho sin IA para que una caída del proveedor no bloquee la publicación."""
    precio = (precio or "").strip()
    original = (original or "").strip()
    titulo_corto = " ".join((titulo or "").split())[:70]

    if precio and precio.lower() != "no disponible":
        if original and original.lower() != "no disponible":
            variantes = [
                f"De {original} a {precio}. Buen momento para aprovechar.",
                f"Bajó de {original} a {precio}; vale la pena mirarlo.",
                f"Ahora en {precio} (antes {original}). Ojo con esa oferta.",
                f"Se dejó ver a {precio}; antes costaba {original}.",
                f"Precio de hoy: {precio}. Venía de {original}.",
            ]
            if titulo_corto:
                variantes.append(f"{titulo_corto}: {precio}. Está interesante.")
            return random.choice(variantes)
        if titulo_corto:
            variantes = [
                f"{titulo_corto}: {precio}. Vale la pena mirarlo.",
                f"Precio de hoy: {precio}. Échale un ojo.",
                f"Se dejó ver a {precio}. Está nítido.",
            ]
            return random.choice(variantes)
        return f"Precio interesante: {precio}."
    if titulo_corto:
        return f"Oferta para revisar: {titulo_corto}."
    return "Oferta interesante para revisar."


def _limpiar_gancho(texto: Optional[str]) -> Optional[str]:
    if not texto:
        return None
    limpio = " ".join(str(texto).split()).strip()
    if limpio.startswith('"') and limpio.endswith('"') and len(limpio) > 1:
        limpio = limpio[1:-1].strip()
    limpio = re.sub(r"<[^>]+>", "", limpio)
    if len(limpio) > 180:
        limpio = limpio[:179].rstrip() + "…"
    if len(limpio) < 15:
        return None
    # Rechaza respuestas cortadas a mitad de frase (típico al agotar max_tokens).
    if limpio[-1] in "$€£¥%&/+*-_=,;:([{":
        return None
    if re.search(
        r"\b(de|del|a|al|con|para|por|en|y|o|desde|hasta|solo|muy|mas|más)$",
        limpio,
        re.IGNORECASE,
    ):
        return None
    if not re.search(r"[.!?…]$", limpio):
        limpio = limpio + "."
    return limpio


async def fallback_groq(prompt: str, system_instruction: str) -> Optional[str]:
    """Genera el gancho con Groq si Gemini no está disponible o agotó cuota."""
    api_key = getattr(Config, "GROQ_API_KEY", "") or os.getenv("GROQ_API_KEY", "")
    if not api_key or not AsyncGroq:
        return None

    modelos: list[str] = []
    for modelo in (
        getattr(Config, "GROQ_MODEL", ""),
        "openai/gpt-oss-20b",
        "openai/gpt-oss-120b",
        "llama-3.1-8b-instant",
    ):
        if modelo and modelo not in modelos:
            modelos.append(modelo)

    try:
        client = AsyncGroq(api_key=api_key)
    except Exception as exc:  # noqa: BLE001
        _registrar_fallo("groq", exc)
        logger.error("No se pudo crear el cliente de Groq: %s", exc)
        return None

    for modelo in modelos:
        try:
            logger.info("Generando gancho con Groq (%s)...", modelo)
            response = await asyncio.wait_for(
                client.chat.completions.create(
                    messages=[
                        {"role": "system", "content": system_instruction},
                        {"role": "user", "content": prompt},
                    ],
                    model=modelo,
                    temperature=0.7,
                    max_tokens=600,
                ),
                timeout=getattr(Config, "GROQ_CALL_TIMEOUT_SECONDS", 20),
            )
            texto = _limpiar_gancho(response.choices[0].message.content)
            if texto:
                _registrar_exito(f"groq:{modelo}")
                return texto
            _registrar_fallo(f"groq:{modelo}", "respuesta corta")
        except asyncio.TimeoutError:
            _registrar_fallo(f"groq:{modelo}", "timeout")
            logger.warning("Groq (%s) excedió el tiempo de espera", modelo)
        except Exception as exc:  # noqa: BLE001 - se prueba el siguiente modelo
            _registrar_fallo(f"groq:{modelo}", exc)
            logger.error("Error usando Groq (%s): %s", modelo, exc)
    return None


def _config_para_modelo(
    modelo: str, system_instruction: str, con_thinking: bool = False
):
    """Construye la configuración; thinking solo cuando se pide y el modelo lo admite."""
    params: dict[str, object] = {
        "system_instruction": system_instruction,
        "temperature": 0.7,
        "max_output_tokens": 350,
    }
    if (
        con_thinking
        and modelo.startswith(("gemini-2.5", "gemini-3"))
        and types is not None
    ):
        try:
            params["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        except Exception:  # noqa: BLE001 - versión antigua del SDK
            pass
    try:
        return types.GenerateContentConfig(**params)
    except Exception:  # noqa: BLE001 - thinking_config no soportado
        params.pop("thinking_config", None)
        return types.GenerateContentConfig(**params)


async def generar_gancho_ia(
    titulo: str, precio: str, original: Optional[str]
) -> Optional[str]:
    """Genera un gancho con Gemini (rotación de claves) y respaldo Groq."""
    global _sin_ia_avisado

    cache_key = (titulo or "", precio or "", original or "")
    if cache_key in _cache:
        return _cache[cache_key]

    precio_str = (
        f"Precio en oferta: {precio}"
        if precio and precio != "No disponible"
        else "Precio desconocido"
    )
    original_str = (
        f"Precio original: {original}"
        if original and str(original).lower() != "no disponible"
        else ""
    )
    prompt = f"Producto: {titulo}\n{precio_str}\n{original_str}"

    system_instruction = (
        "Eres un carismático dominicano que comparte buenas ofertas en Telegram. "
        "IMPORTANTE: Tú NO estás vendiendo el producto, simplemente estás compartiendo o comentando "
        "sobre una oferta interesante que viste en internet. Háblalo de forma natural, como si "
        "le pasaras el dato a un amigo. "
        "Usa jerga dominicana natural (con tigueraje verdadero dominicano, 100% dominicano, klk, jevi, nítido). "
        "No uses acentos de otros países, cero palabras como 'che', 'chama', 'órale' o 'wey'. Solo vocabulario de RD. "
        "Asegúrate de tener SENTIDO LÓGICO: comenta algo específico del producto que estás compartiendo. "
        "NO inventes características ni prometas nada que no esté en el texto. "
        "Crea UNA SOLA oración corta, directa, clara y usa máximo 1 emoji al final."
    )

    keys = get_all_gemini_keys()
    if not keys or not genai:
        if not _sin_ia_avisado:
            logger.info(
                "Sin claves de Gemini o sin librería google-genai; se usará el "
                "respaldo de Groq o la plantilla local."
            )
            _sin_ia_avisado = True
        resultado = await fallback_groq(prompt, system_instruction)
        if resultado:
            _guardar_cache(cache_key, resultado)
        else:
            _registrar_fallo("config", "sin claves de Gemini utilizables")
        return resultado

    modelos = Config.gemini_models()
    for _ in range(3):
        key, wait_time = get_next_available_key(keys)
        if not key:
            logger.info(
                "Todas las claves de Gemini están en cooldown; esperando %.1fs",
                wait_time,
            )
            if wait_time > 8:
                resultado = await fallback_groq(prompt, system_instruction)
                if resultado:
                    _guardar_cache(cache_key, resultado)
                    return resultado
            await asyncio.sleep(min(wait_time, 15.0))
            key, _ = get_next_available_key(keys)
            if not key:
                continue

        try:
            client = genai.Client(api_key=key)
        except Exception as exc:  # noqa: BLE001 - clave o SDK inválidos
            _registrar_fallo("gemini", exc)
            logger.error("No se pudo crear el cliente de Gemini: %s", exc)
            continue

        clave_bloqueada = False
        for modelo in modelos:
            for con_thinking in (True, False):
                config = _config_para_modelo(modelo, system_instruction, con_thinking)
                try:
                    response = await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=modelo, contents=prompt, config=config
                        ),
                        timeout=getattr(Config, "GEMINI_CALL_TIMEOUT_SECONDS", 15),
                    )
                    texto = _limpiar_gancho(getattr(response, "text", None))
                    if texto:
                        _registrar_exito(f"gemini:{modelo}")
                        _guardar_cache(cache_key, texto)
                        return texto
                    _registrar_fallo(f"gemini:{modelo}", "respuesta corta")
                    logger.warning(
                        "Gancho demasiado corto con %s; se prueba otro modelo", modelo
                    )
                    break
                except asyncio.TimeoutError:
                    _registrar_fallo(f"gemini:{modelo}", "timeout")
                    logger.warning(
                        "Gemini (%s) excedió el tiempo de espera; se prueba otro modelo",
                        modelo,
                    )
                    break
                except Exception as exc:  # noqa: BLE001 - se decide por tipo de error
                    error_msg = str(exc)
                    _registrar_fallo(f"gemini:{modelo}", exc)
                    if (
                        "429" in error_msg
                        or "RESOURCE_EXHAUSTED" in error_msg
                        or "quota" in error_msg.lower()
                    ):
                        match = re.search(r"retry in (\d+(?:\.\d+)?)s", error_msg)
                        cooldown = float(match.group(1)) + 1.0 if match else 20.0
                        logger.warning(
                            "Límite de Gemini en %s; clave en pausa %.1fs",
                            modelo,
                            cooldown,
                        )
                        _key_cooldowns[key] = time.time() + cooldown
                        clave_bloqueada = True
                        break
                    if "not found" in error_msg.lower() or "404" in error_msg:
                        logger.warning(
                            "Modelo %s no disponible; se prueba el siguiente", modelo
                        )
                        break
                    if con_thinking and (
                        "thinking" in error_msg.lower()
                        or "invalid argument" in error_msg.lower()
                    ):
                        logger.warning(
                            "El modelo %s rechazó thinking; se reintenta sin él", modelo
                        )
                        continue
                    logger.error(
                        "Error de Gemini (%s): %s; se prueba el siguiente modelo",
                        modelo,
                        exc,
                    )
                    break
            if clave_bloqueada:
                break
        if not clave_bloqueada:
            # Ningún modelo respondió: no tiene sentido repetir la misma clave.
            break

    logger.info("Agotados los intentos de Gemini; intento final con Groq")
    resultado = await fallback_groq(prompt, system_instruction)
    if resultado:
        _guardar_cache(cache_key, resultado)
    return resultado


def _guardar_cache(key: tuple[str, str, str], valor: str) -> None:
    if len(_cache) >= _CACHE_MAX:
        _cache.pop(next(iter(_cache)))
    _cache[key] = valor


async def generar_gancho(
    titulo: str,
    precio: str,
    original: Optional[str],
    requerido: bool | None = None,
) -> Optional[str]:
    """
    Gancho para publicar. Si la IA falla y no es obligatoria, usa plantilla.

    `requerido` toma el valor de Config.AI_HOOK_REQUIRED si no se indica.
    """
    requerido = Config.AI_HOOK_REQUIRED if requerido is None else requerido
    gancho = await generar_gancho_ia(titulo, precio, original)
    if gancho:
        return gancho
    if requerido:
        return None
    return gancho_respaldo(titulo, precio, original)
