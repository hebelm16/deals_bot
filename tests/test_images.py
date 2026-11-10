import httpx
import respx

from utils.images import descargar_imagen, extraer_og_image, resolver_imagen
from utils.models import Oferta


@respx.mock
async def test_descarga_imagen_valida():
    respx.get("https://example.com/img.jpg").mock(
        return_value=httpx.Response(
            200,
            content=b"imagen-jpeg",
            headers={"content-type": "image/jpeg"},
        )
    )
    imagen = await descargar_imagen("https://example.com/img.jpg")
    assert imagen is not None
    assert imagen.contenido == b"imagen-jpeg"
    assert imagen.nombre == "oferta.jpg"


@respx.mock
async def test_rechaza_contenido_que_no_es_imagen():
    respx.get("https://example.com/pagina").mock(
        return_value=httpx.Response(
            200,
            content=b"<html></html>",
            headers={"content-type": "text/html"},
        )
    )
    assert await descargar_imagen("https://example.com/pagina") is None


async def test_rechaza_ip_privada():
    assert await descargar_imagen("http://127.0.0.1/imagen.jpg") is None
    assert await descargar_imagen("http://localhost/imagen.jpg") is None


@respx.mock
async def test_extrae_og_image():
    respx.get("https://example.com/producto").mock(
        return_value=httpx.Response(
            200,
            text='<html><head><meta property="og:image" content="/img.jpg"></head></html>',
            headers={"content-type": "text/html"},
        )
    )
    assert (
        await extraer_og_image("https://example.com/producto")
        == "https://example.com/img.jpg"
    )


@respx.mock
async def test_resolver_usa_og_image_si_la_original_falla():
    respx.get("https://example.com/rota.jpg").mock(
        return_value=httpx.Response(404)
    )
    respx.get("https://example.com/producto").mock(
        return_value=httpx.Response(
            200,
            text='<html><head><meta name="twitter:image" content="/buena.jpg"></head></html>',
            headers={"content-type": "text/html"},
        )
    )
    respx.get("https://example.com/buena.jpg").mock(
        return_value=httpx.Response(
            200,
            content=b"otra-imagen",
            headers={"content-type": "image/png"},
        )
    )
    oferta = Oferta.create(
        titulo="Producto",
        precio="$10",
        link="https://example.com/producto",
        tag="#Test",
        imagen="https://example.com/rota.jpg",
    )
    imagen = await resolver_imagen(oferta)
    assert imagen is not None
    assert imagen.contenido == b"otra-imagen"
    assert oferta.imagen == "https://example.com/buena.jpg"
