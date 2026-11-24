"""Generación del gancho de las ofertas con IA y respaldo sin IA."""

import asyncio
import logging
import os
import random
import re
import time
from difflib import SequenceMatcher
from typing import Callable, NamedTuple, Optional

import httpx

from config import Config
from utils.text import limpiar_titulo

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
# La cuota de Google es por modelo y proyecto: {(clave, modelo): hasta cuándo}
_modelo_cooldowns: dict[tuple[str, str], float] = {}
# Modelos que rechazaron la configuración de thinking: se llaman sin ella.
_sin_thinking: set[str] = set()

# Caché simple de ganchos para no pagar dos veces la misma generación.
_cache: dict[tuple, object] = {}
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

# Modelos que la clave puede usar de verdad, descubiertos vía API.
_modelos_descubiertos: list[str] = []
_modelos_cache_ts = 0.0
_modelos_intento_ts = 0.0
_MODELOS_TTL = 6 * 3600
_MODELOS_ERROR_TTL = 3600


def _version_modelo(nombre: str) -> float:
    match = re.search(r"gemini-(\d+(?:\.\d+)?)", nombre)
    return float(match.group(1)) if match else 0.0


def modelos_gemini_descubiertos() -> list[str]:
    return list(_modelos_descubiertos)


async def descubrir_modelos_gemini(keys: list[str]) -> list[str]:
    """
    Pregunta a la API qué modelos Gemini puede usar la clave.

    Evita depender de nombres hardcodeados que Google retira para cuentas nuevas.
    """
    global _modelos_descubiertos, _modelos_cache_ts, _modelos_intento_ts

    ahora = time.time()
    if _modelos_descubiertos and ahora - _modelos_cache_ts < _MODELOS_TTL:
        return list(_modelos_descubiertos)
    if ahora - _modelos_intento_ts < _MODELOS_ERROR_TTL:
        return list(_modelos_descubiertos)
    _modelos_intento_ts = ahora
    if not keys:
        return []

    for key in keys[:3]:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                respuesta = await client.get(
                    "https://generativelanguage.googleapis.com/v1beta/models",
                    headers={"x-goog-api-key": key},
                )
            if respuesta.status_code != 200:
                logger.warning(
                    "No se pudieron listar los modelos Gemini (HTTP %s)",
                    respuesta.status_code,
                )
                continue
            datos = respuesta.json()
            nombres: list[str] = []
            for modelo in datos.get("models", []):
                nombre = str(modelo.get("name", "")).removeprefix("models/")
                metodos = modelo.get("supportedGenerationMethods") or []
                if "generateContent" not in metodos:
                    continue
                bajo = nombre.lower()
                if not bajo.startswith("gemini"):
                    continue
                if any(
                    parte in bajo
                    for parte in (
                        "embedding",
                        "image",
                        "tts",
                        "audio",
                        "live",
                        "robotics",
                        "veo",
                        "lyria",
                    )
                ):
                    continue
                nombres.append(nombre)
            if not nombres:
                continue
            nombres.sort(
                key=lambda nombre: (
                    0
                    if "flash" in nombre.lower() and "lite" not in nombre.lower()
                    else 1
                    if "flash" in nombre.lower()
                    else 2,
                    1
                    if ("preview" in nombre.lower() or "exp" in nombre.lower())
                    else 0,
                    -_version_modelo(nombre),
                )
            )
            _modelos_descubiertos = nombres[:15]
            _modelos_cache_ts = time.time()
            logger.info(
                "Modelos Gemini disponibles para la clave: %s",
                ", ".join(_modelos_descubiertos[:8]),
            )
            return list(_modelos_descubiertos)
        except (httpx.HTTPError, ValueError, OSError) as exc:
            logger.warning("Error consultando los modelos Gemini: %s", exc)
    return []


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
                variantes.append(
                    f"{titulo_corto}: {precio} (antes {original}). Está interesante."
                )
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


