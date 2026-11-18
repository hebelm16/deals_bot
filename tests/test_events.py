"""Pruebas del modo evento (/evento): estado, topes diarios, ciclo y handlers."""

import time
from types import SimpleNamespace

import pytest
from telegram.ext import Application, CallbackQueryHandler, CommandHandler

from bot import ofertas_bot
from bot.handlers import comando_evento, manejar_callback_evento, setup_handlers
from bot.ofertas_bot import OfertasBot
from config import Config
from database.db_manager import DBManager
from utils.ai_helper import Publicacion
from utils.events import GestorEvento, etiqueta_evento, formatear_hashtag
from utils.formatting import render_offer_text
from utils.models import Oferta


class _FakeMessage:
    def __init__(self, message_id: int = 1):
        self.message_id = message_id
        self.respuestas: list[tuple[str, dict]] = []

    async def reply_text(self, text: str, **kwargs):
        self.respuestas.append((text, kwargs))
        return self


class _FakeQuery:
    def __init__(self, data: str, chat_id: int = 123):
        self.data = data
        self.message = SimpleNamespace(chat_id=chat_id)
        self.respondido = False
        self.editados: list[tuple[str, dict]] = []

    async def answer(self, *args, **kwargs):
        self.respondido = True

    async def edit_message_text(self, text: str, **kwargs):
        self.editados.append((text, kwargs))


class _FakeBot:
    def __init__(self):
        self.envios: list[tuple[str, str, str]] = []
        self._id = 10

    async def send_photo(self, **kwargs):
        self._id += 1
        self.envios.append(("foto", str(kwargs.get("chat_id")), kwargs.get("caption", "")))
        return _FakeMessage(self._id)

    async def send_message(self, **kwargs):
        self._id += 1
        self.envios.append(("texto", str(kwargs.get("chat_id")), kwargs.get("text", "")))
        return _FakeMessage(self._id)


def _config_base() -> Config:
    cfg = Config()
    cfg.TOKEN = "123456:ABC"
    cfg.CHANNEL_ID = "canal"
    cfg.USER_ID = "999"
    cfg.SEND_OFFER_INTERVAL_SECONDS = 0
    cfg.ALERT_SEND_INTERVAL_SECONDS = 0
    cfg.DESCARGAR_IMAGENES = False
    cfg.AI_HOOK_REQUIRED = False
    cfg.LOOP_INTERVAL_SECONDS = 7200
    cfg.MAX_OFERTAS_POR_EJECUCION = 20
    cfg.EVENTO_INTERVAL_SECONDS = 900
    cfg.EVENTO_MAX_OFERTAS_POR_EJECUCION = 5
    cfg.EVENTO_MAX_OFERTAS_DIA = 100
    cfg.EVENTO_MAX_IA_DIA = 350
    cfg.EVENTO_HORAS_DEFECTO = 72
    return cfg


def test_formatear_hashtag_y_etiqueta():
    assert formatear_hashtag("black_friday") == "#BlackFriday"
    assert formatear_hashtag("prime-day") == "#PrimeDay"
    assert formatear_hashtag("BlackFriday") == "#BlackFriday"
    assert formatear_hashtag("#cyber_monday") == "#CyberMonday"
    assert etiqueta_evento("amazon_day") == "🔥 #AmazonDay"
    with pytest.raises(ValueError):
        formatear_hashtag("!!!")


async def test_persistencia_y_expiracion_evento(tmp_path):
    db = DBManager(str(tmp_path / "ev.db"))
    await db.init_db()
    cfg = _config_base()

    ahora = 1_700_000_000.0
    gestor = GestorEvento(db, cfg)
    await gestor.activar("black_friday", 2, ahora=ahora)
    assert gestor.esta_activo(ahora + 100)
    assert gestor.intervalo_ciclo(ahora + 100) == 900
    assert gestor.max_ofertas_ciclo(ahora + 100) == 5
    assert gestor.aplicar_etiqueta("#Slickdeals", ahora + 100) == "#Slickdeals 🔥 #BlackFriday"

    # Simula reinicio del bot mientras sigue activo.
    gestor2 = GestorEvento(db, cfg)
    expirado = await gestor2.cargar(ahora=ahora + 3600)
    assert expirado is None
    assert gestor2.esta_activo(ahora + 3600)
    assert gestor2.estado.etiqueta == "🔥 #BlackFriday"

    # Simula reinicio cuando ya expiró.
    gestor3 = GestorEvento(db, cfg)
    expirado = await gestor3.cargar(ahora=ahora + 8000)
    assert expirado == "black_friday"
    assert not gestor3.esta_activo(ahora + 8000)
    assert gestor3.intervalo_ciclo(ahora + 8000) == 7200


