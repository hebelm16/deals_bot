import os
import logging
import asyncio
import re
import time
from typing import Optional, List, Dict
from config import Config

try:
    from google import genai
    from google.genai import types
except ImportError:
    genai = None

try:
    from groq import AsyncGroq
except ImportError:
    AsyncGroq = None

logger = logging.getLogger(__name__)

# Diccionario para rastrear el tiempo hasta el cual cada llave está en cooldown temporal: {key: timestamp_libre}
_key_cooldowns: Dict[str, float] = {}
_last_used_key_index: int = 0

def get_all_gemini_keys() -> List[str]:
    """Recupera todas las llaves de Gemini disponibles en la configuración."""
    keys = []
    config_keys = getattr(Config, 'GEMINI_API_KEYS', '') or os.getenv('GEMINI_API_KEYS', '')
    if config_keys:
        keys.extend([k.strip() for k in config_keys.split(',') if k.strip()])
    
    k1 = getattr(Config, 'GEMINI_API_KEY', '') or os.getenv('GEMINI_API_KEY', '')
    if k1 and k1.strip() and k1.strip() not in keys:
        keys.append(k1.strip())
        
    k2 = getattr(Config, 'GEMINI_API_KEY_BACKUP', '') or os.getenv('GEMINI_API_KEY_BACKUP', '')
    if k2 and k2.strip() and k2.strip() not in keys:
        keys.append(k2.strip())
        
    return keys

def get_next_available_key(keys: List[str]) -> tuple[Optional[str], float]:
    """
    Busca la siguiente llave disponible que no esté en cooldown.
    Retorna (llave, tiempo_de_espera_minimo_si_todas_estan_en_cooldown).
    """
    global _last_used_key_index
    if not keys:
        return None, 0.0

    now = time.time()
    n = len(keys)
    
    # 1. Buscar una llave disponible a partir del último índice usado (round-robin)
    for i in range(n):
        idx = (_last_used_key_index + i) % n
        key = keys[idx]
        free_at = _key_cooldowns.get(key, 0.0)
        if now >= free_at:
            _last_used_key_index = (idx + 1) % n
            return key, 0.0

    # 2. Si todas están en cooldown, calcular cuánto falta para que se libere la más próxima
    min_wait = min(_key_cooldowns[k] - now for k in keys)
    return None, max(min_wait, 1.0)

async def fallback_groq(prompt: str, system_instruction: str) -> Optional[str]:
    """Genera el gancho con Groq (Llama 3) si Gemini no está disponible o agotó cuota."""
    api_key = getattr(Config, 'GROQ_API_KEY', '') or os.getenv('GROQ_API_KEY', '')
    if not api_key or not AsyncGroq:
        logger.warning("Groq no está configurado o no está instalado.")
        return None
        
    try:
        logger.info("Generando gancho con respaldo de Groq (Llama 3)...")
        client = AsyncGroq(api_key=api_key)
        response = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.3-70b-versatile",
            temperature=0.7,
            max_tokens=250
        )
        texto = response.choices[0].message.content.strip()
        if texto.startswith('"') and texto.endswith('"'):
            texto = texto[1:-1]
        
        # Validar que no esté truncado
        if len(texto) >= 15:
            return texto
        return None
    except Exception as e:
        logger.error(f"Error usando Groq: {e}")
        return None

