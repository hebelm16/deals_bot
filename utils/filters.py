"""Filtro de ofertas que no son productos físicos (viajes, finanzas, puntos...)."""

import re
from typing import Iterable, Optional

from utils.models import Oferta
from utils.text import limpiar_titulo

# Cada categoría se puede excluir o permitir con CATEGORIAS_EXCLUIDAS.
CATEGORIAS: dict[str, re.Pattern[str]] = {
    "viajes": re.compile(
        r"\b(?:airlines?|airfares?|flights? (?:to|from|deals?|tickets?)|"
        r"(?:book|booking) (?:a )?flights?|round[- ]?trip|one[- ]?way fares?|"
        r"cruises? (?:to|from|fares?|deals?)|vacation packages?|"
        r"hotel (?:stays?|rooms?|bookings?|deals?)|hotels? (?:in|from)|"
        r"all[- ]inclusive|car rentals?|resort (?:stays?|packages?))\b",
        re.IGNORECASE,
    ),
    "puntos": re.compile(
        r"\b(?:reward points|rewards points|rapid rewards|loyalty points|"
        r"bonus points|bonus miles|airline miles|frequent flyer|"
        r"redeem(?:ing)? points|points? (?:redemption|transfer))\b",
        re.IGNORECASE,
    ),
    "finanzas": re.compile(
        r"\b(?:credit cards?(?! (?:holders?|readers?|wallets?|cases?|sleeves?))|"
        r"checking accounts?|savings accounts?|bank bonus|"
        r"bank account|sign[- ]?up bonus|open an account|brokerage|"
        r"free stock|referral bonus|personal loans?|apy)\b",
        re.IGNORECASE,
    ),
    "gift_cards": re.compile(
        r"\b(?:e-?gift ?cards?|gift ?cards?|gift certificates?)\b",
        re.IGNORECASE,
    ),
}

CATEGORIAS_POR_DEFECTO = ("viajes", "puntos", "finanzas")


def parsear_categorias(valor: Optional[str]) -> tuple[str, ...]:
    """Convierte 'viajes, finanzas' en categorías válidas (ignora desconocidas)."""
    if valor is None:
        return CATEGORIAS_POR_DEFECTO
    elegidas = [
        parte.strip().lower().replace(" ", "_").replace("-", "_")
        for parte in str(valor).split(",")
    ]
    return tuple(parte for parte in elegidas if parte in CATEGORIAS)


def categoria_no_producto(
    oferta: Oferta, categorias: Iterable[str] = CATEGORIAS_POR_DEFECTO
) -> Optional[str]:
    """Devuelve la categoría excluida a la que pertenece la oferta, si hay."""
    titulo = limpiar_titulo(oferta.titulo) or oferta.titulo or ""
    for nombre in categorias:
        patron = CATEGORIAS.get(nombre)
        if patron and patron.search(titulo):
            return nombre
    return None