_JERGA_MARCADA = (
    "klk",
    "jevi",
    "jevy",
    "nítido",
    "nitido",
    "tíguere",
    "tiguere",
    "tigueraje",
    "manin",
    "ma'ni",
    "compai",
    "compadre",
    "qué lo qué",
    "que lo que",
    "dímelo",
    "dimelo",
    "singao",
    "de pinga",
    "chévere",
    "chevere",
    "vaina",
    "manito",
)
_JERGA_MAXIMA = 2  # más marcas que esto en una frase = jerga metida a la fuerza


def _jerga_forzada(texto: str) -> bool:
    """Detecta el gancho donde la jerga se amontonó en vez de salir natural."""
    bajo = texto.lower()
    return sum(1 for marca in _JERGA_MARCADA if marca in bajo) > _JERGA_MAXIMA


def _limpiar_gancho(texto: Optional[str]) -> Optional[str]:
    if not texto:
        return None
    limpio = " ".join(str(texto).split()).strip()
    if limpio.startswith('"') and limpio.endswith('"') and len(limpio) > 1:
        limpio = limpio[1:-1].strip()
    limpio = re.sub(r"<[^>]+>", "", limpio)
    if _jerga_forzada(limpio):
        logger.info("Gancho descartado por exceso de jerga: %r", limpio[:120])
        return None
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
    # Un punto pegado a un emoji final ("😎.") queda feo: se quita.
    limpio = re.sub(r"([\u2190-\U0001FAFF\uFE0F])\.+$", r"\1", limpio)
    termina_en_emoji = ord(limpio[-1]) >= 0x2190 or limpio[-1] == "\ufe0f"
    if not termina_en_emoji and not re.search(r"[.!?…]$", limpio):
        limpio = limpio + "."
    return limpio


