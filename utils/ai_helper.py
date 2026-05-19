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
            f"Escribe una sola frase corta, MUY llamativa y usando jerga dominicana (como si fueras un promotor de RD) "
            f"para animar a comprar esta oferta en un canal de Telegram. Usa palabras dominicanas (ej. klk, nítido, montro, jevi, mete mano, eso ta' duro, de lo mio, mi loco, wao para, rompe to', manito, eto se ta tornando, y frases actualizadas 2026.) "
            f"pero mantenlo entendible. Usa máximo 1 emoji.\n\n"
            f"Producto: {titulo}\n"
            f"{precio_str}\n"
            f"{original_str}\n\n"
            f"Tu respuesta (solo la frase, sin explicaciones):"
        )
        
        response = await client.aio.models.generate_content(
            model='gemini-2.5-flash',
            contents=prompt,
        )
        texto = response.text.strip()
        # Limpiar si empieza con comillas
        if texto.startswith('"') and texto.endswith('"'):
            texto = texto[1:-1]
        return texto
    except Exception as e:
        logger.error(f"Error al generar gancho con IA: {e}")
        return None
