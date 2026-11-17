import pytest

from bot.ofertas_bot import OfertasBot
from config import Config
from database.db_manager import DBManager
from utils.filters import categoria_no_producto, parsear_categorias
from utils.models import Oferta


def _oferta(titulo: str, link: str = "https://example.com/x") -> Oferta:
    return Oferta.create(titulo=titulo, precio="$10", link=link, tag="#Test")


@pytest.mark.parametrize(
    "titulo,categoria",
    [
        (
            "Southwest Airlines Rewards Members: Book with Reward Points & Save: 25% Off",
            "viajes",
        ),
        ("Round-Trip Flights to Cancun from $199", "viajes"),
        ("Hotel Stays in Las Vegas 40% Off", "viajes"),
        ("Rapid Rewards bonus points promo", "puntos"),
        ("New Chase Credit Card $200 Bonus", "finanzas"),
        ("Open a Checking Account, Get $300", "finanzas"),
    ],
)
def test_detecta_ofertas_que_no_son_productos(titulo, categoria):
    assert categoria_no_producto(_oferta(titulo), ("viajes", "puntos", "finanzas")) == categoria


@pytest.mark.parametrize(
    "titulo",
    [
        "Thrustmaster Flight Stick Joystick",
        "Samsung 65-inch OLED 4K TV",
        "Slim Credit Card Holder Wallet",
        "Energy ESW-C8 Subwoofer",
        "Cruise Control Bluetooth Speaker",
    ],
)
def test_no_excluye_productos_normales(titulo):
    assert categoria_no_producto(_oferta(titulo), ("viajes", "puntos", "finanzas")) is None


def test_gift_cards_solo_si_se_piden():
    oferta = _oferta("$50 Amazon Gift Card for $42")
    assert categoria_no_producto(oferta) is None
    assert categoria_no_producto(oferta, ("gift_cards",)) == "gift_cards"


def test_parsear_categorias():
    assert parsear_categorias("viajes, Gift Cards,inventada") == ("viajes", "gift_cards")
    assert parsear_categorias("") == ()
    assert parsear_categorias(None) == ("viajes", "puntos", "finanzas")


async def test_filtro_guarda_excluidas_y_no_las_vuelve_a_ver(tmp_path):
    db = DBManager(str(tmp_path / "filtro.db"))
    await db.init_db()
    config = Config()
    config.CATEGORIAS_EXCLUIDAS = "viajes,puntos,finanzas"
    bot = OfertasBot(config=config, db_manager=db, scrapers={})

    vuelo = _oferta("Round-Trip Flights to Miami from $99", "https://example.com/vuelo")
    tv = _oferta("Samsung 55-inch 4K TV", "https://example.com/tv")

    nuevas = await bot._filter_new_deals({"fuente": [vuelo, tv]})
    assert [o.titulo for o in nuevas["fuente"]] == ["Samsung 55-inch 4K TV"]
    assert (await db.estadisticas())["excluidas"] == 1

    otra_vez = await bot._filter_new_deals({"fuente": [vuelo]})
    assert otra_vez["fuente"] == []
    assert (await db.estadisticas())["excluidas"] == 1
