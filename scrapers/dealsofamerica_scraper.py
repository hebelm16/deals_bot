import logging
from bs4 import BeautifulSoup
import httpx
from typing import List, Optional
from tenacity import retry, stop_after_attempt, wait_fixed
import random
import re

from .base_scraper import BaseScraper
from utils.models import Oferta

class DealsOfAmericaScraper(BaseScraper):
    emoji = "🇺🇸"

    def __init__(self, name: str, url: str, tag: str):
        super().__init__(name, url, tag)

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    async def obtener_ofertas(self) -> List[Oferta]:
        logging.info(f"DealsOfAmerica: Iniciando scraping desde {self.url}")
        user_agents = [
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:122.0) Gecko/20100101 Firefox/122.0'
        ]
        headers = {
            'User-Agent': random.choice(user_agents),
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
        }
        
        try:
            async with httpx.AsyncClient(follow_redirects=True) as client:
                response = await client.get(self.url, headers=headers, timeout=30.0)
            response.raise_for_status()
            logging.info(f"DealsOfAmerica: Respuesta obtenida. Código de estado: {response.status_code}")
        except httpx.RequestError as e:
            logging.error(f"DealsOfAmerica: Error de red al obtener la página: {e}")
            return []
        except httpx.HTTPStatusError as e:
            logging.error(f"DealsOfAmerica: Error HTTP {e.response.status_code}: {e}")
            return []
        except Exception as e:
            logging.error(f"DealsOfAmerica: Error inesperado al hacer petición: {e}")
            return []

        soup = BeautifulSoup(response.text, 'html.parser')
        secciones_oferta = soup.find_all('section', class_='deal row')
        logging.info(f"DealsOfAmerica: Se encontraron {len(secciones_oferta)} secciones de oferta.")
        
        ofertas = []
        for seccion in secciones_oferta:
            try:
                oferta = self.extraer_oferta(seccion)
                if oferta:
                    ofertas.append(oferta)
                    logging.debug(f"DealsOfAmerica: Oferta procesada: {oferta.titulo}")
            except Exception as e:
                logging.error(f"DealsOfAmerica: Error al procesar una oferta: {e}", exc_info=True)
        
        if not ofertas:
            logging.warning(f"DealsOfAmerica: No se encontraron ofertas en {self.url}.")
        else:
            logging.info(f"DealsOfAmerica: Se encontraron {len(ofertas)} ofertas en total.")
        
        return ofertas

    def extraer_oferta(self, seccion: BeautifulSoup) -> Optional[Oferta]:
        try:
            # El título y el enlace están en la sección principal de detalles
            title_section = seccion.find('div', class_='title')
            titulo_elem = title_section.find('a') if title_section else None
            titulo = self.limpiar_texto(titulo_elem.text) if titulo_elem else None

            if not titulo:
                return None

            link = titulo_elem.get('href') if titulo_elem else None
            if link and not link.startswith('http'):
                link = f"https://www.dealsofamerica.com{link}"

            # El precio está en la sección de la imagen y en la principal. Usamos la de la imagen.
            image_section = seccion.find('div', class_='start_div')
            precio_elem = image_section.find('span', class_='our-price') if image_section else None
            precio = self.limpiar_texto(precio_elem.text) if precio_elem else 'No disponible'

            precio_original_elem = image_section.find('span', class_='list-price') if image_section else None
            precio_original = self.limpiar_texto(precio_original_elem.text) if precio_original_elem else None

            imagen_elem = image_section.find('img') if image_section else None
            imagen = imagen_elem.get('src') if imagen_elem else None

            # La información del cupón o detalles adicionales están en 'more_details'
            cupon = None
            info_cupon_elem = seccion.find('section', class_='more_details')
            info_cupon = self.limpiar_texto(info_cupon_elem.get_text(separator=' ')) if info_cupon_elem else None

            # Intentar extraer el código del cupón de forma más específica
            if info_cupon:
                match = re.search(r'(?:w/coupon|coupon|code)\s+([A-Z0-9]{4,})', info_cupon, re.IGNORECASE)
                if match:
                    cupon = match.group(1)

            if all([titulo, link]):
                return Oferta.create(
                    titulo=titulo,
                    precio=precio,
                    link=link,
                    tag=self.tag,
                    emoji=self.emoji,
                    precio_original=precio_original,
                    imagen=imagen,
                    cupon=cupon,
                    info_cupon=info_cupon
                )
            return None
        except Exception as e:
            logging.error(f"DealsOfAmerica: Error al extraer datos de una sección: {e}")
            return None