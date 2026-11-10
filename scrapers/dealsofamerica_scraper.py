"""Scraper de DealsOfAmerica (HTML)."""

import logging
from typing import List, Optional
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup
from tenacity import retry, stop_after_attempt, wait_fixed

from scrapers.base_scraper import BaseScraper, ScraperError
from utils.models import Oferta

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


class DealsOfAmericaScraper(BaseScraper):
    emoji = "🇺🇸"

    def __init__(self, name: str, url: str, tag: str):
        super().__init__(name, url, tag)

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(3), reraise=True)
    async def obtener_ofertas(self) -> List[Oferta]:
        logger.info("DealsOfAmerica: iniciando scraping desde %s", self.url)
        try:
            async with httpx.AsyncClient(
                headers=HEADERS, follow_redirects=True, timeout=30
            ) as client:
                response = await client.get(self.url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ScraperError(
                f"DealsOfAmerica no respondió correctamente: {exc}"
            ) from exc

        soup = BeautifulSoup(response.text, "html.parser")
        secciones = soup.find_all("section", class_="deal row")
        logger.info("DealsOfAmerica: %s secciones de oferta", len(secciones))

        ofertas: List[Oferta] = []
        for seccion in secciones:
            try:
                oferta = self.extraer_oferta(seccion)
                if oferta:
                    ofertas.append(oferta)
            except Exception as exc:  # noqa: BLE001
                logger.error("DealsOfAmerica: error al procesar una oferta: %s", exc)

        if not ofertas:
            logger.warning(
                "DealsOfAmerica: no se encontraron ofertas en %s", self.url
            )
        else:
            logger.info("DealsOfAmerica: %s ofertas encontradas", len(ofertas))
        return ofertas

    def extraer_oferta(self, seccion) -> Optional[Oferta]:
        title_section = seccion.find("div", class_="title")
        titulo_el = title_section.find("a") if title_section else None
        if not titulo_el:
            return None
        titulo = self.limpiar_texto(titulo_el.get_text())
        if not titulo:
            return None

        link = titulo_el.get("href")
        if not link:
            return None
        link = urljoin(self.url, link)

        image_section = seccion.find("div", class_="start_div")
        precio = "No disponible"
        precio_original: Optional[str] = None
        imagen = None
        if image_section:
            precio_el = image_section.find("span", class_="our-price")
            if precio_el:
                precio = self.limpiar_texto(precio_el.get_text()) or "No disponible"
            original_el = image_section.find("span", class_="list-price")
            if original_el:
                precio_original = self.extraer_precio(original_el.get_text())
                if not precio_original:
                    precio_original = self.limpiar_texto(original_el.get_text())
            img = image_section.find("img")
            if img:
                imagen = (
                    img.get("src")
                    or img.get("data-src")
                    or img.get("data-lazy-src")
                )
                if imagen:
                    imagen = urljoin(self.url, imagen)

        info: Optional[str] = None
        cupon: Optional[str] = None
        info_el = seccion.find("section", class_="more_details")
        if info_el:
            texto_info = self.limpiar_texto(info_el.get_text(separator=" ", strip=True))
            cupon = self.extraer_cupon(texto_info)
            if texto_info and "no se requiere cupón" not in texto_info.lower():
                info = self.limpiar_info(texto_info)

        return Oferta.create(
            titulo=titulo,
            precio=precio,
            link=link,
            tag=self.tag,
            emoji=self.emoji,
            precio_original=precio_original,
            imagen=imagen,
            cupon=cupon,
            info_cupon=info,
        )
