from utils.formatting import CAPTION_LIMIT, render_offer_text, texto_plano
from utils.models import Oferta


def crear_oferta(**kwargs) -> Oferta:
    datos = dict(
        titulo="Producto de prueba",
        precio="$99.99",
        link="https://example.com/producto",
        tag="#Test",
        imagen="https://example.com/imagen.jpg",
    )
    datos.update(kwargs)
    return Oferta.create(**datos)


def test_escapa_todos_los_campos():
    oferta = crear_oferta(
        titulo='AT&T <b>SSD</b> & "Teclado"',
        precio="$99 & <100>",
        precio_original="$150 > $99",
        info_cupon="A & B",
        cupon="A&B<C>",
        link="https://example.com/x?a=1&b=2",
    )
    texto = render_offer_text(oferta)

    assert "AT&amp;T &lt;b&gt;SSD&lt;/b&gt; &amp;" in texto
    assert "&lt;script&gt;" not in texto
    assert "A &amp; B" in texto
    assert "A&amp;B&lt;C&gt;" in texto
    assert 'href="https://example.com/x?a=1&amp;b=2"' in texto
    # Las etiquetas propias del mensaje sí se conservan.
    assert "<b>" in texto


def test_enlace_invalido_no_se_incluye():
    oferta = crear_oferta(link="javascript:alert(1)")
    texto = render_offer_text(oferta)
    assert "javascript" not in texto
    assert "Ir a la Oferta" not in texto


def test_titulo_largo_respeta_limite_de_caption():
    oferta = crear_oferta(titulo="Título " * 2000)
    texto = render_offer_text(oferta, limit=CAPTION_LIMIT)
    assert len(texto) <= CAPTION_LIMIT
    assert "Título" in texto


def test_gancho_se_escapa():
    oferta = crear_oferta(gancho_ia="Oferta <b>increíble</b> & barata")
    texto = render_offer_text(oferta)
    assert "&lt;b&gt;increíble&lt;/b&gt;" in texto
    assert "&amp; barata" in texto


def test_texto_plano_quita_etiquetas():
    assert texto_plano("<b>Hola</b> &amp; adiós") == "Hola & adiós"


def test_oferta_sin_imagen_ni_precio_original():
    oferta = crear_oferta(imagen=None, precio_original=None)
    texto = render_offer_text(oferta)
    assert "Antes:" not in texto
    assert "Precio:" in texto
