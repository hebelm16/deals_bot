from .base_scraper import BaseScraper
import requests
from bs4 import BeautifulSoup
import logging
import time
import hashlib

class DealsnewsScraper(BaseScraper):
    def obtener_ofertas(self):
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
        oferta['precio'] = self.limpiar_texto(precio_elem.text) if precio_elem else None
        oferta['precio'] = 'Gratis' if oferta['precio'] and 'free' in oferta['precio'].lower() else oferta['precio']
        logging.debug(f"DealNews: Precio encontrado: {oferta['precio']}")
        
        imagen = seccion.find('img', class_='native-lazy-img')
        oferta['imagen'] = imagen['src'] if imagen and 'src' in imagen.attrs else None
        logging.debug(f"DealNews: Imagen encontrada: {oferta['imagen']}")
        
        enlace = seccion.find('a', class_='attractor')
        oferta['link'] = enlace['href'] if enlace and 'href' in enlace.attrs else None
        logging.debug(f"DealNews: Enlace encontrado: {oferta['link']}")
        
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
