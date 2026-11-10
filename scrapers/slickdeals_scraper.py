"""Scraper de Slickdeals basado en su feed RSS público.

La web de Slickdeals responde 403 (Cloudflare) a peticiones automatizadas, pero
el feed de FeedBurner sigue disponible y entrega las mismas ofertas de portada.
"""

import logging
import re
import xml.etree.ElementTree as ET

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
    "Accept": "application/rss+xml, application/xml, text/xml;q=0.9, */*;q=0.8",
}


class SlickdealsScraper(BaseScraper):
    emoji = "🔥"

    def __init__(self, name: str, url: str, tag: str):
        super().__init__(name, url, tag)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_fixed(3),
        reraise=True,
    )
    async def obtener_ofertas(self) -> list[Oferta]:
        logger.info("Slickdeals: descargando feed %s", self.url)
        try:
            async with httpx.AsyncClient(
                headers=HEADERS, follow_redirects=True, timeout=30
            ) as client:
                response = await client.get(self.url)
            response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ScraperError(f"Slickdeals no respondió correctamente: {exc}") from exc

        ofertas = self.parsear_feed(response.content)
        if not ofertas:
            logger.warning("Slickdeals: el feed no devolvió ofertas utilizables")
        else:
            logger.info("Slickdeals: %s ofertas desde el feed RSS", len(ofertas))
        return ofertas

    def parsear_feed(self, contenido: bytes | str) -> list[Oferta]:
        try:
            raiz = ET.fromstring(contenido)
        except ET.ParseError as exc:
            raise ScraperError(f"Slickdeals: feed RSS inválido: {exc}") from exc

        items = [
            elemento
            for elemento in raiz.iter()
            if elemento.tag.split("}")[-1] == "item"
        ]
        if not items:
            raise ScraperError("Slickdeals: el contenido recibido no es un feed RSS")

        ofertas: list[Oferta] = []
        vistos: set[str] = set()
        for item in items:
            try:
                oferta = self._extraer_item(item)
                if oferta and oferta.link not in vistos:
                    vistos.add(oferta.link)
                    ofertas.append(oferta)
            except Exception as exc:  # noqa: BLE001 - una entrada rota no invalida el feed
                logger.error("Slickdeals: error al procesar una entrada: %s", exc)
        return ofertas

    @staticmethod
    def _texto_hijo(item, nombre: str) -> str:
        for hijo in item:
            if hijo.tag.split("}")[-1] == nombre:
                return (hijo.text or "").strip()
        return ""

    def _extraer_item(self, item) -> Oferta | None:
        titulo = self.limpiar_texto(re.sub(r"<[^>]+>", " ", self._texto_hijo(item, "title")))
        link = self._texto_hijo(item, "link")
        if not titulo or not link:
            return None

        descripcion = self.limpiar_texto(
            re.sub(r"<[^>]+>", " ", self._texto_hijo(item, "description"))
        )
        encoded = self._texto_hijo(item, "encoded")

        precio = self.extraer_precio(titulo) or self.extraer_precio(descripcion)
        original = self.extraer_precio_original(descripcion) or self.extraer_precio_original(titulo)
        if original and precio and original == precio:
            original = None

        imagen = None
        if encoded:
            soup_img = BeautifulSoup(encoded, "html.parser")
            img = soup_img.find("img")
            if img:
                imagen = img.get("src") or img.get("data-src")

        cupon = self.extraer_cupon(descripcion)
        info = self.limpiar_info(descripcion)

        return Oferta.create(
            titulo=titulo,
            precio=precio or "No disponible",
            link=link,
            tag=self.tag,
            emoji=self.emoji,
            precio_original=original,
            imagen=imagen,
            cupon=cupon,
            info_cupon=info,
        )
