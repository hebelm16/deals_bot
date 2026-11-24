"""Pruebas de la cola de pendientes y del comando /stats."""

import time
from types import SimpleNamespace

from bot.handlers import comando_stats
from bot.ofertas_bot import OfertasBot
from config import Config
from database.db_manager import ESTADO_EN_COLA, ESTADO_EXPIRADA, DBManager
from utils.models import Oferta


class FakeMessage:
    def __init__(self, message_id: int = 1):
        self.message_id = message_id
        self.respuestas: list[tuple[str, dict]] = []

    async def reply_text(self, text: str, **kwargs):
        self.respuestas.append((text, kwargs))
        return self


class FakeBot:
    def __init__(self):
        self.envios: list[tuple[str, str, str]] = []
        self._id = 100

    async def send_photo(self, **kwargs):
        self._id += 1
        self.envios.append(("foto", str(kwargs.get("chat_id")), kwargs.get("caption")))
        return FakeMessage(self._id)

    async def send_message(self, **kwargs):
        self._id += 1
        self.envios.append(("texto", str(kwargs.get("chat_id")), kwargs.get("text")))
        return FakeMessage(self._id)


def _config() -> Config:
    config = Config()
    config.CHANNEL_ID = "canal"
    config.ALERT_SEND_INTERVAL_SECONDS = 0
    config.SEND_OFFER_INTERVAL_SECONDS = 0
    config.AI_HOOK_REQUIRED = False
    config.DESCARGAR_IMAGENES = False
    config.MAX_OFERTAS_POR_EJECUCION = 2
    config.COLA_PENDIENTES_ACTIVA = True
    config.COLA_PENDIENTES_MAX = 10
    config.COLA_PENDIENTES_TTL_HORAS = 24
    config.COLA_PENDIENTES_TTL_HORAS_EVENTO = 6
    return config


def _sin_ia(monkeypatch):
    for variable in (
        "GEMINI_API_KEYS",
        "GEMINI_API_KEY",
        "GEMINI_API_KEY_BACKUP",
        "GROQ_API_KEY",
    ):
        monkeypatch.setattr(Config, variable, "")


def _oferta(numero: int, descuento: int = 50) -> Oferta:
    original = 100
    return Oferta.create(
        titulo=f"Producto Modelo {numero}00",
        precio=f"${original - descuento}",
        precio_original=f"${original}",
        link=f"https://example.com/item-{numero}",
        tag="#DealNews",
    )


async def test_db_encola_y_recupera(tmp_path):
    db = DBManager(str(tmp_path / "cola.db"))
    await db.init_db()

    assert await db.contar_en_cola() == 0
    guardadas = await db.encolar_ofertas([_oferta(1), _oferta(2)])
    assert guardadas == 2
    assert await db.contar_en_cola() == 2

    filas = await db.obtener_en_cola(limite=10, max_edad_segundos=3600)
    assert len(filas) == 2
    assert filas[0]["titulo"].startswith("Producto Modelo")
    assert filas[0]["link"].startswith("https://example.com/item-")

    # Ya en cola, la oferta cuenta como conocida: no se vuelve a raspar como nueva.
    ids, canonicos = await db.obtener_indices_existentes()
    assert len(ids) >= 2
    assert any("item-1" in url for url in canonicos)


async def test_db_expira_lo_viejo(tmp_path):
    db = DBManager(str(tmp_path / "expira.db"))
    await db.init_db()

    vieja = Oferta.create(
        titulo="Producto viejo en cola",
        precio="$50",
        precio_original="$100",
        link="https://example.com/vieja",
        tag="#DealNews",
        timestamp=int(time.time()) - 7200,
    )
    await db.encolar_ofertas([_oferta(1), vieja])
    assert await db.contar_en_cola() == 2

    # Con 1 hora de vida máxima, la de 2 horas caduca y la nueva se queda.
    assert await db.expirar_cola(max_edad_segundos=3600) == 1
    assert await db.contar_en_cola() == 1

    filas = await db.obtener_en_cola(limite=10, max_edad_segundos=86400)
    assert [fila["link"] for fila in filas] == ["https://example.com/item-1"]

    # Una caducada no se publica, pero sigue contando para la deduplicación.
    ids, canonicos = await db.obtener_indices_existentes()
    assert any("vieja" in url for url in canonicos)


async def test_ciclo_encola_sobrantes_y_los_publica_despues(tmp_path, monkeypatch):
    _sin_ia(monkeypatch)
    db = DBManager(str(tmp_path / "flujo.db"))
    await db.init_db()
    config = _config()  # máximo 2 por ciclo

    bot = OfertasBot(config=config, db_manager=db, scrapers={})
    fake = FakeBot()
    bot.bot = fake

    # Cinco candidatas: dos se publican y tres quedan en cola.
    candidatas = [_oferta(numero) for numero in range(1, 6)]
    enviadas = await bot._process_new_deals({"dealnews": candidatas})
    assert enviadas == 2
    assert await db.contar_en_cola() == 3

    # Siguiente ciclo sin ofertas nuevas: la cola se publica sola.
    en_cola = await bot._ofertas_en_cola()
    assert en_cola
    enviadas2 = await bot._process_new_deals(en_cola)
    assert enviadas2 == 2
    assert await db.contar_en_cola() == 1

    # Y una tercera vuelta agota la cola.
    enviadas3 = await bot._process_new_deals(await bot._ofertas_en_cola())
    assert enviadas3 == 1
    assert await db.contar_en_cola() == 0

    # Nada se publicó dos veces.
    titulos = [texto for _, _, texto in fake.envios]
    assert len(titulos) == 5
    assert len(set(titulos)) == 5


