import pytest

from utils.keywords import coincide, compilar_patron, normalizar_keyword


def test_normaliza_espacios():
    assert normalizar_keyword("  laptop   gamer  ") == "laptop gamer"


@pytest.mark.parametrize("keyword", ["", "   ", "++", "\n\t", "a"])
def test_rechaza_keywords_invalidas(keyword):
    with pytest.raises(ValueError):
        normalizar_keyword(keyword)


def test_rechaza_keyword_demasiado_larga():
    with pytest.raises(ValueError):
        normalizar_keyword("x" * 65)


@pytest.mark.parametrize(
    ("keyword", "texto"),
    [
        ("ssd", "SSD 1TB en oferta"),
        ("ssd", "ssd 1TB"),
        ("c++", "oferta c++ barata"),
        ("#deal", "gran #deal hoy"),
        ("$100", "por solo $100"),
        ("laptop gamer", "una laptop gamer buena"),
        ("audífonos", "AUDÍFONOS Sony"),
    ],
)
def test_coincide_palabras_con_simbolos(keyword, texto):
    assert coincide(keyword, texto)


@pytest.mark.parametrize(
    ("keyword", "texto"),
    [
        ("ssd", "ssdsd"),
        ("c++", "c++x"),
        ("deal", "#deals"),
        ("100", "$1000"),
    ],
)
def test_no_coincide_dentro_de_palabras_mayores(keyword, texto):
    assert not coincide(keyword, texto)


def test_patron_no_es_vulnerable_a_regex():
    patron = compilar_patron("a.*b")
    assert patron.search("a.*b") is not None
    assert patron.search("axxxxxb") is None
