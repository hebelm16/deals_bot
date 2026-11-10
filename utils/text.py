"""Limpieza de títulos e información extra para publicaciones legibles."""

import html
import re
from typing import Optional

_PRECIO_EN_TITULO = re.compile(r"\s+\$\s?\d[\d,]*(?:\.\d{1,2})?")
_PREFIJO_TIENDA = re.compile(
    r"^(?:select\s+)?[A-Z][\w&'. ]{2,30}\s+(?:stores?|warehouse)\s*:\s*", re.IGNORECASE
)
_SUFIJOS = (
    re.compile(r"\s*\+?\s*free\s+s(?:&|h|hipping).*$", re.IGNORECASE),
    re.compile(r"\s*w/\s*(?:email|text|sign).*$", re.IGNORECASE),
    re.compile(r"\s*\(pricing/availability[^)]*\).*$", re.IGNORECASE),
    re.compile(r"\s*\(select flights?\).*$", re.IGNORECASE),
    re.compile(r"\s*\(various[^)]*\)\s*$", re.IGNORECASE),
)

_CLAVES_INFO = (
    "coupon",
    "code",
    "promo",
    "free shipping",
    "free s&h",
    "shipping",
    "pickup",
    "in-store",
    "in store",
    "save",
    "off",
    "discount",
    "clip",
)


def limpiar_titulo(titulo: object) -> str:
    """Quita precio/shipping del final y prefijos de tienda del título."""
    original = " ".join(str(titulo or "").split())
    if not original:
        return ""
    texto = html.unescape(original)
    texto = _PREFIJO_TIENDA.sub("", texto)

    precio = _PRECIO_EN_TITULO.search(texto)
    if precio and precio.start() >= 8:
        texto = texto[: precio.start()]

    for patron in _SUFIJOS:
        texto = patron.sub("", texto)

    texto = " ".join(texto.split()).strip(" -–|:;,")
    if not texto:
        return original
    if len(texto) > 120:
        texto = texto[:119].rsplit(" ", 1)[0].rstrip() + "…"
    return texto


def resumen_info(info: object) -> Optional[str]:
    """Convierte la información extra en una etiqueta corta y útil."""
    if not info:
        return None
    texto = html.unescape(" ".join(str(info).split())).lower()
    partes: list[str] = []
    if any(
        clave in texto
        for clave in ("free shipping", "free s&h", "free s/h", "shipping is free")
    ):
        partes.append("Envío gratis")
    if any(
        clave in texto
        for clave in ("pickup", "in-store", "in store", "store pickup")
    ):
        partes.append("Pickup en tienda")
    if any(clave in texto for clave in ("coupon", "promo code", "clip")):
        partes.append("Cupón en la página")
    return " · ".join(dict.fromkeys(partes)) or None


def limpiar_info(info: object) -> Optional[str]:
    """Recorta la información extra: sin URLs, sin créditos y solo si aporta."""
    if not info:
        return None
    texto = html.unescape(" ".join(str(info).split()))
    texto = re.sub(r"https?://\S+", " ", texto)
    texto = re.sub(r"\bwww\.\S+", " ", texto)
    texto = re.sub(r"\[[^\]]*(?:\.com|\.net|\.org)[^\]]*\]", " ", texto)
    texto = re.sub(r"^\s*(?:click here|ver aqu[ií])[^.]*\.\s*", "", texto, flags=re.IGNORECASE)

    for marcador in ("thanks to community", "walmart also has", "note:"):
        posicion = texto.lower().find(marcador)
        if posicion > 20:
            texto = texto[:posicion]

    texto = " ".join(texto.split()).strip(" -–|:;,")
    if len(texto) < 20:
        return None

    bajo = texto.lower()
    if not any(clave in bajo for clave in _CLAVES_INFO):
        return None

    if len(texto) > 160:
        corte = texto[:160]
        if ". " in corte:
            corte = corte.rsplit(". ", 1)[0] + "."
        else:
            corte = corte.rsplit(" ", 1)[0].rstrip() + "…"
        texto = corte
    return texto or None