async def test_cuota_diaria_se_reinicia_al_cambiar_de_dia(tmp_path):
    db = DBManager(str(tmp_path / "cuota.db"))
    await db.init_db()
    cfg = _config_base()
    cfg.EVENTO_MAX_IA_DIA = 2
    cfg.EVENTO_MAX_OFERTAS_DIA = 2

    dia1 = time.mktime((2026, 11, 27, 10, 0, 0, 0, 0, -1))
    dia2 = dia1 + 24 * 3600

    gestor = GestorEvento(db, cfg)
    await gestor.activar("black_friday", 72, ahora=dia1)
    await gestor.registrar_llamada_ia(ahora=dia1)
    await gestor.registrar_llamada_ia(ahora=dia1)
    assert not gestor.puede_usar_ia(ahora=dia1)

    await gestor.registrar_publicacion(ahora=dia1)
    await gestor.registrar_publicacion(ahora=dia1)
    assert gestor.cupo_publicaciones_restante(ahora=dia1) == 0
    assert gestor.max_ofertas_ciclo(ahora=dia1) == 0

    # Al día siguiente se reinician ambos contadores.
    assert gestor.puede_usar_ia(ahora=dia2)
    assert gestor.cupo_publicaciones_restante(ahora=dia2) == 2
    assert gestor.max_ofertas_ciclo(ahora=dia2) == 2


async def test_ciclo_evento_limita_por_ciclo_etiqueta_y_respeta_tope_ia(tmp_path, monkeypatch):
    db = DBManager(str(tmp_path / "ciclo_ev.db"))
    await db.init_db()
    cfg = _config_base()
    cfg.EVENTO_MAX_OFERTAS_POR_EJECUCION = 3
    cfg.EVENTO_MAX_IA_DIA = 2
    cfg.EVENTO_MAX_OFERTAS_DIA = 4

    llamadas_ia = 0

    async def ia_falsa(titulo, precio, original, requerido=None):
        nonlocal llamadas_ia
        llamadas_ia += 1
        return Publicacion(f"Producto ES {llamadas_ia}", "Ese precio está nítido.")

    monkeypatch.setattr(ofertas_bot, "generar_publicacion", ia_falsa)

    bot = OfertasBot(config=cfg, db_manager=db, scrapers={})
    fake = _FakeBot()
    bot.bot = fake
    await bot.evento.activar("black_friday", 72)

    ofertas = [
        Oferta.create(
            titulo=f"Gadget Modelo {i}00",
            precio=f"${10 + i}",
            link=f"https://example.com/item-{i}",
            tag="#DealNews",
        )
        for i in range(1, 7)
    ]

    # Primer ciclo: máximo 3 por ciclo, 2 con IA y la 3ra con plantilla local.
    enviadas = await bot._process_new_deals({"dealnews": ofertas[:4]})
    assert enviadas == 3
    assert llamadas_ia == 2
    assert bot.evento.estado.pub_usadas_hoy == 3
    assert all("🔥 #BlackFriday" in texto for _, _, texto in fake.envios)
    assert "Producto ES 1" in render_offer_text(ofertas[0])

    # Segundo ciclo: solo queda 1 de cupo diario (4 - 3 = 1), sin IA.
    enviadas2 = await bot._process_new_deals({"dealnews": ofertas[4:]})
    assert enviadas2 == 1
    assert llamadas_ia == 2
    assert bot.evento.estado.pub_usadas_hoy == 4

    # Tercer ciclo: tope diario alcanzado -> 0 publicaciones.
    extra = Oferta.create(
        titulo="Otro Producto 900",
        precio="$20",
        link="https://example.com/item-9",
        tag="#DealNews",
    )
    assert await bot._process_new_deals({"dealnews": [extra]}) == 0


async def test_reprogramar_ciclo_y_expiracion_automatica(tmp_path):
    db = DBManager(str(tmp_path / "jq.db"))
    await db.init_db()
    cfg = _config_base()
    bot = OfertasBot(config=cfg, db_manager=db, scrapers={})
    fake = _FakeBot()
    bot.bot = fake
    app = Application.builder().token(cfg.TOKEN).build()
    bot.application = app

    app.job_queue.run_repeating(
        bot.scheduled_check_ofertas,
        interval=cfg.LOOP_INTERVAL_SECONDS,
        first=7200,
        name="ciclo_ofertas",
    )

    await bot.evento.activar("black_friday", 1)
    bot.reprogramar_ciclo(ejecutar_pronto=True)
    jobs = app.job_queue.get_jobs_by_name("ciclo_ofertas")
    assert len(jobs) == 1
    assert jobs[0].job.trigger.interval.total_seconds() == 900

    # Fuerza expiración y ejecuta la tarea de revisión.
    bot.evento.estado.fin_ts = time.time() - 10
    await bot._tarea_revisar_evento()
    assert not bot.evento.esta_activo()
    jobs_despues = app.job_queue.get_jobs_by_name("ciclo_ofertas")
    assert len(jobs_despues) == 1
    assert jobs_despues[0].job.trigger.interval.total_seconds() == 7200
    assert any("finalizado" in texto for _, _, texto in fake.envios)


