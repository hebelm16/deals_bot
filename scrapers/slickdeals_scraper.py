from .base_scraper import BaseScraper
import requests
from bs4 import BeautifulSoup
import logging
import time
import hashlib

class SlickdealsScraper(BaseScraper):
    def obtener_ofertas(self):
        logging.info(f"Slickdeals: Iniciando scraping desde {self.url}")
        response = requests.get(self.url)
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
                
                oferta_id = self.generar_id_oferta(titulo, precio, link)
                
                nueva_oferta = {
                    'id': oferta_id,
                    'titulo': titulo,
                    'precio': precio,
                    'precio_original': precio_original,
                    'link': link,
                    'imagen': imagen,
                    'tag': self.tag,
                    'timestamp': int(time.time()),
                    'cupon': None,
                    'info_cupon': None
                }
                
                ofertas.append(nueva_oferta)
                logging.info(f"Slickdeals: Oferta procesada: {titulo}")
            except Exception as e:
                logging.error(f"Slickdeals: Error al procesar una oferta: {e}", exc_info=True)
                continue
        
        if not ofertas:
            logging.warning(f"Slickdeals: No se encontraron ofertas en {self.url}")
        else:
            logging.info(f"Slickdeals: Se encontraron {len(ofertas)} ofertas en total")
        
        return ofertas

    @staticmethod
    def generar_id_oferta(titulo: str, precio: str, link: str) -> str:
        return hashlib.md5(f"{titulo}|{precio}|{link}".encode()).hexdigest()