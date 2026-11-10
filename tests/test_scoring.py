from utils.formatting import render_offer_text
from utils.models import Oferta
from utils.scoring import (
    calcular_descuento,
    parsear_precio,
    puntuar_oferta,
    seleccionar_mejores,
    similitud_titulos,
    son_duplicados,
)


def crear(precio, original=None, titulo="Producto", **kwargs):
    return Oferta.create(
        titulo=titulo,
        precio=precio,
        precio_original=original,
        link=f"https://example.com/{titulo.replace(' ', '-')}",
        tag="#Test",
        **kwargs,
    )


def test_parsear_precio():
    assert parsear_precio("$1,299.99") == 1299.99
    assert parsear_precio("from $7.70") == 7.70
    assert parsear_precio("$20 + Free S&H") == 20.0
    assert parsear_precio("Up to 80% off") is None
    assert parsear_precio(None) is None


def test_calcular_descuento():
    assert calcular_descuento("$50", "$100") == 50.0
    assert calcular_descuento("$7.59", "$38.99") == 80.5
    assert calcular_descuento("$100", "$100") is None
    assert calcular_descuento("$120", "$100") is None
    assert calcular_descuento("No disponible", "$100") is None


def test_puntua_mejor_el_mayor_descuento():
    fuerte = crear("$50", "$100")
    flojo = crear("$95", "$100")
    assert puntuar_oferta(fuerte) > puntuar_oferta(flojo)


def test_selecciona_mejores_antes_que_relleno():
    fuerte = crear("$50", "$100", titulo="Fuerte")
    medio = crear("$80", "$100", titulo="Medio")
    sin_descuento = crear("$100", None, titulo="Sin descuento")

    seleccion = seleccionar_mejores(
        {"a": [sin_descuento], "b": [fuerte], "c": [medio]}, maximo=2
    )

    assert fuerte in seleccion
    assert medio in seleccion
    assert sin_descuento not in seleccion


def test_muestra_descuento_en_el_mensaje():
    oferta = crear("$50", "$100")
    texto = render_offer_text(oferta)
    assert "(-50%)" in texto


def test_no_duplica_ofertas():
    oferta = crear("$50", "$100")
    seleccion = seleccionar_mejores({"a": [oferta], "b": [oferta]}, maximo=5)
    assert len(seleccion) == 1


def test_detecta_duplicados_entre_fuentes():
    assert son_duplicados(
        "Apple AirPods Pro 3 Wireless Earbuds",
        "Refurb: Apple AirPods Pro 3 Wireless Earbuds",
    )
    assert son_duplicados(
        "Apple AirPods Pro 3 Wireless Earbuds $50",
        "Refurb Apple AirPods Pro 3 Wireless Earbuds $55",
    )
    assert not son_duplicados("Apple AirPods Pro 3", "Apple AirPods Pro 2")
    assert not son_duplicados(
        "Samsung 75-inch 4K Smart TV", "Samsung 65-inch 4K Smart TV"
    )
    assert similitud_titulos("Sony WH-1000XM5", "Sony WH-1000XM5") > 0.9


def test_seleccion_evita_duplicados_similares():
    primera = crear("$50", "$100", titulo="Apple AirPods Pro 3 Wireless Earbuds")
    duplicada = crear("$55", "$100", titulo="Refurb Apple AirPods Pro 3 Wireless Earbuds")
    distinta = crear("$30", "$60", titulo="Samsung 75-inch 4K Smart TV")

    seleccion = seleccionar_mejores(
        {"slickdeals": [primera, duplicada], "dealnews": [distinta]}, maximo=3
    )

    assert primera in seleccion
    assert duplicada not in seleccion
    assert distinta in seleccion
