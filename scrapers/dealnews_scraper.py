import logging
from bs4 import BeautifulSoup
import requests
from typing import List, Dict, Any
from retrying import retry
import hashlib
import time
import re

from .base_scraper import BaseScraper

class DealsnewsScraper(BaseScraper):
    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def obtener_ofertas(self) -> List[Dict[str, Any]]:
        logging.info(f"DealNews: Iniciando scraping desde {self.url}")
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        try:
            response = requests.get(self.url, headers=headers, timeout=30)
            response.raise_for_status()
            logging.info(f"DealNews: Respuesta obtenida. Código de estado: {response.status_code}")
        except requests.RequestException as e:
            logging.error(f"DealNews: Error al obtener la página: {e}")
            return []
        
        soup = BeautifulSoup(response.text, 'html.parser')
        ofertas = []
        
        secciones_oferta = soup.find_all('div', class_='flex-cell flex-cell-size-1of1')
        logging.info(f"DealNews: Se encontraron {len(secciones_oferta)} secciones de oferta")
        
        for i, seccion in enumerate(secciones_oferta):
            logging.debug(f"DealNews: Procesando sección de oferta {i+1}")
            try:
                oferta = self.extraer_oferta(seccion)
                if oferta:
                    ofertas.append(oferta)
                    logging.info(f"DealNews: Oferta procesada: {oferta['titulo']}")
                else:
                    logging.warning(f"DealNews: No se pudo extraer oferta de la sección {i+1}")
            except Exception as e:
                logging.error(f"DealNews: Error al procesar una oferta: {e}", exc_info=True)
        
        if not ofertas:
            logging.warning(f"DealNews: No se encontraron ofertas en {self.url}")
        else:
            logging.info(f"DealNews: Se encontraron {len(ofertas)} ofertas en total")
        
        return ofertas

    def extraer_oferta(self, seccion):
        oferta = {}
        
        titulo = seccion.find('div', class_='title limit-height limit-height-large-2 limit-height-small-2')
        oferta['titulo'] = self.limpiar_texto(titulo.text) if titulo else None
        logging.debug(f"DealNews: Título encontrado: {oferta['titulo']}")
        
        precio_elem = seccion.find('div', class_='callout limit-height limit-height-large-1 limit-height-small-1')
        if precio_elem:
            precio_texto = precio_elem.get_text(strip=True)
            precio_match = re.search(r'\$\d+(?:\.\d+)?', precio_texto)
            if precio_match:
                oferta['precio'] = precio_match.group()
            else:
                oferta['precio'] = self.limpiar_texto(precio_texto)
            
            precio_original_elem = precio_elem.find('span', class_='callout-comparison')
            if precio_original_elem:
                oferta['precio_original'] = self.limpiar_texto(precio_original_elem.text)
            else:
                oferta['precio_original'] = None
        else:
            oferta['precio'] = 'No disponible'
            oferta['precio_original'] = None
        
        logging.debug(f"DealNews: Precio encontrado: {oferta['precio']}")
        logging.debug(f"DealNews: Precio original encontrado: {oferta['precio_original']}")
        
        imagen = seccion.find('img', class_='native-lazy-img')
        oferta['imagen'] = imagen['src'] if imagen and 'src' in imagen.attrs else None
        logging.debug(f"DealNews: Imagen encontrada: {oferta['imagen']}")
        
        enlace = seccion.find('a', class_='attractor')
        oferta['link'] = enlace['href'] if enlace and 'href' in enlace.attrs else None
        logging.debug(f"DealNews: Enlace encontrado: {oferta['link']}")
        
        info_elem = seccion.find('div', class_='snippet summary')
        if info_elem:
            oferta['info_cupon'] = self.limpiar_texto(info_elem.text)
            cupon_matches = re.findall(r'"([^"]*)"', oferta['info_cupon'])
            oferta['cupon'] = cupon_matches[-1] if cupon_matches else None
        else:
            oferta['info_cupon'] = "No se requiere cupón"
            oferta['cupon'] = None
        logging.debug(f"DealNews: Info/Cupón encontrado: {oferta['info_cupon']}")
        
        if all([oferta['titulo'], oferta['precio'], oferta['link']]):
            oferta['id'] = self.generar_id_oferta(oferta['titulo'], oferta['precio'], oferta['link'])
            oferta['tag'] = self.tag
            oferta['timestamp'] = int(time.time())
            return oferta
        else:
            logging.warning("DealNews: Oferta incompleta ignorada")
            return None

    @staticmethod
    def generar_id_oferta(titulo: str, precio: str, link: str) -> str:
        return hashlib.md5(f"{titulo}|{precio}|{link}".encode()).hexdigest()

    @staticmethod
    def limpiar_texto(texto: str) -> str:
        return ' '.join(texto.strip().split())
