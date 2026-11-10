from bot.ofertas_bot import OfertasBot
from config import Config
from database.db_manager import DBManager
from utils.models import Oferta


class FakeMessage:
    def __init__(self, message_id: int):
        self.message_id = message_id


class FakeBot:
    def __init__(self):
        self.envios = []
        self._id = 100

    async def send_photo(self, **kwargs):
        self._id += 1
        self.envios.append(("foto", kwargs.get("chat_id"), kwargs.get("caption")))
        return FakeMessage(self._id)

    async def send_message(self, **kwargs):
        self._id += 1
        self.envios.append(("texto", kwargs.get("chat_id"), kwargs.get("text")))
        return FakeMessage(self._id)


def _sin_ia(monkeypatch):
    for variable in (
        "GEMINI_API_KEYS",
        "GEMINI_API_KEY",
        "GEMINI_API_KEY_BACKUP",
        "GROQ_API_KEY",
    ):
        monkeypatch.setattr(Config, variable, "")


async def test_ciclo_guarda_ofertas_y_envia_alerta(tmp_path, monkeypatch):
    _sin_ia(monkeypatch)
    db = DBManager(str(tmp_path / "ciclo.db"))
    await db.init_db()
    await db.agregar_suscripcion("u1", "u1", "ssd")

    config = Config()
    config.CHANNEL_ID = "canal"
    config.ALERT_SEND_INTERVAL_SECONDS = 0
    config.SEND_OFFER_INTERVAL_SECONDS = 0
    config.AI_HOOK_REQUIRED = False
    config.DESCARGAR_IMAGENES = False

    bot = OfertasBot(config=config, db_manager=db, scrapers={})
    fake = FakeBot()
    bot.bot = fake

    ofertas = [
        Oferta.create(
            titulo="SSD 1TB",
            precio="$50",
            link="https://example.com/ssd",
            tag="#Test",
            imagen="https://example.com/ssd.jpg",
        ),
        Oferta.create(
            titulo="TV 4K",
            precio="$300",
            link="https://example.com/tv",
            tag="#Test",
            imagen=None,
        ),
    ]

    enviadas = await bot._process_new_deals({"test": ofertas})

    assert enviadas == 2
    stats = await db.estadisticas()
    assert stats["ofertas"] == 2
    assert stats["pendientes"] == 0
    assert stats["fallidas"] == 0

    destinos = [envio[1] for envio in fake.envios]
    assert "canal" in destinos
    assert "u1" in destinos


async def test_segundo_ciclo_no_duplica(tmp_path, monkeypatch):
    _sin_ia(monkeypatch)
    db = DBManager(str(tmp_path / "ciclo2.db"))
    await db.init_db()

    config = Config()
    config.CHANNEL_ID = "canal"
    config.SEND_OFFER_INTERVAL_SECONDS = 0
    config.DESCARGAR_IMAGENES = False
    bot = OfertasBot(config=config, db_manager=db, scrapers={})
    bot.bot = FakeBot()

    oferta = Oferta.create(
        titulo="Producto",
        precio="$10",
        link="https://example.com/producto?utm_source=feed",
        tag="#Test",
    )

    await bot._process_new_deals({"test": [oferta]})
    nuevas = await bot._filter_new_deals({"test": [oferta]})
    assert nuevas["test"] == []


async def test_guarda_duplicados_entre_fuentes(tmp_path, monkeypatch):
    _sin_ia(monkeypatch)
    db = DBManager(str(tmp_path / "ciclo3.db"))
    await db.init_db()

    config = Config()
    config.CHANNEL_ID = "canal"
    config.SEND_OFFER_INTERVAL_SECONDS = 0
    config.DESCARGAR_IMAGENES = False
    bot = OfertasBot(config=config, db_manager=db, scrapers={})
    bot.bot = FakeBot()

    original = Oferta.create(
        titulo="Apple AirPods Pro 3 Wireless Earbuds",
        precio="$50",
        precio_original="$100",
        link="https://example.com/airpods",
        tag="#Test",
    )
    duplicada = Oferta.create(
        titulo="Refurb Apple AirPods Pro 3 Wireless Earbuds",
        precio="$55",
        precio_original="$100",
        link="https://example.com/airpods-refurb",
        tag="#Test",
    )

    enviadas = await bot._process_new_deals({"test": [original, duplicada]})

    assert enviadas == 1
    stats = await db.estadisticas()
    assert stats["duplicadas"] == 1


def test_render_no_excede_caption():
    from utils.formatting import CAPTION_LIMIT, render_offer_text

    oferta = Oferta.create(
        titulo="A" * 3000,
        precio="$10",
        link="https://example.com/x",
        tag="#Test",
        info_cupon="B" * 2000,
        gancho_ia="C" * 500,
    )
    assert len(render_offer_text(oferta, limit=CAPTION_LIMIT)) <= CAPTION_LIMIT
