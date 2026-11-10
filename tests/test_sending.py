from telegram.error import BadRequest

from bot.ofertas_bot import OfertasBot
from config import Config
from database.db_manager import DBManager
from utils.models import Oferta


class FakeMessage:
    message_id = 42


class FakeBot:
    def __init__(self, falla_foto: bool = False, falla_html: bool = False):
        self.falla_foto = falla_foto
        self.falla_html = falla_html
        self.fotos = 0
        self.mensajes = 0

    async def send_photo(self, **kwargs):
        self.fotos += 1
        if self.falla_foto:
            raise BadRequest("Wrong type of the web page content")
        return FakeMessage()

    async def send_message(self, **kwargs):
        self.mensajes += 1
        if self.falla_html and kwargs.get("parse_mode") == "HTML":
            raise BadRequest("Can't parse entities: character '&' is reserved")
        return FakeMessage()


def crear_bot(tmp_path, fake: FakeBot, reintentos: int = 2) -> OfertasBot:
    config = Config()
    config.CHANNEL_ID = "123"
    config.SEND_OFFER_MAX_RETRIES = reintentos
    config.SEND_OFFER_RETRY_SLEEP_SECONDS = 0
    bot = OfertasBot(
        config=config,
        db_manager=DBManager(str(tmp_path / "envio.db")),
        scrapers={},
    )
    bot.bot = fake
    return bot


def crear_oferta(**kwargs) -> Oferta:
    datos = dict(
        titulo="Producto & <prueba>",
        precio="$10",
        link="https://example.com/p",
        tag="#Test",
        imagen="https://example.com/p.jpg",
    )
    datos.update(kwargs)
    return Oferta.create(**datos)


async def test_si_falla_la_foto_se_envia_texto(tmp_path):
    fake = FakeBot(falla_foto=True)
    bot = crear_bot(tmp_path, fake)

    assert await bot.enviar_oferta_con_reintento(crear_oferta()) == 42
    assert fake.fotos == 1
    assert fake.mensajes == 1


async def test_si_falla_el_html_se_envia_texto_plano(tmp_path):
    fake = FakeBot(falla_html=True)
    bot = crear_bot(tmp_path, fake)

    assert await bot.enviar_oferta_con_reintento(crear_oferta(imagen=None)) == 42
    assert fake.fotos == 0
    assert fake.mensajes == 2


async def test_sin_imagen_envia_mensaje(tmp_path):
    fake = FakeBot()
    bot = crear_bot(tmp_path, fake)

    assert await bot.enviar_oferta_con_reintento(crear_oferta(imagen=None)) == 42
    assert fake.fotos == 0
    assert fake.mensajes == 1