async def generar_gancho_ia(titulo: str, precio: str, original: str) -> Optional[str]:
    """
    Genera un gancho usando Gemini con rotación de llaves, espera paciente de rate limits,
    y Groq como respaldo. Reintenta pacientemente para no dejar publicaciones sin gancho.
    """
    precio_str = f"Precio en oferta: {precio}" if precio and precio != "No disponible" else "Precio desconocido"
    original_str = f"Precio original: {original}" if original and original != "No disponible" else ""
    
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

    models_to_try = [
        os.getenv('GEMINI_MODEL', 'gemini-3-flash-preview'),
        'gemini-2.5-flash',
        'gemini-2.0-flash'
    ]
    # Eliminar duplicados manteniendo orden
    gemini_models = []
    for m in models_to_try:
        if m and m not in gemini_models:
            gemini_models.append(m)

    keys = get_all_gemini_keys()
    
    # Si no hay llaves de Gemini o la librería no está instalada, ir directo a Groq
    if not keys or not genai:
        logger.info("No hay llaves de Gemini disponibles o librería no instalada. Intentando con Groq...")
        return await fallback_groq(prompt, system_instruction)

    max_rounds = 4  # Intentar hasta 4 rondas con paciencia
    for round_num in range(max_rounds):
        key, wait_time = get_next_available_key(keys)
        
        # Si todas las llaves de Gemini están temporalmente en cooldown (rate limit 429)
        if not key:
            logger.info(f"Todas las llaves de Gemini están en pausa temporal por cuota. Esperando {wait_time:.1f}s antes de reintentar...")
            # Si wait_time es largo y tenemos Groq, probamos Groq de una vez
            if wait_time > 10.0:
                groq_res = await fallback_groq(prompt, system_instruction)
                if groq_res:
                    return groq_res
            
            # Esperar el tiempo necesario para que una llave se libere
            await asyncio.sleep(min(wait_time, 30.0))
            key, _ = get_next_available_key(keys)
            if not key:
                # Si aún no hay llave libre, probar Groq
                groq_res = await fallback_groq(prompt, system_instruction)
                if groq_res:
                    return groq_res
                continue

        # Intentar con la llave seleccionada
        client = genai.Client(api_key=key)
        
        # Configuración con thinking desactivado (budget=0) y suficientes tokens para que no se trunque
        config_params = {
            "system_instruction": system_instruction,
            "temperature": 0.7,
            "max_output_tokens": 350,
        }
        try:
            # Desactivar thinking en Gemini 2.5 para que no consuma los tokens de salida en razonamiento
            config_params["thinking_config"] = types.ThinkingConfig(thinking_budget=0)
        except Exception:
            pass

        config = types.GenerateContentConfig(**config_params)

        for model_name in gemini_models:
            try:
                response = await client.aio.models.generate_content(
                    model=model_name,
                    contents=prompt,
                    config=config
                )
                texto = response.text.strip() if response.text else ""
                if texto:
                    if texto.startswith('"') and texto.endswith('"'):
                        texto = texto[1:-1]
                    
                    # Validar que no sea un texto incompleto o demasiado corto
                    if len(texto) >= 15:
                        return texto
                    else:
                        logger.warning(f"Gancho generado demasiado corto ('{texto}'), probando siguiente intento...")

            except Exception as e:
                error_msg = str(e)
                # Detección de límite de velocidad o cuota (429 / RESOURCE_EXHAUSTED)
                if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg or "quota" in error_msg.lower():
                    match = re.search(r'retry in (\d+(?:\.\d+)?)s', error_msg)
                    cooldown = float(match.group(1)) + 1.0 if match else 20.0
                    logger.warning(f"Límite de velocidad en Gemini (modelo {model_name}). Pausando esta llave por {cooldown:.1f}s...")
                    _key_cooldowns[key] = time.time() + cooldown
                    break  # Salir de modelos para probar la siguiente llave
                elif "not found" in error_msg.lower() or "404" in error_msg:
                    logger.warning(f"Modelo {model_name} no disponible en Gemini. Probando siguiente modelo...")
                    continue
                else:
                    logger.error(f"Error de Gemini ({model_name}): {e}. Intentando con Groq...")
                    groq_res = await fallback_groq(prompt, system_instruction)
                    if groq_res:
                        return groq_res
                    break

    # Si tras todas las rondas Gemini no respondió, intento final con Groq
    logger.info("Agotados los intentos con Gemini. Ejecutando intento final con Groq...")
    return await fallback_groq(prompt, system_instruction)
