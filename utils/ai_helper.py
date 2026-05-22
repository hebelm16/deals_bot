import os
import logging
import asyncio
import re
from google import genai
from google.genai import types
from typing import Optional

logger = logging.getLogger(__name__)

async def generar_gancho_ia(titulo: str, precio: str, original: str) -> Optional[str]:
    """Genera un gancho corto y atractivo para una oferta usando Gemini con System Instructions."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
        
    client = genai.Client(api_key=api_key)
    precio_str = f"Precio en oferta: {precio}" if precio and precio != "No disponible" else "Precio desconocido"
    original_str = f"Precio original: {original}" if original and original != "No disponible" else ""
    
    prompt = f"Producto: {titulo}\n{precio_str}\n{original_str}"
    
    system_instruction = (
        "Eres un carismático promotor de ofertas de República Dominicana. Tu objetivo es crear "
        "ganchos súper llamativos de UNA SOLA oración corta para compartir en Telegram. "
        "Usa jerga dominicana natural (klk, nítido, montro, jevi, mete mano, de lo mio, apero, etc) "
        "pero asegurate de que tenga SENTIDO LÓGICO con el producto que estás promocionando. "
        "NO inventes características ni prometas cosas que no están en el texto. "
        "Mantén la respuesta directa, clara y usa máximo 1 emoji al final."
    )
    
    config = types.GenerateContentConfig(
        system_instruction=system_instruction,
        temperature=0.7,
    )

    max_retries = 3
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
                # Si fallamos en la cuota y hay llave de respaldo en el último intento
                if intento == max_retries - 1 and os.getenv("GEMINI_API_KEY_BACKUP"):
                    logger.warning("Límite de cuota agotado. Intentando con llave de respaldo...")
                    try:
                        client_backup = genai.Client(api_key=os.getenv("GEMINI_API_KEY_BACKUP"))
                        response_backup = await client_backup.aio.models.generate_content(
                            model='gemini-2.5-flash',
                            contents=prompt,
                            config=config
                        )
                        texto_backup = response_backup.text.strip()
                        if texto_backup.startswith('"') and texto_backup.endswith('"'):
                            texto_backup = texto_backup[1:-1]
                        return texto_backup
                    except Exception as e_backup:
                        logger.warning(f"La llave de respaldo también falló: {e_backup}")
                        return None
                elif intento < max_retries - 1:
                    # Extraer el tiempo de espera exacto que pide Google (ej: retry in 58.29s)
                    match = re.search(r'retry in (\d+(?:\.\d+)?)s', error_msg)
                    if match:
                        wait_time = int(float(match.group(1))) + 2  # Añadimos 2s de margen
                    else:
                        wait_time = 60  # Por defecto esperamos 1 minuto si no dice cuánto
                        
                    logger.warning(f"Error de cuota (429). Google pide esperar. Pausando el bot por {wait_time} segundos...")
                    await asyncio.sleep(wait_time)
                else:
                    logger.warning("Límite de cuota gratuita alcanzado. Publicando sin gancho...")
                    return None
            else:
                logger.error(f"Error al generar gancho con IA: {e}")
                return None
    return None