async def test_comando_evento_y_botones(tmp_path):
    db = DBManager(str(tmp_path / "cmd.db"))
    await db.init_db()
    cfg = _config_base()
    bot = OfertasBot(config=cfg, db_manager=db, scrapers={})
    app = Application.builder().token(cfg.TOKEN).build()
    bot.application = app
    setup_handlers(app, bot)

    # Verifica que /evento y los callbacks con patrón quedaron registrados.
    handlers = app.handlers[0]
    comandos = {
        cmd
        for h in handlers
        if isinstance(h, CommandHandler)
        for cmd in h.commands
    }
    assert "evento" in comandos
    callbacks = [h for h in handlers if isinstance(h, CallbackQueryHandler)]
    assert len(callbacks) == 2

    # Usuario no admin es rechazado.
    msg_no_admin = _FakeMessage()
    upd_no_admin = SimpleNamespace(
        effective_user=SimpleNamespace(id=111),
        effective_message=msg_no_admin,
        message=msg_no_admin,
        callback_query=None,
    )
    ctx = SimpleNamespace(bot_data={"bot": bot}, args=["black_friday", "72"], bot=_FakeBot())
    await comando_evento(upd_no_admin, ctx)
    assert "No tienes permiso" in msg_no_admin.respuestas[0][0]
    assert not bot.evento.esta_activo()

    # Admin activa con /evento black_friday 72.
    msg_admin = _FakeMessage()
    upd_admin = SimpleNamespace(
        effective_user=SimpleNamespace(id=999),
        effective_message=msg_admin,
        message=msg_admin,
        callback_query=None,
    )
    await comando_evento(upd_admin, ctx)
    assert bot.evento.esta_activo()
    assert bot.evento.estado.etiqueta == "🔥 #BlackFriday"
    assert "Modo evento activado" in msg_admin.respuestas[0][0]

    # Admin consulta /evento sin argumentos -> muestra panel con botones.
    ctx_vacio = SimpleNamespace(bot_data={"bot": bot}, args=[], bot=_FakeBot())
    await comando_evento(upd_admin, ctx_vacio)
    assert "Modo evento activo" in msg_admin.respuestas[1][0]
    assert msg_admin.respuestas[1][1]["reply_markup"] is not None

    # Admin desactiva con botón inline.
    query_off = _FakeQuery("evento:off")
    upd_cb = SimpleNamespace(
        effective_user=SimpleNamespace(id=999),
        effective_message=None,
        message=None,
        callback_query=query_off,
    )
    await manejar_callback_evento(upd_cb, ctx_vacio)
    assert query_off.respondido
    assert not bot.evento.esta_activo()
    assert "desactivado" in query_off.editados[0][0]

    # Admin activa con botón inline de Prime Day.
    query_on = _FakeQuery("evento:on:prime_day:48")
    upd_cb_on = SimpleNamespace(
        effective_user=SimpleNamespace(id=999),
        effective_message=None,
        message=None,
        callback_query=query_on,
    )
    await manejar_callback_evento(upd_cb_on, ctx_vacio)
    assert bot.evento.esta_activo()
    assert bot.evento.estado.etiqueta == "🔥 #PrimeDay"

    # Admin extiende +24h con botón inline.
    fin_antes = bot.evento.estado.fin_ts
    query_ext = _FakeQuery("evento:extender:24")
    upd_cb_ext = SimpleNamespace(
        effective_user=SimpleNamespace(id=999),
        effective_message=None,
        message=None,
        callback_query=query_ext,
    )
    await manejar_callback_evento(upd_cb_ext, ctx_vacio)
    assert bot.evento.estado.fin_ts > fin_antes
    assert "extendido +24h" in query_ext.editados[0][0]


async def test_cargar_evento_formato_legado_y_corrupto(tmp_path):
    db = DBManager(str(tmp_path / "legacy.db"))
    await db.init_db()
    cfg = _config_base()
    ahora = 1_700_000_000.0

    await db.set_ajuste("evento.estado", f"black_friday|{ahora + 3600}|12")
    gestor = GestorEvento(db, cfg)
    assert await gestor.cargar(ahora=ahora) is None
    assert gestor.esta_activo(ahora)
    assert gestor.estado.ia_usadas_hoy == 12

    await db.set_ajuste("evento.estado", "{json-roto")
    gestor2 = GestorEvento(db, cfg)
    assert await gestor2.cargar(ahora=ahora) is None
    assert not gestor2.esta_activo(ahora)
