"""Título en español + gancho en una sola llamada de IA."""

from types import SimpleNamespace

import pytest

from bot.ofertas_bot import OfertasBot
from config import Config
from database.db_manager import DBManager
from utils import ai_helper
from utils.ai_helper import (
    Publicacion,
    generar_publicacion,
    parsear_publicacion,
)
from utils.formatting import render_offer_text
from utils.models import Oferta

ORIGINAL = "Samsung 65-inch S90F OLED 4K Smart TV $800"


def test_parsea_titulo_y_gancho():
    texto = (
        "TITULO: Smart TV Samsung S90F OLED 4K de 65 pulgadas\n"
        "GANCHO: Klk, ese OLED de 65 está jevi a ese precio. 📺"
    )
    pub = parsear_publicacion(texto, ORIGINAL)
    assert pub is not None
    assert pub.titulo_es == "Smart TV Samsung S90F OLED 4K de 65 pulgadas"
    assert pub.gancho.startswith("Klk")


def test_acepta_formato_con_acentos_y_markdown():
    texto = "**Título:** Audífonos Sony WH-1000XM5\n**Gancho:** Están nítidos esos audífonos Sony."
    pub = parsear_publicacion(texto, "Sony WH-1000XM5 Headphones $248")
    assert pub is not None
    assert pub.titulo_es == "Audífonos Sony WH-1000XM5"


def test_sin_gancho_es_invalido():
    assert parsear_publicacion("TITULO: Smart TV Samsung 65 pulgadas", ORIGINAL) is None
    assert parsear_publicacion("", ORIGINAL) is None
    assert parsear_publicacion(None, ORIGINAL) is None


def test_titulo_que_pierde_numeros_se_descarta_pero_conserva_gancho():
    texto = "TITULO: Smart TV Samsung OLED 4K\nGANCHO: Está jevi ese televisor, aprovecha."
    pub = parsear_publicacion(texto, ORIGINAL)
    assert pub is not None
    assert pub.titulo_es is None  # perdió 65 y 90
    assert pub.gancho.startswith("Está jevi")


def test_titulo_cortado_o_demasiado_largo_se_descarta():
    gancho = "GANCHO: Ese precio está nítido, míralo."
    completo = "Smart TV Samsung S90F OLED 4K de 65 pulgadas"
    assert parsear_publicacion(f"TITULO: {completo}\n{gancho}", ORIGINAL).titulo_es
    # Cortado a mitad de frase (termina en preposición o símbolo).
    assert parsear_publicacion(f"TITULO: {completo} con\n{gancho}", ORIGINAL).titulo_es is None
    assert parsear_publicacion(f"TITULO: {completo} $\n{gancho}", ORIGINAL).titulo_es is None
    assert parsear_publicacion(f"TITULO: {completo} {'a' * 130}\n{gancho}", ORIGINAL).titulo_es is None


def test_formato_usa_titulo_es_si_existe():
    oferta = Oferta.create(
        titulo=ORIGINAL, precio="$800", link="https://example.com", tag="#T"
    )
    assert "Samsung 65-inch S90F OLED 4K Smart TV" in render_offer_text(oferta)
    oferta.titulo_es = "Smart TV Samsung S90F OLED 4K de 65 pulgadas"
    texto = render_offer_text(oferta)
    assert "Smart TV Samsung S90F OLED 4K de 65 pulgadas" in texto
    assert "65-inch" not in texto


class _Respuesta:
    def __init__(self, text):
        self.text = text


