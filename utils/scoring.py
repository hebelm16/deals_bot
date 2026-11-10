"""Puntuación y selección de ofertas por descuento y calidad."""

import math
import re
from typing import Dict, List, Optional, Sequence

from utils.models import Oferta

PRECIO_RE = re.compile(r"\$\s?(\d{1,3}(?:,\d{3})*(?:\.\d{1,2})?)")

# Peso pequeño por fuente: sirve para desempatar, no para tapar el descuento.
PESOS_FUENTE = {
    "slickdeals": 1.2,
    "dealnews": 1.0,
    "dealsofamerica": 0.9,
}


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
