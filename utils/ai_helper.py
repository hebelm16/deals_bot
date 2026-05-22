import os
import logging
import asyncio
import re
from typing import Optional
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

# Estado global para rotar las llaves de Gemini
_gemini_keys = []
_current_gemini_idx = 0
_keys_loaded = False

def get_next_gemini_key():
    global _gemini_keys, _current_gemini_idx, _keys_loaded
    if not _keys_loaded:
        config_keys = Config.GEMINI_API_KEYS
        if config_keys:
            _gemini_keys = [k.strip() for k in config_keys.split(',') if k.strip()]
        else:
            # Fallback a la llave singular si el usuario no usó GEMINI_API_KEYS
            if Config.GEMINI_API_KEY:
                _gemini_keys.append(Config.GEMINI_API_KEY)
            if Config.GEMINI_API_KEY_BACKUP:
                _gemini_keys.append(Config.GEMINI_API_KEY_BACKUP)
        _keys_loaded = True
        
    if not _gemini_keys:
        return None
        
    if _current_gemini_idx >= len(_gemini_keys):
        return None  # Todas las llaves están agotadas
        
    return _gemini_keys[_current_gemini_idx]

def mark_current_gemini_key_exhausted():
    global _current_gemini_idx
    logger.error(f"Marcando llave Gemini (índice {_current_gemini_idx}) como AGOTADA por hoy.")
    _current_gemini_idx += 1

async def fallback_groq(prompt: str, system_instruction: str) -> Optional[str]:
    api_key = Config.GROQ_API_KEY
    if not api_key or not AsyncGroq:
        logger.warning("Groq no está configurado o no está instalado (Llama 3 no disponible). Publicando sin IA.")
        return None
        
    try:
        logger.info("Generando gancho con Groq (Llama 3)...")
        client = AsyncGroq(api_key=api_key)
        response = await client.chat.completions.create(
            messages=[
                {"role": "system", "content": system_instruction},
                {"role": "user", "content": prompt}
            ],
            model="llama-3.1-8b-instant",
            temperature=0.7,
            max_tokens=60
        )
        texto = response.choices[0].message.content.strip()
        if texto.startswith('"') and texto.endswith('"'):
            texto = texto[1:-1]
        return texto
    except Exception as e:
        logger.error(f"Error usando Groq: {e}")
        return None

async def generar_gancho_ia(titulo: str, precio: str, original: str) -> Optional[str]:
    """Genera un gancho usando Gemini con rotación de llaves, o Groq como Plan B."""
    precio_str = f"Precio en oferta: {precio}" if precio and precio != "No disponible" else "Precio desconocido"
    original_str = f"Precio original: {original}" if original and original != "No disponible" else ""
    
    prompt = f"Producto: {titulo}\n{precio_str}\n{original_str}"
    
    system_instruction = (
        "Eres un carismático promotor de ofertas de República Dominicana. Tu objetivo es crear "
        "ganchos súper llamativos de UNA SOLA oración corta para compartir en Telegram. "
        "Usa jerga dominicana natural (klk, nítido, montro, jevi, mete mano, de lo mio, etc) "
        "pero asegurate de que tenga SENTIDO LÓGICO con el producto que estás promocionando. "
        "NO inventes características ni prometas cosas que no están en el texto. "
        "Mantén la respuesta directa, clara y usa máximo 1 emoji al final."
    )

    while True:
        api_key = get_next_gemini_key()
        if not api_key or not genai:
            logger.warning("No quedan llaves Gemini disponibles o librería no instalada. Intentando con Groq...")
            return await fallback_groq(prompt, system_instruction)
            
        client = genai.Client(api_key=api_key)
        config = types.GenerateContentConfig(
            system_instruction=system_instruction,
            temperature=0.7,
        )

        max_retries = 3
        key_exhausted = False
        
        for intento in range(max_retries):
            try:
                response = await client.aio.models.generate_content(
                    model='gemini-2.5-flash',
                    contents=prompt,
                    config=config
                )
                texto = response.text.strip()
                if texto.startswith('"') and texto.endswith('"'):
                    texto = texto[1:-1]
                return texto
                
            except Exception as e:
                error_msg = str(e)
                if "429" in error_msg or "RESOURCE_EXHAUSTED" in error_msg:
                    match = re.search(r'retry in (\d+(?:\.\d+)?)s', error_msg)
                    if match:
                        wait_time = int(float(match.group(1))) + 2
                    else:
                        wait_time = 60
                    
                    # Si pide esperar más de un minuto, probablemente chocamos con el límite diario
                    if wait_time > 60 or intento == max_retries - 1:
                        logger.warning(f"Límite fuerte de cuota alcanzado (espera {wait_time}s). Cambiando de llave Gemini...")
                        mark_current_gemini_key_exhausted()
                        key_exhausted = True
                        break # Salimos del bucle de reintentos para intentar la siguiente llave
                    else:
                        logger.warning(f"Límite de velocidad (429). Reintentando en {wait_time}s (Intento {intento+1}/{max_retries})...")
                        await asyncio.sleep(wait_time)
                else:
                    logger.error(f"Error de Gemini: {e}. Intentando fallback a Groq...")
                    return await fallback_groq(prompt, system_instruction)
                    
        # Si la llave se agotó en el bucle for, el while True continuará y sacará la siguiente llave.
        if not key_exhausted:
            # Si salimos del for por otro motivo (ej break no ejecutado, aunque deberíamos haber retornado)
            break
            
    return None
