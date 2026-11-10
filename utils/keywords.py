"""Normalización y coincidencia de palabras clave de alertas."""

import re

from config import Config


def normalizar_keyword(
    raw: str,
    min_length: int | None = None,
    max_length: int | None = None,
) -> str:
    """Limpia y valida una palabra clave. Lanza ValueError si no es válida."""
    min_length = Config.KEYWORD_MIN_LENGTH if min_length is None else min_length
    max_length = Config.KEYWORD_MAX_LENGTH if max_length is None else max_length

    keyword = " ".join((raw or "").split())
    if not keyword:
        raise ValueError("La palabra clave no puede estar vacía.")
    if any(ord(char) < 32 for char in keyword):
        raise ValueError("La palabra clave contiene caracteres no válidos.")
    if not any(char.isalnum() for char in keyword):
        raise ValueError("La palabra clave debe contener al menos una letra o número.")
    if len(keyword) < min_length:
        raise ValueError(
            f"La palabra clave debe tener al menos {min_length} caracteres."
        )
    if len(keyword) > max_length:
        raise ValueError(
            f"La palabra clave no puede superar {max_length} caracteres."
        )
    return keyword


def compilar_patron(keyword: str) -> re.Pattern[str]:
    """
    Compila un patrón que respeta límites de palabra incluso con símbolos.

    `\\b` falla con palabras como `c++`, `$100` o `#deal`; usar `(?<!\\w)` y
    `(?!\\w)` permite que esas palabras coincidan sin generar falsos positivos
    dentro de palabras mayores.
    """
    limpia = normalizar_keyword(keyword).lower()
    return re.compile(r"(?<!\w)" + re.escape(limpia) + r"(?!\w)")


def coincide(keyword: str, texto: str) -> bool:
    """Devuelve True si la palabra clave aparece como palabra completa."""
    try:
        patron = compilar_patron(keyword)
    except ValueError:
        return False
    return bool(patron.search((texto or "").lower()))
