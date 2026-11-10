"""Descarga de imágenes de ofertas para poder subirlas a Telegram."""

import ipaddress
import logging
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup

from utils.models import Oferta

logger = logging.getLogger(__name__)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
    ),
    "Accept": "image/avif,image/webp,image/png,image/jpeg,image/*;q=0.8,*/*;q=0.5",
}

EXTENSIONES = {
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/gif": ".gif",
}


@dataclass(frozen=True)
class ImagenDescargada:
    contenido: bytes
    nombre: str
    content_type: str


def _url_permitida(url: str) -> bool:
    try:
        partes = urlsplit(url)
    except ValueError:
        return False
    if partes.scheme not in ("http", "https") or not partes.hostname:
        return False
    host = partes.hostname.lower()
    if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
        return False
    try:
        direccion = ipaddress.ip_address(host)
        if direccion.is_private or direccion.is_loopback or direccion.is_reserved:
            return False
    except ValueError:
        # Es un nombre de dominio normal; se permite (las fuentes son conocidas).
        pass
    return True


async def descargar_imagen(
    url: Optional[str],
    max_bytes: int = 5_000_000,
    timeout: int = 20,
) -> Optional[ImagenDescargada]:
    """Descarga una imagen validando tipo y tamaño. Devuelve None si no sirve."""
    if not url or not _url_permitida(url):
        return None
    try:
        async with httpx.AsyncClient(
            headers=HEADERS, follow_redirects=True, timeout=timeout
        ) as client:
            async with client.stream("GET", url) as respuesta:
                if respuesta.status_code != 200:
                    return None
                content_type = (
                    respuesta.headers.get("content-type", "").split(";")[0].strip().lower()
                )
                if not content_type.startswith("image/"):
                    return None
                partes: list[bytes] = []
                total = 0
                async for trozo in respuesta.aiter_bytes():
                    total += len(trozo)
                    if total > max_bytes:
                        logger.warning("Imagen demasiado grande: %s", url)
                        return None
                    partes.append(trozo)
                contenido = b"".join(partes)
    except (httpx.HTTPError, OSError) as exc:
        logger.debug("No se pudo descargar la imagen %s: %s", url, exc)
        return None
    if not contenido:
        return None
    extension = EXTENSIONES.get(content_type, ".jpg")
    return ImagenDescargada(
        contenido=contenido, nombre=f"oferta{extension}", content_type=content_type
    )


async def extraer_og_image(url: Optional[str], timeout: int = 20) -> Optional[str]:
    """Busca og:image/twitter:image en la página del producto."""
    if not url or not _url_permitida(url):
        return None
    try:
        async with httpx.AsyncClient(
            headers={**HEADERS, "Accept": "text/html,application/xhtml+xml"},
            follow_redirects=True,
            timeout=timeout,
        ) as client:
            respuesta = await client.get(url)
        if respuesta.status_code != 200:
            return None
        tipo = respuesta.headers.get("content-type", "").lower()
        if "html" not in tipo and tipo:
            return None
        sopa = BeautifulSoup(respuesta.text, "html.parser")
        for meta in sopa.find_all("meta"):
            clave = (meta.get("property") or meta.get("name") or "").lower()
            if clave in (
                "og:image",
                "og:image:secure_url",
                "twitter:image",
                "twitter:image:src",
            ):
                contenido = meta.get("content")
                if contenido:
                    return urljoin(str(respuesta.url), contenido)
        enlace = sopa.find("link", rel=lambda valor: valor and "image_src" in valor)
        if enlace and enlace.get("href"):
            return urljoin(str(respuesta.url), enlace["href"])
    except (httpx.HTTPError, OSError) as exc:
        logger.debug("No se pudo leer og:image de %s: %s", url, exc)
    return None


async def resolver_imagen(
    oferta: Oferta,
    max_bytes: int = 5_000_000,
    timeout: int = 20,
) -> Optional[ImagenDescargada]:
    """Intenta la URL de la oferta y, si falla, el og:image de la página."""
    imagen = await descargar_imagen(oferta.imagen, max_bytes=max_bytes, timeout=timeout)
    if imagen:
        return imagen
    og_image = await extraer_og_image(oferta.link, timeout=timeout)
    if og_image:
        imagen = await descargar_imagen(og_image, max_bytes=max_bytes, timeout=timeout)
        if imagen:
            oferta.imagen = og_image
            return imagen
    return None
