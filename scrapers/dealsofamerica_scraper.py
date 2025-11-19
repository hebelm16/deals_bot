import logging
from bs4 import BeautifulSoup
from typing import List, Dict, Any
from playwright.async_api import async_playwright
import asyncio

from .base_scraper import BaseScraper

class DealsOfAmericaScraper(BaseScraper):
    async def obtener_ofertas(self) -> List[Dict[str, Any]]:
        logging.info(f"DealsOfAmerica: Iniciando scraping con Playwright desde {self.url}")
        ofertas = []
        
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch()
                page = await browser.new_page()
                
                await page.goto(self.url, timeout=60000)
                
                # Esperar a que los contenedores de las ofertas estén presentes
                await page.wait_for_selector('div.deal-item-container', timeout=30000)
                
                content = await page.content()
                
                # --- Bloque de Debugging ---
                try:
                    with open("debug_dealsofamerica.html", "w", encoding="utf-8") as f:
                        f.write(content)
                    logging.info("DealsOfAmerica: HTML de debugging guardado en debug_dealsofamerica.html")
                except Exception as e:
                    logging.error(f"DealsOfAmerica: No se pudo guardar el archivo de debug: {e}")
                # --- Fin del Bloque de Debugging ---

                await browser.close()
        except Exception as e:
            logging.error(f"DealsOfAmerica: Error durante la navegación con Playwright: {e}")
            return []

        soup = BeautifulSoup(content, 'html.parser')
        secciones_oferta = soup.find_all('div', class_='deal-item-container')
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
                'precio_original': None,
                'link': link,
                'imagen': imagen,
                'tag': self.tag,
                'cupon': cupon,
                'info_cupon': None
            }
        return None