"""Utilidades compartidas por los scrapers."""

import re
from abc import ABC, abstractmethod
from typing import List, Optional

from utils.models import Oferta

PRECIO_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)")
PRECIO_ORIGINAL_PATTERNS = (
    re.compile(
        r"(?:was|reg(?:ular)?\.?|list price|originally|retail(?:s)? for|antes)\s*"
        r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)",
        re.IGNORECASE,
    ),
    re.compile(
        r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)\s*"
        r"(?:was|reg\.?|regular price)",
        re.IGNORECASE,
    ),
)
CUPON_RE = re.compile(
    r"(?:coupon|promo)\s*code[:\s]*[\"']?([A-Z0-9]{4,20})", re.IGNORECASE
)
CUPON_RE2 = re.compile(
    r"(?:w/|with)\s*(?:coupon\s*)?code[:\s]*[\"']?([A-Z0-9]{4,20})", re.IGNORECASE
)


class ScraperError(Exception):
    """Fallo controlado de un scraper (red, bloqueo o HTML inesperado)."""


class BaseScraper(ABC):
    emoji = "✨"

    def __init__(self, name: str, url: str, tag: str):
        self.name = name
        self.url = url
        self.tag = tag

    @staticmethod
    def limpiar_texto(texto: str) -> str:
        return " ".join(str(texto or "").strip().split())

    @staticmethod
    def extraer_precio(texto: str) -> Optional[str]:
        match = PRECIO_RE.search(str(texto or ""))
        return f"${match.group(1)}" if match else None

    @staticmethod
    def extraer_precio_original(texto: str) -> Optional[str]:
        for patron in PRECIO_ORIGINAL_PATTERNS:
            match = patron.search(str(texto or ""))
            if match:
                return f"${match.group(1)}"
        return None

    @staticmethod
    def extraer_cupon(texto: str) -> Optional[str]:
        for patron in (CUPON_RE, CUPON_RE2):
            match = patron.search(str(texto or ""))
            if match:
                codigo = match.group(1).upper()
                if codigo not in {"CODE", "COUPON", "PROMO", "PROMOCODE"}:
                    return codigo
        return None

    @staticmethod
    def limpiar_info(texto: str, limite: int = 300) -> Optional[str]:
        limpio = re.sub(r"<[^>]+>", " ", str(texto or ""))
        limpio = limpio.replace("*", " ")
        limpio = " ".join(limpio.split())
        if not limpio:
            return None
        return limpio[:limite].rstrip()

    @abstractmethod
    async def obtener_ofertas(self) -> List[Oferta]:
        """Devuelve las ofertas disponibles en la fuente."""
