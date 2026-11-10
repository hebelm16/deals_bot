"""Descarga y resolución de imágenes de ofertas para Telegram."""

import html
import ipaddress
import json
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


def _normalizar_url(url: Optional[str]) -> Optional[str]:
    if not url:
        return None
    limpia = html.unescape(str(url).strip())
    if limpia.startswith("//"):
        limpia = "https:" + limpia
    if not limpia.startswith(("http://", "https://")):
        return None
    return limpia


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
        pass
    return True


def _parece_imagen(contenido: bytes, content_type: str) -> bool:
    if content_type.startswith("image/"):
        return True
    if contenido.startswith(b"\xff\xd8\xff"):  # JPEG
        return True
    if contenido.startswith(b"\x89PNG\r\n\x1a\n"):  # PNG
        return True
    if contenido.startswith((b"GIF87a", b"GIF89a")):  # GIF
        return True
    if contenido[:4] == b"RIFF" and contenido[8:12] == b"WEBP":  # WebP
        return True
    return False


async def descargar_imagen(
    url: Optional[str],
    max_bytes: int = 5_000_000,
    timeout: int = 20,
    referer: Optional[str] = None,
) -> Optional[ImagenDescargada]:
    """Descarga una imagen validando tipo real, tamaño y esquema."""
    url = _normalizar_url(url)
    if not url or not _url_permitida(url):
        return None
    headers = dict(HEADERS)
    referer = _normalizar_url(referer)
    if referer:
        headers["Referer"] = referer
    try:
        async with httpx.AsyncClient(
            headers=headers, follow_redirects=True, timeout=timeout
        ) as client:
            async with client.stream("GET", url) as respuesta:
                if respuesta.status_code != 200:
                    return None
                content_type = (
                    respuesta.headers.get("content-type", "").split(";")[0].strip().lower()
                )
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
    if not contenido or not _parece_imagen(contenido, content_type):
        return None
    if not content_type.startswith("image/"):
        content_type = "image/jpeg"
    extension = EXTENSIONES.get(content_type, ".jpg")
    return ImagenDescargada(
        contenido=contenido, nombre=f"oferta{extension}", content_type=content_type
    )


def _candidatos_json_ld(sopa: BeautifulSoup) -> list[str]:
    candidatos: list[str] = []

    def recorrer(valor):
        if isinstance(valor, str):
            if valor.startswith(("http://", "https://", "//")):
                candidatos.append(valor)
        elif isinstance(valor, dict):
            for clave, subvalor in valor.items():
                if clave.lower() in ("image", "thumbnailurl", "contenturl"):
                    recorrer(subvalor)
        elif isinstance(valor, list):
            for elemento in valor:
                recorrer(elemento)

    for script in sopa.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            datos = json.loads(script.string or "")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        recorrer(datos)
    return candidatos


async def extraer_candidatos_imagen(
    url: Optional[str], timeout: int = 20
) -> list[str]:
    """Devuelve candidatos de imagen de la página: og, twitter, JSON-LD e <img>."""
    url = _normalizar_url(url)
    if not url or not _url_permitida(url):
        return []
    try:
        async with httpx.AsyncClient(
            headers={**HEADERS, "Accept": "text/html,application/xhtml+xml"},
            follow_redirects=True,
            timeout=timeout,
        ) as client:
            respuesta = await client.get(url)
        if respuesta.status_code != 200:
            return []
        tipo = respuesta.headers.get("content-type", "").lower()
        if tipo and "html" not in tipo:
            return []
        sopa = BeautifulSoup(respuesta.text, "html.parser")
        base = str(respuesta.url)
        candidatos: list[str] = []

        for meta in sopa.find_all("meta"):
            clave = (meta.get("property") or meta.get("name") or "").lower()
            if clave in (
                "og:image",
                "og:image:secure_url",
                "og:image:url",
                "twitter:image",
                "twitter:image:src",
            ):
                contenido = meta.get("content")
                if contenido:
                    candidatos.append(contenido)
        for enlace in sopa.find_all("link"):
            rel = enlace.get("rel") or []
            rel_texto = " ".join(rel).lower() if isinstance(rel, list) else str(rel).lower()
            if "image_src" in rel_texto or "preload" in rel_texto:
                if enlace.get("href"):
                    candidatos.append(enlace["href"])
        candidatos.extend(_candidatos_json_ld(sopa))

        for img in sopa.find_all("img"):
            for atributo in ("src", "data-src", "data-lazy-src"):
                if img.get(atributo):
                    candidatos.append(img[atributo])
                    break

        resultado: list[str] = []
        for candidato in candidatos:
            absuelto = urljoin(base, candidato)
            if absuelto not in resultado and _url_permitida(absuelto):
                resultado.append(absuelto)
        return resultado[:10]
    except (httpx.HTTPError, OSError) as exc:
        logger.debug("No se pudieron extraer imágenes de %s: %s", url, exc)
    return []


async def extraer_og_image(url: Optional[str], timeout: int = 20) -> Optional[str]:
    """Compatibilidad: primer candidato de imagen de la página."""
    candidatos = await extraer_candidatos_imagen(url, timeout=timeout)
    return candidatos[0] if candidatos else None


async def resolver_imagen(
    oferta: Oferta,
    max_bytes: int = 5_000_000,
    timeout: int = 20,
) -> Optional[ImagenDescargada]:
    """Prueba la URL original y luego candidatos de la página del producto."""
    referer = oferta.link
    imagen = await descargar_imagen(
        oferta.imagen, max_bytes=max_bytes, timeout=timeout, referer=referer
    )
    if imagen:
        return imagen

    candidatos = []
    if oferta.imagen:
        candidatos.append(oferta.imagen)
    candidatos.extend(await extraer_candidatos_imagen(oferta.link, timeout=timeout))
    vistos: set[str] = set()
    for candidato in candidatos:
        normalizado = _normalizar_url(candidato)
        if not normalizado or normalizado in vistos:
            continue
        vistos.add(normalizado)
        imagen = await descargar_imagen(
            normalizado,
            max_bytes=max_bytes,
            timeout=timeout,
            referer=referer,
        )
        if imagen:
            oferta.imagen = normalizado
            return imagen
    return None