def _gemini(monkeypatch, texto, llamadas=None):
    class Modelos:
        async def generate_content(self, **kwargs):
            if llamadas is not None:
                llamadas.append(kwargs)
            return _Respuesta(texto)

    monkeypatch.setattr(Config, "GEMINI_API_KEYS", "clave-falsa")
    monkeypatch.setattr(Config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(Config, "GEMINI_API_KEY_BACKUP", "")
    monkeypatch.setattr(Config, "GROQ_API_KEY", "")
    monkeypatch.setattr(
        ai_helper,
        "genai",
        SimpleNamespace(
            Client=lambda api_key=None: SimpleNamespace(
                aio=SimpleNamespace(models=Modelos())
            )
        ),
    )
    monkeypatch.setattr(ai_helper, "_cache", {})

    async def sin_descubrimiento(_keys):
        return []

    monkeypatch.setattr(ai_helper, "descubrir_modelos_gemini", sin_descubrimiento)


async def test_una_sola_llamada_devuelve_titulo_y_gancho(monkeypatch):
    llamadas: list = []
    _gemini(
        monkeypatch,
        "TITULO: Smart TV Samsung S90F OLED 4K de 65 pulgadas\n"
        "GANCHO: Klk, ese OLED de 65 está jevi a ese precio.",
        llamadas,
    )
    pub = await generar_publicacion(ORIGINAL, "$800", "$1,299", requerido=False)
    assert pub.titulo_es == "Smart TV Samsung S90F OLED 4K de 65 pulgadas"
    assert "jevi" in pub.gancho
    assert len(llamadas) == 1
    assert "TITULO" in llamadas[0]["config"].system_instruction

    await generar_publicacion(ORIGINAL, "$800", "$1,299", requerido=False)
    assert len(llamadas) == 1  # segunda vez sale del caché


async def test_respuesta_invalida_usa_plantilla_sin_titulo(monkeypatch):
    _gemini(monkeypatch, "Claro, aquí tienes un resumen largo sin formato.")
    pub = await generar_publicacion(ORIGINAL, "$800", "$1,299", requerido=False)
    assert pub.titulo_es is None
    assert pub.gancho
    assert await generar_publicacion(ORIGINAL, "$800", None, requerido=True) is None


async def test_ciclo_publica_con_titulo_traducido(tmp_path, monkeypatch):
    from bot import ofertas_bot

    async def falsa(titulo, precio, original, requerido=None):
        return Publicacion("Teclado mecánico Keychron K2", "Ese teclado está nítido.")

    monkeypatch.setattr(ofertas_bot, "generar_publicacion", falsa)

    class Msg:
        message_id = 7

    envios = []

    class FakeBot:
        async def send_message(self, **kw):
            envios.append(kw.get("text"))
            return Msg()

        async def send_photo(self, **kw):
            envios.append(kw.get("caption"))
            return Msg()

    db = DBManager(str(tmp_path / "pub.db"))
    await db.init_db()
    config = Config()
    config.CHANNEL_ID = "canal"
    config.SEND_OFFER_INTERVAL_SECONDS = 0
    config.DESCARGAR_IMAGENES = False
    bot = OfertasBot(config=config, db_manager=db, scrapers={})
    bot.bot = FakeBot()

    oferta = Oferta.create(
        titulo="Keychron K2 Mechanical Keyboard $59",
        precio="$59",
        link="https://example.com/k2",
        tag="#T",
    )
    assert await bot._process_new_deals({"f": [oferta]}) == 1
    assert any("Teclado mecánico Keychron K2" in (t or "") for t in envios)
    # La deduplicación sigue usando el título original, no el traducido.
    assert (await bot._filter_new_deals({"f": [oferta]}))["f"] == []


@pytest.mark.parametrize("requerido", [True, False])
async def test_timeout_usa_respaldo_segun_regla(tmp_path, monkeypatch, requerido):
    from bot import ofertas_bot

    async def lenta(*a, **k):
        import asyncio

        await asyncio.sleep(5)

    monkeypatch.setattr(ofertas_bot, "generar_publicacion", lenta)
    db = DBManager(str(tmp_path / "t.db"))
    await db.init_db()
    config = Config()
    config.AI_HOOK_TIMEOUT_SECONDS = 0.05
    config.AI_HOOK_REQUIRED = requerido
    bot = OfertasBot(config=config, db_manager=db, scrapers={})
    oferta = Oferta.create(titulo="SSD 1TB", precio="$50", link="https://e.com", tag="#T")
    resultado = await bot._generar_gancho(oferta)
    assert (resultado is None) == requerido
    if not requerido:
        assert resultado.titulo_es is None and resultado.gancho


def test_titulo_igual_al_original_no_cuenta_como_traduccion():
    original = "Sony WH-1000XM5 Wireless Noise Cancelling Headphones $248"
    texto = (
        "TITULO: Sony WH-1000XM5 Wireless Noise Cancelling Headphones\n"
        "GANCHO: Están nítidos esos audífonos, aprovecha."
    )
    pub = parsear_publicacion(texto, original)
    assert pub is not None and pub.titulo_es is None
    traducido = (
        "TITULO: Audífonos inalámbricos Sony WH-1000XM5 con cancelación de ruido\n"
        "GANCHO: Están nítidos esos audífonos, aprovecha."
    )
    assert parsear_publicacion(traducido, original).titulo_es
