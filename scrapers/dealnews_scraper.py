"""Scraper de DealNews (HTML)."""

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


class DealsnewsScraper(BaseScraper):
    emoji = "📰"

    def __init__(self, name: str, url: str, tag: str):
        super().__init__(name, url, tag)

    @retry(stop=stop_after_attempt(3), wait=wait_fixed(3), reraise=True)
    async def obtener_ofertas(self) -> List[Oferta]:
        logger.info("DealNews: iniciando scraping desde %s", self.url)
        try:
            async with httpx.AsyncClient(
                headers=HEADERS, follow_redirects=True, timeout=30
            ) as client:
                response = await client.get(self.url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ScraperError(f"DealNews no respondió correctamente: {exc}") from exc

        soup = BeautifulSoup(response.text, "html.parser")
        secciones = soup.find_all("div", class_="flex-cell flex-cell-size-1of1")
        logger.info("DealNews: %s secciones de oferta", len(secciones))

        ofertas: List[Oferta] = []
        for indice, seccion in enumerate(secciones, start=1):
            try:
                oferta = self.extraer_oferta(seccion)
                if oferta:
                    ofertas.append(oferta)
                else:
                    logger.debug("DealNews: sección %s sin datos completos", indice)
            except Exception as exc:  # noqa: BLE001
                logger.error("DealNews: error al procesar una oferta: %s", exc)

        if not ofertas:
            logger.warning("DealNews: no se encontraron ofertas en %s", self.url)
        else:
            logger.info("DealNews: %s ofertas encontradas", len(ofertas))
        return ofertas

    def extraer_oferta(self, seccion) -> Optional[Oferta]:
        titulo_el = seccion.find(
            "div", class_="title limit-height limit-height-large-2 limit-height-small-2"
        )
        if not titulo_el:
            titulo_el = seccion.find("div", class_="title")
        titulo = self.limpiar_texto(titulo_el.get_text()) if titulo_el else ""
        if not titulo:
            return None

        precio_el = seccion.find(
            "div", class_="callout limit-height limit-height-large-1 limit-height-small-1"
        )
        precio: Optional[str] = None
        precio_original: Optional[str] = None
        if precio_el:
            texto_precio = precio_el.get_text(strip=True)
            precio = self.extraer_precio(texto_precio)
            original_el = precio_el.find("span", class_="callout-comparison")
            if original_el:
                precio_original = self.extraer_precio_original(original_el.get_text())
                if not precio_original:
                    precio_original = self.extraer_precio(original_el.get_text())
            if not precio:
                return None
        else:
            return None

        if precio_original and precio_original == precio:
            precio_original = None

        enlace = seccion.find("a", class_="attractor")
        link = enlace.get("href") if enlace else None
        if not link:
            return None
        link = urljoin(self.url, link)

        imagen = None
        img = seccion.find("img", class_="native-lazy-img") or seccion.find("img")
        if img:
            imagen = img.get("src") or img.get("data-src") or img.get("data-lazy-src")

        info: Optional[str] = None
        cupon: Optional[str] = None
        info_el = seccion.find("div", class_="snippet summary")
        if info_el:
            texto_info = self.limpiar_texto(info_el.get_text(" ", strip=True))
            cupon = self.extraer_cupon(texto_info)
            if texto_info and "no se requiere cupón" not in texto_info.lower():
                info = self.limpiar_info(texto_info)

        return Oferta.create(
            titulo=titulo,
            precio=precio or "No disponible",
            link=link,
            tag=self.tag,
            emoji=self.emoji,
            precio_original=precio_original,
            imagen=imagen,
            cupon=cupon,
            info_cupon=info,
        )
