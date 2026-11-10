"""Scraper de Slickdeals basado en su feed RSS público.

La web de Slickdeals responde 403 (Cloudflare) a peticiones automatizadas, pero
el feed de FeedBurner sigue disponible. Algunas respuestas llegan con XML
malformado o como página HTML de error, así que el parser intenta recuperarse.
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

        tipo = response.headers.get("content-type", "").lower()
        inicio = response.content[:500].lower()
        if "xml" not in tipo and b"<rss" not in inicio and b"<feed" not in inicio:
            raise ScraperError(
                f"Slickdeals devolvió contenido que no es RSS ({tipo or 'sin tipo'})"
            )

        ofertas = self.parsear_feed(response.content)
        if not ofertas:
            logger.warning("Slickdeals: el feed no devolvió ofertas utilizables")
        else:
            logger.info("Slickdeals: %s ofertas desde el feed RSS", len(ofertas))
        return ofertas

    def parsear_feed(self, contenido: bytes | str) -> list[Oferta]:
        raiz = None
        error_original = None
        try:
            raiz = ET.fromstring(contenido)
        except ET.ParseError as exc:
            error_original = exc
            logger.warning(
                "Slickdeals: XML inválido (%s); se intenta sanear y usar HTML", exc
            )
            try:
                raiz = ET.fromstring(self._sanitizar_xml(contenido))
            except ET.ParseError as exc_saneado:
                logger.warning("Slickdeals: el XML saneado tampoco es válido: %s", exc_saneado)
                raiz = None

        if raiz is not None:
            items = [
                elemento
                for elemento in raiz.iter()
                if elemento.tag.split("}")[-1] == "item"
            ]
            ofertas = self._ofertas_desde_elementos(items)
            if ofertas:
                return ofertas

        ofertas = self._parsear_con_bs(contenido)
        if ofertas:
            logger.info("Slickdeals: recuperadas %s ofertas con el parser HTML", len(ofertas))
            return ofertas

        raise ScraperError(
            f"Slickdeals: feed RSS inválido: {error_original or 'sin elementos item'}"
        )

    @staticmethod
    def _sanitizar_xml(contenido: bytes | str) -> str:
        texto = (
            contenido.decode("utf-8", errors="replace")
            if isinstance(contenido, bytes)
            else contenido
        )
        texto = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", texto)
        # Escapa ampersands sueltos sin tocar entidades válidas.
        return re.sub(
            r"&(?!(?:amp|lt|gt|quot|apos|#\d+|#x[0-9a-fA-F]+);)", "&amp;", texto
        )

    def _ofertas_desde_elementos(self, items) -> list[Oferta]:
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

    def _parsear_con_bs(self, contenido: bytes | str) -> list[Oferta]:
        sopa = BeautifulSoup(contenido, "html.parser")
        ofertas: list[Oferta] = []
        vistos: set[str] = set()
        for item in sopa.find_all("item"):
            try:
                titulo_el = item.find("title")
                link_el = item.find("link")
                desc_el = item.find("description")
                encoded = item.find("encoded") or item.find("content:encoded")
                link = link_el.get_text(strip=True) if link_el else ""
                if not link:
                    # html.parser trata <link> como etiqueta vacía: el texto
                    # queda como hermano siguiente.
                    match = re.search(
                        r"https?://[^\s<\"']+", item.decode_contents()
                    )
                    if match:
                        link = match.group(0)
                oferta = self._crear_oferta(
                    titulo=titulo_el.get_text() if titulo_el else "",
                    link=link,
                    descripcion=desc_el.get_text(" ", strip=True) if desc_el else "",
                    encoded=encoded.decode_contents() if encoded else "",
                )
                if oferta and oferta.link not in vistos:
                    vistos.add(oferta.link)
                    ofertas.append(oferta)
            except Exception as exc:  # noqa: BLE001
                logger.error("Slickdeals: error en parser HTML: %s", exc)
        return ofertas

    @staticmethod
    def _texto_hijo(item, nombre: str) -> str:
        for hijo in item:
            if hijo.tag.split("}")[-1] == nombre:
                return (hijo.text or "").strip()
        return ""

    def _extraer_item(self, item) -> Oferta | None:
        titulo = self._texto_hijo(item, "title")
        link = self._texto_hijo(item, "link")
        descripcion = self._texto_hijo(item, "description")
        encoded = self._texto_hijo(item, "encoded")
        return self._crear_oferta(titulo, link, descripcion, encoded)

    def _crear_oferta(
        self, titulo: str, link: str, descripcion: str, encoded: str
    ) -> Oferta | None:
        titulo = self.limpiar_texto(re.sub(r"<[^>]+>", " ", titulo or ""))
        descripcion = self.limpiar_texto(re.sub(r"<[^>]+>", " ", descripcion or ""))
        link = (link or "").strip()
        if not titulo or not link:
            return None

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
