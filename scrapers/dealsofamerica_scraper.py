import logging
from bs4 import BeautifulSoup
from typing import List, Dict, Any
from playwright.async_api import async_playwright, TimeoutError as PlaywrightTimeoutError
import asyncio
import time
import hashlib
import re

from .base_scraper import BaseScraper

class DealsOfAmericaScraper(BaseScraper):
    async def obtener_ofertas(self) -> List[Dict[str, Any]]:
        logging.info(f"DealsOfAmerica: Iniciando scraping con Playwright desde {self.url}")
        ofertas = []
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                await page.goto(self.url, timeout=60000)

                # Intentar aceptar el banner de cookies si aparece
                try:
                    logging.info("DealsOfAmerica: Buscando banner de cookies...")
                    await page.click('#onetrust-accept-btn-handler', timeout=5000)
                    logging.info("DealsOfAmerica: Banner de cookies aceptado.")
                    await page.wait_for_load_state('networkidle') # Esperar a que la página se estabilice
                except PlaywrightTimeoutError:
                    logging.info("DealsOfAmerica: No se encontró el banner de cookies o ya estaba aceptado.")
                
                # Esperar a que los contenedores de las ofertas estén presentes
                await page.wait_for_selector('section.deal.row', timeout=30000)
                
                content = await page.content()
                
                await browser.close()
        except (PlaywrightTimeoutError, Exception) as e:
            logging.error(f"DealsOfAmerica: Error durante la navegación con Playwright: {e}")
            return []

        soup = BeautifulSoup(content, 'html.parser')
        secciones_oferta = soup.find_all('section', class_='deal row')
        logging.info(f"DealsOfAmerica: Se encontraron {len(secciones_oferta)} secciones de oferta tras renderizado.")
        
        for seccion in secciones_oferta:
            try:
                oferta = self.extraer_oferta(seccion)
                if oferta:
                    ofertas.append(oferta)
                    logging.debug(f"DealsOfAmerica: Oferta procesada: {oferta['titulo']}")
            except Exception as e:
                logging.error(f"DealsOfAmerica: Error al procesar una oferta: {e}", exc_info=True)
        
        if not ofertas:
            logging.warning(f"DealsOfAmerica: No se encontraron ofertas en {self.url} después de usar Playwright.")
        else:
            logging.info(f"DealsOfAmerica: Se encontraron {len(ofertas)} ofertas en total.")
        
        return ofertas

    def extraer_oferta(self, seccion: BeautifulSoup) -> Dict[str, Any] | None:
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
                # Patrón para buscar "w/Coupon CODIGO", "coupon CODIGO", "code CODIGO", etc.
                # El código suele ser alfanumérico y de 4+ caracteres.
                match = re.search(r'(?:w/coupon|coupon|code)\s+([A-Z0-9]{4,})', info_cupon, re.IGNORECASE)
                if match:
                    cupon = match.group(1)

            if all([titulo, link]):
                return {
                    'id': self.generar_id_oferta(titulo, precio, link),
                    'titulo': titulo,
                    'precio': precio,
                    'precio_original': precio_original,
                    'link': link,
                    'imagen': imagen,
                    'tag': self.tag,
                    'timestamp': int(time.time()),
                    'cupon': cupon,
                    'info_cupon': info_cupon
                }
            return None
        except Exception as e:
            logging.error(f"DealsOfAmerica: Error al extraer datos de una sección: {e}")
            return None

    @staticmethod
    def generar_id_oferta(titulo: str, precio: str, link: str) -> str:
        """Genera un ID único para la oferta."""
        return hashlib.md5(f"{titulo}|{precio}|{link}".encode()).hexdigest()

    def obtener_ofertas_sync(self) -> List[Dict[str, Any]]:
        """Wrapper síncrono para ejecutar el método asíncrono."""
        return asyncio.run(self.obtener_ofertas())