from bot.ofertas_bot import OfertasBot
from config import Config
from database.db_manager import DBManager
from utils.models import Oferta


def crear(tag: str, indice: int) -> Oferta:
    return Oferta.create(
        titulo=f"{tag}-{indice}",
        precio=f"${indice}",
        link=f"https://example.com/{tag}/{indice}",
        tag=tag,
    )


def crear_bot(tmp_path, maximo: int = 4) -> OfertasBot:
    config = Config()
    config.MAX_OFERTAS_POR_EJECUCION = maximo
    return OfertasBot(
        config=config,
        db_manager=DBManager(str(tmp_path / "seleccion.db")),
        scrapers={},
    )


def test_reparto_equilibrado_entre_fuentes(tmp_path):
    bot = crear_bot(tmp_path, maximo=4)
    fuente_a = [crear("#A", i) for i in range(3)]
    fuente_b = [crear("#B", i) for i in range(3)]

    seleccion = bot.seleccionar_ofertas_equilibradas(fuente_a, fuente_b)

    assert len(seleccion) == 4
    assert sum(1 for oferta in seleccion if oferta.tag == "#A") == 2
    assert sum(1 for oferta in seleccion if oferta.tag == "#B") == 2


def test_respeta_maximo_y_no_duplica(tmp_path):
    bot = crear_bot(tmp_path, maximo=10)
    fuente = [crear("#A", i) for i in range(4)]
    seleccion = bot.seleccionar_ofertas_equilibradas(fuente, fuente)

    assert len(seleccion) == 4
    assert len({(oferta.titulo, oferta.link) for oferta in seleccion}) == 4


def test_fuentes_vacias(tmp_path):
    bot = crear_bot(tmp_path)
    assert bot.seleccionar_ofertas_equilibradas([], []) == []
