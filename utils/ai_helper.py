import os
import logging
from google import genai
from typing import Optional

logger = logging.getLogger(__name__)

async def generar_gancho_ia(titulo: str, precio: str, original: str) -> Optional[str]:
    """Genera un gancho corto y atractivo para una oferta usando Gemini Flash."""
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        return None
        
    try:
        client = genai.Client(api_key=api_key)
        
        precio_str = f"Precio en oferta: {precio}" if precio and precio != "No disponible" else "Precio desconocido"
        original_str = f"Precio original: {original}" if original and original != "No disponible" else ""
        
        prompt = (
            f"Escribe una sola frase corta, MUY llamativa pero sin inventar nada, algo que tenga sentido  usando jerga dominicana (como si fueras un promotor de RD) "
            f"para animar a comprar esta oferta en un canal de Telegram. Usa palabras dominicanas (ej. klk, nítido, montro, jevi, mete mano, eso ta' duro, de lo mio, mi loco, wao para, rompe to', manito, eto se ta tornando, y frases actualizadas 2026.) "
            f"pero mantenlo entendible. Usa máximo 1 emoji.\n\n"
            f"Producto: {titulo}\n"
            f"{precio_str}\n"
            f"{original_str}\n\n"
            f"Tu respuesta (solo la frase, sin explicaciones):"
        )
        
        response = await client.aio.models.generate_content(
            model='gemini-1.5-flash',
            contents=prompt,
        )
        texto = response.text.strip()
        # Limpiar si empieza con comillas
        if texto.startswith('"') and texto.endswith('"'):
            texto = texto[1:-1]
        return texto
    except Exception as e:
        if ("429" in str(e) or "RESOURCE_EXHAUSTED" in str(e)) and os.getenv("GEMINI_API_KEY_BACKUP"):
            logger.warning("Límite de cuota alcanzado con la llave principal. Intentando con llave de respaldo...")
            try:
                client_backup = genai.Client(api_key=os.getenv("GEMINI_API_KEY_BACKUP"))
                response_backup = await client_backup.aio.models.generate_content(
                    model='gemini-1.5-flash',
                    contents=prompt,
                )
                texto_backup = response_backup.text.strip()
                if texto_backup.startswith('"') and texto_backup.endswith('"'):
                    texto_backup = texto_backup[1:-1]
                return texto_backup
            except Exception as e_backup:
                logger.warning(f"La llave de respaldo también falló: {e_backup}")
                return None
        elif "429" in str(e) or "RESOURCE_EXHAUSTED" in str(e):
            logger.warning("Límite de cuota gratuita de IA alcanzado (Error 429). Publicando sin gancho...")
        else:
            logger.error(f"Error al generar gancho con IA: {e}")
        return None