async def fallback_groq(
    prompt: str,
    system_instruction: str,
    parser: Optional[Callable[[Optional[str]], object]] = None,
) -> object:
    """Genera el gancho con Groq si Gemini no está disponible o agotó cuota."""
    parser = parser or _limpiar_gancho
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
                    temperature=0.4,
                    max_tokens=600,
                ),
                timeout=getattr(Config, "GROQ_CALL_TIMEOUT_SECONDS", 20),
            )
            texto = parser(response.choices[0].message.content)
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
        # Baja temperatura: datos concretos y frases coherentes, no ingenio.
        "temperature": 0.4,
        "max_output_tokens": 350,
    }
    if (
        con_thinking
        and modelo not in _sin_thinking
        and modelo.startswith(("gemini-2.5", "gemini-3"))
        and types is not None
    ):
        try:
            if modelo.startswith("gemini-3"):
                # Gemini 3 usa niveles; thinking_budget=0 da 400 INVALID_ARGUMENT.
                params["thinking_config"] = types.ThinkingConfig(
                    thinking_level=types.ThinkingLevel.MINIMAL
                )
            else:
                params["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        except Exception:  # noqa: BLE001 - versión antigua del SDK
            pass
    try:
        return types.GenerateContentConfig(**params)
    except Exception:  # noqa: BLE001 - thinking_config no soportado
        params.pop("thinking_config", None)
        return types.GenerateContentConfig(**params)


class Publicacion(NamedTuple):
    """Resultado de la IA: título en español (opcional) y gancho."""

    titulo_es: Optional[str]
    gancho: str


def _numeros(texto: str) -> set[str]:
    return set(re.findall(r"\d+", texto))


def _limpiar_titulo_es(texto: Optional[str], original: str) -> Optional[str]:
    """Valida el título traducido: sin HTML, sin cortes y sin perder números."""
    if not texto:
        return None
    limpio = " ".join(str(texto).split())
    limpio = re.sub(r"<[^>]+>", "", limpio)
    limpio = limpio.strip(" \"'`*_-–|:;,")
    if not 5 <= len(limpio) <= 120:
        return None
    if limpio[-1] in "$€£¥%&/+-=,;:([{":
        return None
    if re.search(
        r"\b(de|del|a|al|con|para|por|en|y|o|e|u|la|el|los|las|un|una)$",
        limpio,
        re.IGNORECASE,
    ):
        return None
    # Marca, modelo, capacidad y cantidades no se pueden perder ni inventar.
    base = limpiar_titulo(original)
    if SequenceMatcher(None, base.lower(), limpio.lower()).ratio() >= 0.93:
        logger.info("Título 'traducido' igual al original; se descarta: %r", limpio)
        return None
    faltantes = _numeros(base) - _numeros(limpio)
    if faltantes:
        logger.info(
            "Título traducido descartado (faltan números %s): %r",
            sorted(faltantes),
            limpio,
        )
        return None
    return limpio


def parsear_publicacion(
    texto: Optional[str], original: str
) -> Optional[Publicacion]:
    """Lee 'TITULO: ...' y 'GANCHO: ...'. El gancho es obligatorio."""
    if not texto:
        return None
    titulo_raw = None
    gancho_raw = None
    for linea in str(texto).splitlines():
        match = re.match(
            r"^\W*(t[ií]tulo|gancho)\W*:\s*(.+)$", linea.strip(), re.IGNORECASE
        )
        if not match:
            continue
        valor = match.group(2).strip(" *_`")
        if match.group(1).lower().startswith("t"):
            titulo_raw = valor
        else:
            gancho_raw = valor
    gancho = _limpiar_gancho(gancho_raw)
    if not gancho:
        return None
    return Publicacion(_limpiar_titulo_es(titulo_raw, original), gancho)


def limpiar_cache_ia() -> None:
    """Vacía la caché de resultados de IA (útil para pruebas manuales)."""
    _cache.clear()


_RE_PRECIO = re.compile(r"(\d[\d,]*(?:\.\d+)?)")
_SIN_PRECIO = ("", "no disponible", "n/a", "unknown")


def _precio_en_numero(valor: Optional[str]) -> Optional[float]:
    """Extrae el valor numérico de un precio tipo '$1,299.00'."""
    if valor is None or str(valor).strip().lower() in _SIN_PRECIO:
        return None
    coincidencia = _RE_PRECIO.search(str(valor).replace(" ", ""))
    if not coincidencia:
        return None
    try:
        return float(coincidencia.group(1).replace(",", ""))
    except ValueError:
        return None


def _descuento_porcentaje(
    precio: Optional[str], original: Optional[str]
) -> Optional[int]:
    """Descuento aproximado; solo si ambos precios son numéricos y tiene sentido."""
    actual = _precio_en_numero(precio)
    antes = _precio_en_numero(original)
    if not actual or not antes or antes <= 0 or actual >= antes:
        return None
    porcentaje = round((1 - actual / antes) * 100)
    return porcentaje if 1 <= porcentaje <= 95 else None


def _prompt_oferta(titulo: str, precio: str, original: Optional[str]) -> str:
    """Datos reales de la oferta: es lo único que la IA puede afirmar."""
    lineas = [f"Producto: {limpiar_titulo(titulo)}"]
    if precio and str(precio).strip().lower() not in _SIN_PRECIO:
        lineas.append(f"Precio en oferta: {precio}")
    else:
        lineas.append("Precio desconocido")
    if original and str(original).strip().lower() not in _SIN_PRECIO:
        lineas.append(f"Precio original: {original}")
        descuento = _descuento_porcentaje(precio, original)
        if descuento:
            lineas.append(f"Descuento aproximado: {descuento}%")
    return "\n".join(lineas)


_ESTILO_DOMINICANO = (
    "Eres el dueño de un canal dominicano de ofertas en Telegram. Le escribes a tu "
    "gente de tú a tú, como quien pasa el dato: cercano, directo y sin teatro. "
    "Tu español es dominicano y neutro; la jerga es OPCIONAL, no una cuota. "
    "Si una expresión coloquial cae sola, úsala (una sola por frase); si no encaja, "
    "escribe claro y ya. NUNCA metas palabras como 'klk', 'jevi', 'nítido', 'tíguere' "
    "o 'manin' solo por sonar dominicano: eso suena forzado y le quita seriedad al dato. "
    "PROHIBIDO inventar. Solo puedes afirmar lo que aparece en los datos de la oferta "
    "(tipo de producto, precio y precio original). No inventes características, "
    "materiales, tamaños, garantías, envíos, vendedor ni stock; no digas que lo "
    "compraste, que te llegó o que lo probaste; no compares con otros productos; "
    "no prometas nada ni exageres con 'el mejor del mercado' o similares. "
    "Si del producto solo sabes el nombre, comenta el precio, no el producto. "
    "Cada frase debe tener sentido completo y decir algo concreto: nada de relleno. "
)

_INSTRUCCION_GANCHO = (
    _ESTILO_DOMINICANO
    + "Devuelve UNA sola oración de 100 caracteres como máximo, con máximo 1 emoji al "
    "final. No repitas el nombre del producto palabra por palabra (el título ya va "
    "arriba). Sin comillas, sin hashtags y sin explicar nada más."
)

_INSTRUCCION_PUBLICACION = (
    _ESTILO_DOMINICANO
    + "Responde SIEMPRE con exactamente dos líneas y nada más:\n"
    "TITULO: nombre del producto TRADUCIDO al español claro y neutro (no dominicano), "
    "máximo 90 caracteres. Traduce TODAS las palabras descriptivas (tipo de producto, "
    "material, función, color, público); NUNCA devuelvas el título igual que en inglés. "
    "Solo mantén sin traducir marcas, modelos, medidas, capacidades y cantidades "
    "exactamente como vienen. No incluyas precio ni envío.\n"
    "GANCHO: UNA sola oración de 100 caracteres como máximo, con máximo 1 emoji al "
    "final. No repitas el TITULO palabra por palabra.\n"
    "Ejemplos de TITULO:\n"
    "Sony WH-1000XM5 Wireless Noise Cancelling Headphones -> "
    "Audífonos inalámbricos Sony WH-1000XM5 con cancelación de ruido\n"
    "Levi's Men's 511 Slim Fit Jeans -> Jeans Levi's 511 corte ajustado para hombre\n"
    "Anker 737 Power Bank 24,000mAh 140W Portable Charger -> "
    "Batería portátil Anker 737 de 24,000mAh y 140W"
)


async def generar_gancho_ia(
    titulo: str, precio: str, original: Optional[str]
) -> Optional[str]:
    """Genera un gancho con Gemini (rotación de claves) y respaldo Groq."""
    cache_key = (titulo or "", precio or "", original or "")
    return await _generar_con_ia(
        cache_key,
        _prompt_oferta(titulo, precio, original),
        _INSTRUCCION_GANCHO,
        _limpiar_gancho,
    )


async def generar_publicacion_ia(
    titulo: str, precio: str, original: Optional[str]
) -> Optional[Publicacion]:
    """Una sola llamada: título en español + gancho."""
    cache_key = ("pub", titulo or "", precio or "", original or "")
    return await _generar_con_ia(
        cache_key,
        _prompt_oferta(titulo, precio, original),
        _INSTRUCCION_PUBLICACION,
        lambda texto: parsear_publicacion(texto, titulo or ""),
    )


async def _generar_con_ia(
    cache_key: tuple,
    prompt: str,
    system_instruction: str,
    parser: Callable[[Optional[str]], object],
):
    """Bucle común Gemini (multi-clave/modelo) con respaldo Groq."""
    global _sin_ia_avisado

    if cache_key in _cache:
        return _cache[cache_key]

    keys = get_all_gemini_keys()
    if not keys or not genai:
        if not _sin_ia_avisado:
            logger.info(
                "Sin claves de Gemini o sin librería google-genai; se usará el "
                "respaldo de Groq o la plantilla local."
            )
            _sin_ia_avisado = True
        resultado = await fallback_groq(prompt, system_instruction, parser)
        if resultado:
            _guardar_cache(cache_key, resultado)
        else:
            _registrar_fallo("config", "sin claves de Gemini utilizables")
        return resultado

    preferidos = Config.gemini_model_preferidos()
    descubiertos = await descubrir_modelos_gemini(keys)
    # El modelo elegido se intenta siempre primero; el descubrimiento solo
    # aporta alternativas si ese modelo no está disponible para la clave.
    respaldo = Config.gemini_models()
    if descubiertos:
        # Del respaldo configurado solo valen los modelos que la clave puede usar.
        respaldo = [m for m in respaldo if m in descubiertos]
    orden = [*preferidos, *respaldo, *descubiertos]

    modelos: list[str] = []
    for nombre in orden:
        if nombre and nombre not in modelos:
            modelos.append(nombre)
    logger.debug("Modelos Gemini a probar: %s", ", ".join(modelos[:6]))
    for _ in range(3):
        key, wait_time = get_next_available_key(keys)
        if not key:
            logger.info(
                "Todas las claves de Gemini están en cooldown; esperando %.1fs",
                wait_time,
            )
            if wait_time > 8:
                resultado = await fallback_groq(prompt, system_instruction, parser)
                if resultado:
                    _guardar_cache(cache_key, resultado)
                    return resultado
            if wait_time > 15:
                # Pausa larga (p. ej. cuota diaria): esperar no sirve de nada.
                break
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
        agotados = 0
        for modelo in modelos:
            if _modelo_cooldowns.get((key, modelo), 0.0) > time.time():
                agotados += 1
                continue
            for con_thinking in (True, False):
                config = _config_para_modelo(modelo, system_instruction, con_thinking)
                try:
                    response = await asyncio.wait_for(
                        client.aio.models.generate_content(
                            model=modelo, contents=prompt, config=config
                        ),
                        timeout=getattr(Config, "GEMINI_CALL_TIMEOUT_SECONDS", 8),
                    )
                    texto = parser(getattr(response, "text", None))
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
                        if match:
                            cooldown = float(match.group(1)) + 1.0
                        elif "PerDay" in error_msg or "per day" in error_msg.lower():
                            # Cuota diaria agotada: no tiene sentido reintentar pronto.
                            cooldown = 1800.0
                        else:
                            cooldown = 60.0
                        logger.warning(
                            "Cuota agotada en %s; se pausa ese modelo %.0fs y se "
                            "prueba el siguiente",
                            modelo,
                            cooldown,
                        )
                        _modelo_cooldowns[(key, modelo)] = time.time() + cooldown
                        agotados += 1
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
                        _sin_thinking.add(modelo)
                        continue
                    logger.error(
                        "Error de Gemini (%s): %s; se prueba el siguiente modelo",
                        modelo,
                        exc,
                    )
                    break
        if agotados >= len(modelos):
            # Todos los modelos de esta clave sin cuota: se pasa a la siguiente.
            hasta = min(
                _modelo_cooldowns.get((key, modelo), 0.0) for modelo in modelos
            )
            _key_cooldowns[key] = max(hasta, time.time() + 1.0)
            clave_bloqueada = True
        if not clave_bloqueada:
            # Ningún modelo respondió: no tiene sentido repetir la misma clave.
            break

    logger.info("Agotados los intentos de Gemini; intento final con Groq")
    resultado = await fallback_groq(prompt, system_instruction, parser)
    if resultado:
        _guardar_cache(cache_key, resultado)
    return resultado


def _guardar_cache(key: tuple, valor: object) -> None:
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


async def generar_publicacion(
    titulo: str,
    precio: str,
    original: Optional[str],
    requerido: bool | None = None,
) -> Optional[Publicacion]:
    """
    Título en español + gancho en una sola llamada de IA.

    Si la IA falla y no es obligatoria, devuelve el gancho de plantilla y sin
    título traducido (se publica el título original limpio).
    """
    requerido = Config.AI_HOOK_REQUIRED if requerido is None else requerido
    resultado = await generar_publicacion_ia(titulo, precio, original)
    if resultado:
        return resultado
    if requerido:
        return None
    return Publicacion(None, gancho_respaldo(titulo, precio, original))
