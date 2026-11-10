"""Comandos de usuario y administración del bot."""

import asyncio
import html
import os
import time
from functools import wraps

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import CallbackQueryHandler, CommandHandler, ContextTypes

from utils.ai_helper import (
    estado_ia,
    generar_gancho_ia,
    modelos_gemini_descubiertos,
)
from utils.keywords import normalizar_keyword


def setup_handlers(application, bot) -> None:
    application.add_handler(CommandHandler("start", comando_ayuda))
    application.add_handler(CommandHandler("ayuda", comando_ayuda))
    application.add_handler(CommandHandler("estado", obtener_estado))
    application.add_handler(CommandHandler("diagnostico", diagnostico))
    application.add_handler(CommandHandler("test_ia", test_ia))
    application.add_handler(CommandHandler("habilitar", habilitar_fuente))
    application.add_handler(CommandHandler("deshabilitar", deshabilitar_fuente))
    application.add_handler(CommandHandler("alerta", agregar_alerta))
    application.add_handler(CommandHandler("mis_alertas", mis_alertas))
    application.add_handler(CommandHandler("borrar_alerta", borrar_alerta))
    application.add_handler(CommandHandler("borrar_mis_datos", borrar_mis_datos))
    application.add_handler(CallbackQueryHandler(manejar_callback_fuente))


def admin_required(func):
    """Restringe un handler al administrador configurado en TELEGRAM_USER_ID."""

    @wraps(func)
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        bot = context.bot_data["bot"]
        usuario = update.effective_user
        autorizado = bool(usuario) and str(usuario.id) == str(bot.config.USER_ID)
        if not autorizado:
            mensaje = "No tienes permiso para usar este comando."
            if update.callback_query:
                await update.callback_query.answer(mensaje, show_alert=True)
            elif update.effective_message:
                await update.effective_message.reply_text(mensaje)
            return None
        return await func(update, context)

    return wrapper


async def comando_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mensaje = (
        "👋 <b>¡Hola! Soy Deals Bot</b> 🛍️\n\n"
        "Cazo ofertas en varias fuentes y te aviso por mensaje directo cuando "
        "encuentro algo que coincide con tus palabras clave.\n\n"
        "<b>Comandos disponibles:</b>\n"
        "🔸 /alerta <code>&lt;palabra&gt;</code> — Crea una alerta (ej. <i>/alerta ssd</i>)\n"
        "🔸 /mis_alertas — Mira tus suscripciones\n"
        "🔸 /borrar_alerta <code>&lt;palabra&gt;</code> — Elimina una suscripción\n"
        "🔸 /borrar_mis_datos — Borra todas tus suscripciones\n"
        "🔸 /ayuda — Muestra este mensaje\n\n"
        "<i>Guardo tu id de chat y tus palabras clave solo para enviarte alertas. "
        "Puedes borrarlas cuando quieras con /borrar_mis_datos.</i>"
    )
    await update.message.reply_text(mensaje, parse_mode="HTML")


@admin_required
async def obtener_estado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot_data["bot"]
    db = bot.db_manager
    lineas = ["<b>Estado del bot</b>", "", "<b>Fuentes:</b>"]
    for nombre, info in bot.scrapers.items():
        estado = "habilitada" if info["enabled"] else "deshabilitada"
        error = bot._ultimos_errores_scrapers.get(nombre)
        sufijo = f" — último error: <code>{html.escape(str(error)[:120], quote=False)}</code>" if error else ""
        lineas.append(f"• <code>{html.escape(nombre)}</code>: {estado}{sufijo}")

    ultimo_ok = await db.get_ajuste("ultimo_ciclo_ok")
    ultimo_ts = await db.get_ajuste("ultimo_ciclo_ts")
    detalle = await db.get_ajuste("ultimo_ciclo_detalle", "")
    if ultimo_ok:
        lineas.append("")
        lineas.append("<b>Último ciclo correcto:</b>")
        lineas.append(
            f"<code>{html.escape(time_str(ultimo_ok))}</code> — "
            f"{html.escape(detalle or 'sin detalle')}"
        )
    elif ultimo_ts:
        lineas.append("")
        lineas.append(
            "<b>Último ciclo:</b> con error a las "
            f"<code>{html.escape(time_str(ultimo_ts))}</code>"
        )
    else:
        lineas.append("")
        lineas.append("<i>Todavía no se ha ejecutado ningún ciclo.</i>")

    stats = await db.estadisticas()
    lineas.append("")
    lineas.append("<b>Datos:</b>")
    lineas.append(
        f"Ofertas: {stats['ofertas']} · Suscripciones: {stats['suscripciones']} · "
        f"Pendientes: {stats['pendientes']} · Fallidas: {stats['fallidas']}"
    )
    await update.message.reply_text("\n".join(lineas), parse_mode="HTML")


