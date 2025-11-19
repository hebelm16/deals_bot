import logging
from bs4 import BeautifulSoup
import requests
from typing import List, Dict, Any
from retrying import retry
import re

from .base_scraper import BaseScraper

class DealsOfAmericaScraper(BaseScraper):
    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def obtener_ofertas(self) -> List[Dict[str, Any]]:
        logging.info(f"DealsOfAmerica: Iniciando scraping desde {self.url}")
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        try:
            response = requests.get(self.url, headers=headers, timeout=30)
            response.raise_for_status()
            logging.info(f"DealsOfAmerica: Respuesta obtenida. Código de estado: {response.status_code}")
        except requests.RequestException as e:
            logging.error(f"DealsOfAmerica: Error al obtener la página: {e}")
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        ofertas = []
        
        secciones_oferta = soup.find_all('div', class_='deal-item-container')
        logging.info(f"DealsOfAmerica: Se encontraron {len(secciones_oferta)} secciones de oferta")
        
        for seccion in secciones_oferta:
            try:
                oferta = self.extraer_oferta(seccion)
                if oferta:
                    ofertas.append(oferta)
                    logging.info(f"DealsOfAmerica: Oferta procesada: {oferta['titulo']}")
            except Exception as e:
                logging.error(f"DealsOfAmerica: Error al procesar una oferta: {e}", exc_info=True)
        
        if not ofertas:
            logging.warning(f"DealsOfAmerica: No se encontraron ofertas en {self.url}")
        else:
            logging.info(f"DealsOfAmerica: Se encontraron {len(ofertas)} ofertas en total")
        
        return ofertas

    def extraer_oferta(self, seccion: BeautifulSoup) -> Dict[str, Any] | None:
        titulo_elem = seccion.find('a', class_='deal-title')
        titulo = self.limpiar_texto(titulo_elem.text) if titulo_elem else None

        if not titulo:
            return None

        link = titulo_elem['href'] if titulo_elem and titulo_elem.has_attr('href') else None
        if link and not link.startswith('http'):
            link = f"https://www.dealsofamerica.com{link}"

        precio_elem = seccion.find('span', class_='price')
        precio = self.limpiar_texto(precio_elem.text) if precio_elem else 'No disponible'

        imagen_elem = seccion.find('img')
        imagen = imagen_elem['src'] if imagen_elem and imagen_elem.has_attr('src') else 'No disponible'

        cupon_elem = seccion.find('div', class_='coupon-code')
        cupon = self.limpiar_texto(cupon_elem.text) if cupon_elem else None

        if all([titulo, link]):
            return {
                'titulo': titulo,
                'precio': precio,
                'precio_original': None, # La web no parece tener este campo de forma consistente
                'link': link,
                'imagen': imagen,
                'tag': self.tag,
                'cupon': cupon,
                'info_cupon': None
            }
        return None
