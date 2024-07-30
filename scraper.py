import logging
from bs4 import BeautifulSoup
import requests
from typing import List, Dict, Any
from retrying import retry
import hashlib
import time
import re

class BaseScraper:
    def __init__(self, url: str, tag: str):
        self.url = url
        self.tag = tag

    @staticmethod
    def limpiar_texto(texto: str) -> str:
        return ' '.join(texto.lower().split())

class SlickdealsScraper(BaseScraper):
    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def obtener_ofertas(self) -> List[Dict[str, Any]]:
        response = requests.get(self.url)
        soup = BeautifulSoup(response.content, 'html.parser')
        ofertas = []
        
        for oferta in soup.find_all('div', {'class': 'dealCard__content'}):
            try:
                titulo = self.limpiar_texto(oferta.find('a', {'class': 'dealCard__title'}).text.strip())
                link = 'https://slickdeals.net' + oferta.find('a', {'class': 'dealCard__title'})['href']
                
                precio_elem = oferta.find('span', {'class': 'dealCard__price'})
                precio = self.limpiar_texto(precio_elem.text.strip()) if precio_elem else 'No disponible'
                
                precio_original_elem = oferta.find('span', {'class': 'dealCard__originalPrice'})
                precio_original = self.limpiar_texto(precio_original_elem.text.strip()) if precio_original_elem else None
                
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
                logging.info(f"Oferta procesada exitosamente: {titulo}")
            except Exception as e:
                logging.error(f"Error al procesar una oferta de Slickdeals: {e}", exc_info=True)
                continue
        
        if not ofertas:
            logging.warning(f"No se encontraron ofertas en {self.url}")
        
        return ofertas

    @staticmethod
    def generar_id_oferta(titulo: str, precio: str, link: str) -> str:
        return hashlib.md5(f"{titulo}|{precio}|{link}".encode()).hexdigest()

class DealsnewsScraper(BaseScraper):
    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    def obtener_ofertas(self) -> List[Dict[str, Any]]:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'}
        response = requests.get(self.url, headers=headers)
        response.raise_for_status()
        
        soup = BeautifulSoup(response.text, 'html.parser')
        ofertas = []
        
        secciones_oferta = soup.find_all('div', class_='flex-cell flex-cell-size-1of1')
        
        for seccion in secciones_oferta:
            if seccion.find('div', class_='details-container'):
                try:
                    oferta = {}
                    
                    titulo = seccion.find('div', class_='title limit-height limit-height-large-2 limit-height-small-2')
                    oferta['titulo'] = titulo['title'].strip() if titulo and 'title' in titulo.attrs else 'No disponible'
                    
                    precio_elem = seccion.find('div', class_='callout limit-height limit-height-large-1 limit-height-small-1')
                    if precio_elem:
                        precio_texto = precio_elem.text.strip()
                        oferta['precio'] = 'Gratis' if 'free' in precio_texto.lower() else precio_texto
                    else:
                        oferta['precio'] = 'No disponible'
                    oferta['precio_original'] = None
                    
                    imagen = seccion.find('img', class_='native-lazy-img')
                    oferta['imagen'] = imagen['src'] if imagen and 'src' in imagen.attrs else 'No disponible'
                    
                    enlace = seccion.find('a', class_='attractor')
                    oferta['link'] = enlace['href'] if enlace and 'href' in enlace.attrs else 'No disponible'
                    
                    cupon_elem = seccion.find('div', class_='snippet summary')
                    if cupon_elem and 'title' in cupon_elem.attrs:
                        oferta['info_cupon'] = cupon_elem['title'].strip()
                        cupon_matches = re.findall(r'"([^"]*)"', oferta['info_cupon'])
                        if cupon_matches:
                            oferta['cupon'] = cupon_matches[-1]
                        else:
                            oferta['cupon'] = None
                    else:
                        oferta['info_cupon'] = None
                        oferta['cupon'] = None
                    
                    oferta['id'] = self.generar_id_oferta(oferta['titulo'], oferta['precio'], oferta['link'])
                    oferta['tag'] = self.tag
                    oferta['timestamp'] = int(time.time())
                    
                    ofertas.append(oferta)
                    logging.info(f"DealNews - Oferta procesada: {oferta['titulo']}")
                except Exception as e:
                    logging.error(f"Error al procesar una oferta de DealNews: {e}", exc_info=True)
                    continue
        
        if not ofertas:
            logging.warning(f"No se encontraron ofertas en {self.url}")
        else:
            logging.info(f"DealNews - Se encontraron {len(ofertas)} ofertas en total")
        
        return ofertas

    @staticmethod
    def generar_id_oferta(titulo: str, precio: str, link: str) -> str:
        return hashlib.md5(f"{titulo}|{precio}|{link}".encode()).hexdigest()
