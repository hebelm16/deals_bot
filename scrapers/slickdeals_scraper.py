import logging
from bs4 import BeautifulSoup
import httpx
from typing import List, Dict, Any
from tenacity import retry, stop_after_attempt, wait_fixed
import hashlib
import time

from .base_scraper import BaseScraper
from utils.models import Oferta

class SlickdealsScraper(BaseScraper):
    emoji = "🔥"

    def __init__(self, name: str, url: str, tag: str):
        super().__init__(name, url, tag)

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(5))
    async def obtener_ofertas(self) -> List[Oferta]:
        logging.info(f"Slickdeals: Iniciando scraping desde {self.url}")
        async with httpx.AsyncClient() as client:
            response = await client.get(self.url, timeout=30)
        logging.info(f"Slickdeals: Respuesta obtenida. Código de estado: {response.status_code}")
        soup = BeautifulSoup(response.content, 'html.parser')
        ofertas = []
        
        for oferta in soup.find_all('div', {'class': 'dealCard__content'}):
            try:
                titulo = self.limpiar_texto(oferta.find('a', {'class': 'dealCard__title'}).text)
                link = 'https://slickdeals.net' + oferta.find('a', {'class': 'dealCard__title'})['href']
                
                precio_elem = oferta.find('span', {'class': 'dealCard__price'})
                precio = self.limpiar_texto(precio_elem.text) if precio_elem else 'No disponible'
                
                precio_original_elem = oferta.find('span', {'class': 'dealCard__originalPrice'})
                precio_original = self.limpiar_texto(precio_original_elem.text) if precio_original_elem else None
                
                imagen_elem = oferta.find('img', {'class': 'dealCard__image'})
                imagen = imagen_elem['src'] if imagen_elem else 'No disponible'
                
                # Verificar si es una tarjeta de carga
                if "loading" in titulo.lower() or "cargando" in titulo.lower():
                    logging.warning("Se detectó una tarjeta de carga, ignorando...")
                    continue
                
                nueva_oferta = Oferta.create(
                    titulo=titulo,
                    precio=precio,
                    link=link,
                    tag=self.tag,
                    emoji=self.emoji,
                    precio_original=precio_original,
                    imagen=imagen
                )
                
                ofertas.append(nueva_oferta)
                logging.info(f"Slickdeals: Oferta procesada: {titulo}")
            except Exception as e:
                logging.error(f"Slickdeals: Error al procesar una oferta: {e}", exc_info=True)
                continue
        
        if not ofertas:
            logging.warning(f"Slickdeals: No se encontraron ofertas en {self.url}")
            return []
        else:
            logging.info(f"Slickdeals: Se encontraron {len(ofertas)} ofertas en total")
        
        return ofertas

    @staticmethod
    def limpiar_texto(texto: str) -> str:
        return ' '.join(texto.strip().split())