@admin_required
async def diagnostico(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot_data["bot"]
    config = bot.config
    db = bot.db_manager
    stats = await db.estadisticas()
    ultimo_ok = await db.get_ajuste("ultimo_ciclo_ok")
    ultimo_error = await db.get_ajuste("ultimo_ciclo_detalle", "")

    imagenes = getattr(bot, "_imagen_stats", {})
    lineas = [
        "<b>Diagnóstico técnico</b>",
        "",
        f"IA configurada: <b>{'sí' if config.has_ai() else 'no'}</b>",
        f"Claves Gemini definidas: {len(config.GEMINI_API_KEYS.split(',')) if config.GEMINI_API_KEYS else 0} "
        f"+ principal {'sí' if config.GEMINI_API_KEY else 'no'} "
        f"+ respaldo {'sí' if config.GEMINI_API_KEY_BACKUP else 'no'}",
        f"Groq definido: <b>{'sí' if config.GROQ_API_KEY else 'no'}</b>",
        f"Modelos Gemini: <code>{html.escape(', '.join(config.gemini_models()))}</code>",
        f"Preferencia Gemini: <code>{html.escape(', '.join(config.gemini_model_preferidos()))}</code>",
        f"Timeout por llamada Gemini: {config.GEMINI_CALL_TIMEOUT_SECONDS}s",
        f"Modelo Groq: <code>{html.escape(config.GROQ_MODEL)}</code>",
        f"Gancho IA obligatorio: <b>{'sí' if config.AI_HOOK_REQUIRED else 'no'}</b>",
        f"Base de datos: <code>{html.escape(os.path.abspath(config.DATABASE))}</code>",
        f"Ofertas: {stats['ofertas']} · Suscripciones: {stats['suscripciones']}",
        f"Pendientes: {stats['pendientes']} · Fallidas: {stats['fallidas']}",
        "Imágenes: "
        f"URL {imagenes.get('url', 0)} · descargadas {imagenes.get('descargada', 0)} · "
        f"respaldo {imagenes.get('placeholder', 0)} · texto {imagenes.get('texto', 0)}",
        "",
        "<b>Fuentes:</b>",
    ]
    for nombre, info in bot.scrapers.items():
        lineas.append(f"• {html.escape(nombre)}: {'on' if info['enabled'] else 'off'}")
    descubiertos = modelos_gemini_descubiertos()
    if descubiertos:
        lineas.append("")
        lineas.append(
            "Modelos Gemini descubiertos: "
            f"<code>{html.escape(', '.join(descubiertos[:8]))}</code>"
        )
    if ultimo_ok:
        lineas.append("")
        lineas.append(
            f"Último ciclo correcto: <code>{html.escape(time_str(ultimo_ok))}</code>"
        )
    if ultimo_error:
        lineas.append(
            f"Último detalle: <code>{html.escape(str(ultimo_error)[:200])}</code>"
        )
    if bot._ultimos_errores_scrapers:
        lineas.append("")
        lineas.append("<b>Errores de scrapers:</b>")
        for nombre, error in bot._ultimos_errores_scrapers.items():
            lineas.append(
                f"• {html.escape(nombre)}: <code>{html.escape(str(error)[:120])}</code>"
            )

    estado = estado_ia()
    lineas.append("")
    lineas.append("<b>IA:</b>")
    lineas.append(
        f"Último proveedor: <code>{html.escape(str(estado['ultimo_proveedor'] or '—'))}</code>"
    )
    if estado["ultimo_error"]:
        lineas.append(
            f"Último error ({time_str(estado['ultimo_error_ts'])}): "
            f"<code>{html.escape(str(estado['ultimo_error_origen']))}: "
            f"{html.escape(str(estado['ultimo_error'])[:200])}</code>"
        )
    lineas.append(
        f"Éxitos: {estado['exitos']} · Fallos: {estado['fallos']}"
    )

    try:
        info = await bot.bot.get_webhook_info()
        lineas.append("")
        lineas.append("<b>Telegram:</b>")
        if info.url:
            lineas.append(f"Webhook: <code>{html.escape(info.url)}</code>")
            lineas.append(f"Updates pendientes: {info.pending_update_count}")
            if info.last_error_message:
                lineas.append(
                    "Último error del webhook: "
                    f"<code>{html.escape(str(info.last_error_message)[:200])}</code>"
                )
        else:
            lineas.append("Modo: polling (sin webhook)")
    except Exception as exc:  # noqa: BLE001
        lineas.append(
            f"Telegram: no se pudo consultar el webhook (<code>{html.escape(str(exc)[:120])}</code>)"
        )
    await update.message.reply_text("\n".join(lineas), parse_mode="HTML")


@admin_required
async def test_ia(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    """Prueba real de IA desde Telegram; muestra proveedor o el error exacto."""
    bot = context.bot_data["bot"]
    config = bot.config
    await update.message.reply_text("Probando IA, espera unos segundos…")
    inicio = time.monotonic()
    resultado = None
    try:
        resultado = await asyncio.wait_for(
            generar_gancho_ia(
                f"Prueba de conexión {int(time.time())}", "$10.00", "$20.00"
            ),
            timeout=config.AI_HOOK_TIMEOUT_SECONDS + 15,
        )
    except asyncio.TimeoutError:
        resultado = None

    estado = estado_ia()
    if resultado:
        lineas_resultado = [
            "✅ <b>IA funcionando</b>",
            f"Tiempo: {int((time.monotonic() - inicio) * 1000)} ms",
            f"Proveedor: <code>{html.escape(str(estado['ultimo_proveedor']))}</code>",
            f"Gancho: <i>{html.escape(resultado)}</i>",
        ]
        if estado["ultimo_error"]:
            lineas_resultado.append(
                "Último error previo: "
                f"<code>{html.escape(str(estado['ultimo_error_origen']))}: "
                f"{html.escape(str(estado['ultimo_error'])[:160])}</code>"
            )
        await update.message.reply_text(
            "\n".join(lineas_resultado), parse_mode="HTML"
        )
        return

    lineas = [
        "❌ <b>La IA no devolvió gancho</b>",
        f"IA configurada: {'sí' if config.has_ai() else 'no'}",
        f"Modelos: <code>{html.escape(', '.join(config.gemini_models()))}</code>",
        f"Groq: <code>{html.escape(config.GROQ_MODEL)}</code>",
    ]
    if estado["ultimo_error"]:
        lineas.append(
            "Origen: "
            f"<code>{html.escape(str(estado['ultimo_error_origen']))}</code>"
        )
        lineas.append(
            f"Error: <code>{html.escape(str(estado['ultimo_error'])[:300])}</code>"
        )
    await update.message.reply_text("\n".join(lineas), parse_mode="HTML")


def time_str(timestamp: str | int | None) -> str:
    try:
        import time as _time

        return _time.strftime("%Y-%m-%d %H:%M", _time.localtime(int(timestamp)))
    except (TypeError, ValueError, OSError):
        return "?"


async def _mostrar_fuentes(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot_data["bot"]
    if not bot.scrapers:
        await update.message.reply_text("No hay fuentes cargadas.")
        return
    filas = []
    for nombre, info in bot.scrapers.items():
        accion = "off" if info["enabled"] else "on"
        etiqueta = f"🔴 {nombre}" if info["enabled"] else f"🟢 {nombre}"
        filas.append(
            [
                InlineKeyboardButton(
                    f"{etiqueta} ({'desactivar' if accion == 'off' else 'activar'})",
                    callback_data=f"fuente:{accion}:{nombre}",
                )
            ]
        )
    await update.message.reply_text(
        "Selecciona una fuente para cambiar su estado:",
        reply_markup=InlineKeyboardMarkup(filas),
    )


@admin_required
async def habilitar_fuente(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _mostrar_fuentes(update, context)


@admin_required
async def deshabilitar_fuente(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    await _mostrar_fuentes(update, context)

@admin_required
async def manejar_callback_fuente(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    bot = context.bot_data["bot"]
    query = update.callback_query
    await query.answer()

    try:
        accion, nombre = query.data.split(":", 2)[1:]
    except (ValueError, AttributeError):
        await query.edit_message_text("Acción no válida.")
        return
    if accion not in ("on", "off") or nombre not in bot.scrapers:
        await query.edit_message_text("Acción o fuente no válida.")
        return

    habilitada = accion == "on"
    await bot._guardar_estado_fuente(nombre, habilitada)
    mensaje = f"Fuente {nombre} {'habilitada' if habilitada else 'deshabilitada'}."
    try:
        await query.edit_message_text(mensaje)
    except Exception:  # noqa: BLE001
        await context.bot.send_message(
            chat_id=query.message.chat_id, text=mensaje
        )


async def agregar_alerta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot_data["bot"]
    config = bot.config
    if update.effective_chat.type != "private":
        await update.message.reply_text(
            "Para crear alertas, escríbeme por privado y usa /alerta allí."
        )
        return
    if not context.args:
        await update.message.reply_text(
            "Uso: /alerta <palabra_clave>\nEjemplo: /alerta laptop"
        )
        return

    try:
        keyword = normalizar_keyword(
            " ".join(context.args),
            min_length=config.KEYWORD_MIN_LENGTH,
            max_length=config.KEYWORD_MAX_LENGTH,
        )
    except ValueError as exc:
        await update.message.reply_text(f"⚠️ {exc}")
        return

    user_id = str(update.effective_user.id)
    chat_id = str(update.effective_chat.id)
    total = await bot.db_manager.contar_suscripciones_usuario(user_id)
    if total >= config.MAX_ALERTAS_POR_USUARIO:
        await update.message.reply_text(
            f"⚠️ Ya tienes {total} alertas. El máximo es "
            f"{config.MAX_ALERTAS_POR_USUARIO}; borra alguna antes de crear otra."
        )
        return

    agregado = await bot.db_manager.agregar_suscripcion(user_id, chat_id, keyword)
    if agregado:
        await update.message.reply_text(
            f"✅ ¡Suscripción agregada! Te avisaré cuando encuentre ofertas para: "
            f"'{keyword}'"
        )
    else:
        await update.message.reply_text(
            f"⚠️ Ya estás suscrito a la palabra clave '{keyword}'."
        )


async def mis_alertas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot_data["bot"]
    user_id = str(update.effective_user.id)
    suscripciones = await bot.db_manager.obtener_suscripciones_por_usuario(user_id)
    if not suscripciones:
        await update.message.reply_text("No tienes ninguna alerta configurada.")
        return

    texto = "🔔 <b>Tus alertas activas:</b>\n\n"
    for keyword in suscripciones:
        texto += f"- <code>{html.escape(keyword, quote=False)}</code>\n"
    texto += (
        f"\n{len(suscripciones)}/{bot.config.MAX_ALERTAS_POR_USUARIO} alertas. "
        "Para borrar una: /borrar_alerta &lt;palabra&gt;"
    )
    await update.message.reply_text(texto, parse_mode="HTML")


async def borrar_alerta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot_data["bot"]
    if not context.args:
        await update.message.reply_text("Uso: /borrar_alerta <palabra_clave>")
        return

    try:
        keyword = normalizar_keyword(" ".join(context.args))
    except ValueError as exc:
        await update.message.reply_text(f"⚠️ {exc}")
        return

    user_id = str(update.effective_user.id)
    eliminado = await bot.db_manager.eliminar_suscripcion(user_id, keyword)
    if eliminado:
        await update.message.reply_text(f"🗑️ Alerta eliminada: '{keyword}'")
    else:
        await update.message.reply_text(
            f"❌ No se encontró ninguna alerta para '{keyword}'."
        )


async def borrar_mis_datos(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    bot = context.bot_data["bot"]
    user_id = str(update.effective_user.id)
    eliminadas = await bot.db_manager.eliminar_todas_suscripciones_usuario(user_id)
    await update.message.reply_text(
        f"🧹 Se eliminaron {eliminadas} suscripciones. No guardo más datos tuyos."
    )
