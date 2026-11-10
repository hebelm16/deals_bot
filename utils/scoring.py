"""Puntuación y selección de ofertas por descuento y calidad."""

import math
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Dict, List, Optional, Sequence

from utils.models import Oferta
from utils.text import limpiar_titulo

PRECIO_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)")

PALABRAS_VACIAS = {
    "the",
    "and",
    "with",
    "for",
    "from",
    "your",
    "you",
    "this",
    "that",
    "new",
    "sale",
    "deal",
    "deals",
    "free",
    "shipping",
    "pack",
    "set",
    "pcs",
    "piece",
    "pieces",
    "inch",
    "inches",
    "color",
    "colors",
    "size",
    "sizes",
    "refurb",
    "refurbished",
    "renewed",
}

# Peso pequeño por fuente: sirve para desempatar, no para tapar el descuento.
PESOS_FUENTE = {
    "slickdeals": 1.2,
    "dealnews": 1.0,
    "dealsofamerica": 0.9,
}


def normalizar_titulo(titulo: object) -> str:
    """Minúsculas, sin acentos, precios ni signos, para comparar títulos."""
    texto = unicodedata.normalize("NFKD", limpiar_titulo(titulo))
    texto = texto.encode("ascii", "ignore").decode("ascii").lower()
    return " ".join(re.findall(r"[a-z0-9]+", texto))


def _tokens_titulo(titulo: object) -> set[str]:
    return {
        token
        for token in normalizar_titulo(titulo).split()
        if len(token) > 2 and token not in PALABRAS_VACIAS
    }


def _numeros_titulo(titulo: object) -> set[str]:
    return {
        token
        for token in re.findall(r"\d+[a-z0-9]*", normalizar_titulo(titulo))
        if token
    }


def similitud_titulos(a: object, b: object) -> float:
    """Similitud 0..1 entre dos títulos, penalizando modelos distintos."""
    tokens_a = _tokens_titulo(a)
    tokens_b = _tokens_titulo(b)
    if not tokens_a or not tokens_b:
        return 0.0

    numeros_a = _numeros_titulo(a)
    numeros_b = _numeros_titulo(b)
    if numeros_a and numeros_b and not (
        numeros_a <= numeros_b or numeros_b <= numeros_a
    ):
        # Un portátil de 15" no es el mismo producto que uno de 16".
        return 0.0

    jaccard = len(tokens_a & tokens_b) / len(tokens_a | tokens_b)
    ratio = SequenceMatcher(
        None, normalizar_titulo(a), normalizar_titulo(b)
    ).ratio()
    return max(jaccard, ratio)


def son_duplicados(a: object, b: object, umbral: float = 0.82) -> bool:
    return similitud_titulos(a, b) >= umbral


def parsear_precio(valor: object) -> Optional[float]:
    """Convierte '$1,299.99' o 1299.99 en número. Devuelve None si no hay precio."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        return float(valor)
    match = PRECIO_RE.search(str(valor))
    if not match:
        return None
    try:
        return float(match.group(1).replace(",", ""))
    except ValueError:
        return None


def calcular_descuento(
    precio: object, precio_original: object
) -> Optional[float]:
    """Descuento porcentual real (0-95). None si los datos no son válidos."""
    actual = parsear_precio(precio)
    original = parsear_precio(precio_original)
    if actual is None or original is None or actual <= 0 or original <= 0:
        return None
    if actual >= original:
        return None
    descuento = (original - actual) / original * 100
    if descuento < 1:
        return None
    return round(min(descuento, 95.0), 1)


def puntuar_oferta(
    oferta: Oferta,
    posicion: int = 0,
    peso_fuente: float = 1.0,
) -> float:
    """Puntúa una oferta: descuento real + calidad de datos + frescura."""
    descuento = calcular_descuento(oferta.precio, oferta.precio_original)
    puntuacion = min(descuento, 90.0) if descuento else 0.0
    if parsear_precio(oferta.precio) is not None:
        puntuacion += 1.0
    if (oferta.imagen or "").startswith(("http://", "https://")):
        puntuacion += 2.0
    if oferta.info_cupon:
        puntuacion += 1.0
    if oferta.cupon:
        puntuacion += 1.0
    puntuacion += peso_fuente
    # Dentro de cada fuente, las primeras posiciones suelen ser más recientes.
    puntuacion += max(0.0, 3.0 - posicion * 0.05)
    return round(puntuacion, 2)


def seleccionar_mejores(
    ofertas_por_fuente: Dict[str, Sequence[Oferta]],
    maximo: int,
    pesos: Optional[Dict[str, float]] = None,
    umbral_titulos: float = 0.82,
) -> List[Oferta]:
    """
    Elige las mejores ofertas por puntuación, con cuota inicial por fuente
    para no llenar el canal con una sola web.
    """
    if maximo <= 0:
        return []
    fuentes = [
        (nombre, list(ofertas))
        for nombre, ofertas in ofertas_por_fuente.items()
        if ofertas
    ]
    if not fuentes:
        return []

    pesos = {**PESOS_FUENTE, **(pesos or {})}
    candidatos = []
    for nombre, ofertas in fuentes:
        for posicion, oferta in enumerate(ofertas):
            peso = pesos.get(nombre, 1.0)
            candidatos.append(
                (puntuar_oferta(oferta, posicion, peso), -posicion, nombre, oferta)
            )
    candidatos.sort(key=lambda item: (-item[0], item[1]))

    cuota = max(1, math.ceil(maximo / len(fuentes)))
    seleccionadas: List[Oferta] = []
    vistos: set[tuple[str, str]] = set()
    conteo = {nombre: 0 for nombre, _ in fuentes}

    def agregar(nombre: str, oferta: Oferta) -> bool:
        clave = ((oferta.titulo or "").strip().lower(), (oferta.link or "").strip())
        if clave in vistos:
            return False
        if any(
            son_duplicados(oferta.titulo, existente.titulo, umbral_titulos)
            for existente in seleccionadas
        ):
            return False
        vistos.add(clave)
        seleccionadas.append(oferta)
        conteo[nombre] += 1
        return True

    for _, _, nombre, oferta in candidatos:
        if len(seleccionadas) >= maximo:
            break
        if conteo[nombre] < cuota:
            agregar(nombre, oferta)

    if len(seleccionadas) < maximo:
        for _, _, nombre, oferta in candidatos:
            if len(seleccionadas) >= maximo:
                break
            agregar(nombre, oferta)

    return seleccionadas