async def test_no_encola_si_esta_desactivada(tmp_path, monkeypatch):
    _sin_ia(monkeypatch)
    db = DBManager(str(tmp_path / "off.db"))
    await db.init_db()
    config = _config()
    config.COLA_PENDIENTES_ACTIVA = False

    bot = OfertasBot(config=config, db_manager=db, scrapers={})
    bot.bot = FakeBot()

    await bot._process_new_deals({"dealnews": [_oferta(n) for n in range(1, 6)]})
    assert await db.contar_en_cola() == 0


async def test_no_encola_sin_precio_ni_duplicadas(tmp_path, monkeypatch):
    _sin_ia(monkeypatch)
    db = DBManager(str(tmp_path / "filtro.db"))
    await db.init_db()
    config = _config()
    config.MAX_OFERTAS_POR_EJECUCION = 1

    bot = OfertasBot(config=config, db_manager=db, scrapers={})
    bot.bot = FakeBot()

    publicada = _oferta(1)
    sin_precio = Oferta.create(
        titulo="Producto sin precio", precio="No disponible",
        link="https://example.com/sin-precio", tag="#DealNews",
    )
    # Duplicada exacta de la que sí se publica.
    duplicada = Oferta.create(
        titulo=publicada.titulo, precio="$49",
        precio_original="$100",
        link="https://example.com/dup", tag="#DealNews",
    )
    with_descuento = _oferta(2)

    await bot._process_new_deals(
        {"dealnews": [publicada, sin_precio, duplicada, with_descuento]}
    )

    titulos = [fila["titulo"] for fila in await db.obtener_en_cola(10, 86400)]
    assert titulos == [with_descuento.titulo]


async def test_stats_agrupa_fuente_aunque_haya_etiqueta_de_evento(tmp_path):
    db = DBManager(str(tmp_path / "tags.db"))
    await db.init_db()
    for indice, tag in enumerate(("#DealNews", "#DealNews 🔥 #BlackFriday", "#DealNews")):
        await db.guardar_oferta(
            Oferta.create(
                titulo=f"Producto {indice}",
                precio="$50",
                precio_original="$100",
                link=f"https://example.com/producto-{indice}",
                tag=tag,
            ),
            estado="enviada",
        )
    por_fuente = await db.contar_por_fuente("enviada")
    assert por_fuente == {"#DealNews": 3}


async def test_tope_diario_del_evento_no_encola(tmp_path, monkeypatch):
    _sin_ia(monkeypatch)
    db = DBManager(str(tmp_path / "tope.db"))
    await db.init_db()
    config = _config()
    config.EVENTO_MAX_OFERTAS_DIA = 2

    bot = OfertasBot(config=config, db_manager=db, scrapers={})
    bot.bot = FakeBot()
    await bot.evento.activar("black_friday", 72)
    bot.evento.estado.pub_usadas_hoy = 2

    enviadas = await bot._process_new_deals({"dealnews": [_oferta(1)]})
    assert enviadas == 0
    assert await db.contar_en_cola() == 0


async def test_comando_stats(tmp_path, monkeypatch):
    _sin_ia(monkeypatch)
    db = DBManager(str(tmp_path / "stats.db"))
    await db.init_db()
    config = _config()

    bot = OfertasBot(config=config, db_manager=db, scrapers={})
    bot.bot = FakeBot()
    await bot._process_new_deals({"dealnews": [_oferta(n) for n in range(1, 6)]})

    # Una suscripción para comprobar que aparece el dato.
    await db.agregar_suscripcion("u1", "u1", "ssd")

    msg = FakeMessage()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=int(config.USER_ID)),
        effective_message=msg,
        message=msg,
        callback_query=None,
    )
    ctx = SimpleNamespace(bot_data={"bot": bot}, args=[], bot=FakeBot())
    await comando_stats(update, ctx)

    texto, kwargs = msg.respuestas[0]
    assert kwargs.get("parse_mode") == "HTML"
    assert "Estadísticas" in texto
    assert "Publicadas por fuente" in texto
    assert "#DealNews" in texto
    assert "Últimas 24 h" in texto
    assert "Mayores descuentos" in texto
    assert "Modo evento" in texto
    assert "Suscripciones: <b>1</b>" in texto


async def test_comando_stats_sin_datos(tmp_path, monkeypatch):
    _sin_ia(monkeypatch)
    db = DBManager(str(tmp_path / "vacio.db"))
    await db.init_db()
    config = _config()

    bot = OfertasBot(config=config, db_manager=db, scrapers={})
    bot.bot = FakeBot()

    msg = FakeMessage()
    update = SimpleNamespace(
        effective_user=SimpleNamespace(id=int(config.USER_ID)),
        effective_message=msg,
        message=msg,
        callback_query=None,
    )
    ctx = SimpleNamespace(bot_data={"bot": bot}, args=[], bot=FakeBot())
    await comando_stats(update, ctx)

    texto = msg.respuestas[0][0]
    assert "Publicadas: <b>0</b>" in texto
    assert "Mayores descuentos" not in texto


def test_estados_de_cola_son_distintos():
    assert ESTADO_EN_COLA != ESTADO_EXPIRADA
    assert ESTADO_EN_COLA not in ("pendiente", "enviada", "duplicada", "excluida")
