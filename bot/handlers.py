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
    generar_publicacion_ia,
    limpiar_cache_ia,
    modelos_gemini_descubiertos,
)
from utils.keywords import normalizar_keyword


def setup_handlers(application, bot) -> None:
    application.add_handler(CommandHandler("start", comando_ayuda))
    application.add_handler(CommandHandler("ayuda", comando_ayuda))
    application.add_handler(CommandHandler("estado", obtener_estado))
    application.add_handler(CommandHandler("stats", comando_stats))
    application.add_handler(CommandHandler("diagnostico", diagnostico))
    application.add_handler(CommandHandler("test_ia", test_ia))
    application.add_handler(CommandHandler("habilitar", habilitar_fuente))
    application.add_handler(CommandHandler("deshabilitar", deshabilitar_fuente))
    application.add_handler(CommandHandler("evento", comando_evento))
    application.add_handler(CommandHandler("alerta", agregar_alerta))
    application.add_handler(CommandHandler("mis_alertas", mis_alertas))
    application.add_handler(CommandHandler("borrar_alerta", borrar_alerta))
    application.add_handler(CommandHandler("borrar_mis_datos", borrar_mis_datos))
    application.add_handler(
        CallbackQueryHandler(manejar_callback_fuente, pattern=r"^fuente:")
    )
    application.add_handler(
        CallbackQueryHandler(manejar_callback_evento, pattern=r"^evento:")
    )


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
        f"Pendientes: {stats['pendientes']} · Fallidas: {stats['fallidas']} · "
        f"Duplicadas: {stats.get('duplicadas', 0)} · "
        f"Excluidas: {stats.get('excluidas', 0)} · "
        f"Cola: {stats.get('cola', 0)}"
    )
    if hasattr(bot, "evento"):
        res_ev = bot.evento.resumen()
        if res_ev["activo"]:
            lineas.append("")
            lineas.append(
                f"<b>Modo evento:</b> {html.escape(res_ev['etiqueta'])} "
                f"(hasta <code>{html.escape(time_str(res_ev['fin_ts']))}</code> · "
                f"pub {res_ev['pub_usadas_hoy']}/{res_ev['pub_max_dia']} · "
                f"IA {res_ev['ia_usadas_hoy']}/{res_ev['ia_max_dia']})"
            )
    await update.message.reply_text("\n".join(lineas), parse_mode="HTML")


@admin_required
async def comando_stats(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot_data["bot"]
    db = bot.db_manager

    stats = await db.estadisticas()
    por_fuente = await db.contar_por_fuente("enviada")
    ventana = await db.contar_ventana(24)
    top = await db.top_ofertas_descuento(5, dias=7)
    publicadas = sum(por_fuente.values())

    lineas = ["📊 <b>Estadísticas</b>", ""]
    lineas.append(
        f"Publicadas: <b>{publicadas}</b> · "
        f"En cola: <b>{stats.get('cola', 0)}</b> · "
        f"Suscripciones: <b>{stats.get('suscripciones', 0)}</b>"
    )
    lineas.append(
        f"Total en base: {stats.get('ofertas', 0)} · "
        f"Duplicadas: {stats.get('duplicadas', 0)} · "
        f"Excluidas: {stats.get('excluidas', 0)} · "
        f"Fallidas: {stats.get('fallidas', 0)} · "
        f"Caducadas: {stats.get('expiradas', 0)}"
    )

    if por_fuente:
        lineas.append("")
        lineas.append("<b>Publicadas por fuente:</b>")
        for fuente, total in list(por_fuente.items())[:8]:
            lineas.append(f"• <code>{html.escape(fuente)}</code>: {total}")

    lineas.append("")
    lineas.append("<b>Últimas 24 h:</b>")
    lineas.append(
        f"Enviadas {ventana.get('enviada', 0)} · "
        f"Duplicadas {ventana.get('duplicada', 0)} · "
        f"Excluidas {ventana.get('excluida', 0)} · "
        f"Fallidas {ventana.get('fallida', 0)}"
    )

    if top:
        lineas.append("")
        lineas.append("<b>🔥 Mayores descuentos (7 días):</b>")
        for posicion, oferta in enumerate(top, start=1):
            titulo = html.escape((oferta["titulo"] or "")[:70], quote=False)
            precios = html.escape(
                f"{oferta['precio']} / antes {oferta['precio_original']}", quote=False
            )
            lineas.append(
                f"{posicion}. <b>{oferta['descuento']:.0f}%</b> — {titulo} "
                f"<code>{precios}</code>"
            )

    lineas.append("")
    if hasattr(bot, "evento"):
        resumen = bot.evento.resumen()
        if resumen["activo"]:
            lineas.append(
                f"<b>Modo evento:</b> activo ({html.escape(resumen['etiqueta'])}) · "
                f"hoy {resumen['pub_usadas_hoy']}/{resumen['pub_max_dia']} publicaciones · "
                f"IA {resumen['ia_usadas_hoy']}/{resumen['ia_max_dia']}"
            )
        else:
            lineas.append("<b>Modo evento:</b> inactivo")

    estado = estado_ia()
    if estado.get("exitos") or estado.get("fallos"):
        lineas.append(
            f"IA: {estado.get('exitos', 0)} OK · {estado.get('fallos', 0)} fallos · "
            f"último proveedor "
            f"<code>{html.escape(str(estado.get('ultimo_proveedor') or 'n/a'))}</code>"
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
        f"Pendientes: {stats['pendientes']} · Fallidas: {stats['fallidas']} · "
        f"Duplicadas: {stats.get('duplicadas', 0)} · "
        f"Excluidas: {stats.get('excluidas', 0)} · "
        f"Cola: {stats.get('cola', 0)}",
        "Imágenes: "
        f"URL {imagenes.get('url', 0)} · descargadas {imagenes.get('descargada', 0)} · "
        f"respaldo {imagenes.get('placeholder', 0)} · texto {imagenes.get('texto', 0)}",
        _linea_diagnostico_evento(bot),
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
    limpiar_cache_ia()  # que la prueba llame de verdad a la IA
    try:
        resultado = await asyncio.wait_for(
            generar_publicacion_ia(
                "Sony WH-1000XM5 Wireless Noise Cancelling Headphones $248.00",
                "$248.00",
                "$399.99",
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
            f"Título: <code>{html.escape(resultado.titulo_es or '(sin traducir)')}</code>",
            f"Gancho: <i>{html.escape(resultado.gancho)}</i>",
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


def _formatear_restante(segundos: int) -> str:
    if segundos < 60:
        return "&lt;1m"
    minutos = segundos // 60
    horas, mins = divmod(minutos, 60)
    if horas:
        return f"{horas}h {mins}m"
    return f"{mins}m"


def _linea_diagnostico_evento(bot) -> str:
    if not hasattr(bot, "evento"):
        return "Modo evento: no disponible"
    res = bot.evento.resumen()
    mins = max(1, res["intervalo_segundos"] // 60)
    if res["activo"]:
        return (
            f"Modo evento: <b>activo</b> ({html.escape(res['etiqueta'])}, "
            f"cada {mins} min, pub {res['pub_usadas_hoy']}/{res['pub_max_dia']}, "
            f"IA {res['ia_usadas_hoy']}/{res['ia_max_dia']})"
        )
    return f"Modo evento: inactivo (ciclo cada {mins} min)"


def _panel_evento(bot) -> tuple[str, InlineKeyboardMarkup]:
    res = bot.evento.resumen()
    mins = max(1, res["intervalo_segundos"] // 60)
    if res["activo"]:
        texto = (
            "🔥 <b>Modo evento activo</b>\n\n"
            f"Evento: <code>{html.escape(res['nombre'])}</code> "
            f"({html.escape(res['etiqueta'])})\n"
            f"Termina: <code>{html.escape(time_str(res['fin_ts']))}</code> "
            f"(quedan {_formatear_restante(res['restante_segundos'])})\n"
            f"Ciclo: cada {mins} min · máx {res['max_por_ciclo']}/ciclo\n"
            f"Hoy: {res['pub_usadas_hoy']}/{res['pub_max_dia']} publicaciones · "
            f"{res['ia_usadas_hoy']}/{res['ia_max_dia']} llamadas IA"
        )
        teclado = InlineKeyboardMarkup(
            [
                [
                    InlineKeyboardButton("🔄 Extender +24h", callback_data="evento:extender:24"),
                    InlineKeyboardButton("🛑 Desactivar", callback_data="evento:off"),
                ],
                [InlineKeyboardButton("↻ Actualizar", callback_data="evento:estado")],
            ]
        )
        return texto, teclado

    texto = (
        "⏸️ <b>Modo evento inactivo</b>\n\n"
        f"Ciclo normal: cada {mins} min · máx {res['max_por_ciclo']} ofertas/ciclo\n"
        f"Hoy (evento): {res['pub_usadas_hoy']}/{res['pub_max_dia']} publicaciones · "
        f"{res['ia_usadas_hoy']}/{res['ia_max_dia']} llamadas IA\n\n"
        "<b>Uso rápido:</b>\n"
        "<code>/evento black_friday 72</code>\n"
        "<code>/evento prime_day 48</code>\n"
        "<code>/evento off</code>"
    )
    teclado = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton(
                    "🔥 Black Friday (72h)", callback_data="evento:on:black_friday:72"
                )
            ],
            [
                InlineKeyboardButton(
                    "📦 Prime Day (48h)", callback_data="evento:on:prime_day:48"
                ),
                InlineKeyboardButton(
                    "⚡ Cyber Monday (24h)", callback_data="evento:on:cyber_monday:24"
                ),
            ],
        ]
    )
    return texto, teclado


@admin_required
async def comando_evento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot_data["bot"]
    await bot.evento.verificar_expiracion()
    args = context.args or []

    if not args:
        texto, teclado = _panel_evento(bot)
        await update.message.reply_text(
            texto, parse_mode="HTML", reply_markup=teclado
        )
        return

    if args[0].lower() in ("off", "stop", "desactivar", "apagar"):
        nombre = await bot.evento.desactivar()
        if nombre:
            bot.reprogramar_ciclo(ejecutar_pronto=False)
            mins = max(1, bot.intervalo_ciclo_actual() // 60)
            await update.message.reply_text(
                f"🛑 Modo evento <b>{html.escape(nombre)}</b> desactivado.\n"
                f"Ciclo normal restaurado (cada {mins} min).",
                parse_mode="HTML",
            )
        else:
            await update.message.reply_text("El modo evento ya estaba inactivo.")
        return

    nombre = args[0]
    if len(args) >= 2:
        try:
            horas = int(args[1])
        except ValueError:
            await update.message.reply_text(
                "Uso: <code>/evento &lt;nombre&gt; [horas]</code> o <code>/evento off</code>\n"
                "Ejemplo: <code>/evento black_friday 72</code>",
                parse_mode="HTML",
            )
            return
    else:
        horas = int(getattr(bot.config, "EVENTO_HORAS_DEFECTO", 72))

    try:
        await bot.evento.activar(nombre, horas)
    except ValueError as exc:
        await update.message.reply_text(f"⚠️ {exc}")
        return

    bot.reprogramar_ciclo(ejecutar_pronto=True)
    texto, teclado = _panel_evento(bot)
    await update.message.reply_text(
        f"✅ <b>Modo evento activado</b> (primera revisión en segundos)\n\n{texto}",
        parse_mode="HTML",
        reply_markup=teclado,
    )


@admin_required
async def manejar_callback_evento(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    bot = context.bot_data["bot"]
    query = update.callback_query
    await query.answer()

    partes = (query.data or "").split(":")
    accion = partes[1] if len(partes) > 1 else ""
    prefijo = ""

    if accion == "on" and len(partes) >= 4:
        try:
            horas = int(partes[3])
            await bot.evento.activar(partes[2], horas)
            bot.reprogramar_ciclo(ejecutar_pronto=True)
            prefijo = "✅ <b>Modo evento activado</b> (primera revisión en segundos)\n\n"
        except ValueError as exc:
            prefijo = f"⚠️ {html.escape(str(exc))}\n\n"
    elif accion == "extender" and len(partes) >= 3:
        try:
            horas = int(partes[2])
            extendido = await bot.evento.extender(horas)
            if extendido:
                prefijo = f"🔄 <b>Evento extendido +{horas}h</b>\n\n"
            else:
                prefijo = "ℹ️ El evento ya había finalizado.\n\n"
        except ValueError as exc:
            prefijo = f"⚠️ {html.escape(str(exc))}\n\n"
    elif accion == "off":
        nombre = await bot.evento.desactivar()
        if nombre:
            bot.reprogramar_ciclo(ejecutar_pronto=False)
            prefijo = f"🛑 <b>Modo {html.escape(nombre)} desactivado</b>\n\n"
        else:
            prefijo = "ℹ️ El modo evento ya estaba inactivo.\n\n"
    elif accion == "estado":
        await bot.evento.verificar_expiracion()
    else:
        await query.edit_message_text("Acción de evento no válida.")
        return

    texto, teclado = _panel_evento(bot)
    mensaje = f"{prefijo}{texto}"
    try:
        await query.edit_message_text(
            mensaje, parse_mode="HTML", reply_markup=teclado
        )
    except Exception:  # noqa: BLE001
        await context.bot.send_message(
            chat_id=query.message.chat_id,
            text=mensaje,
            parse_mode="HTML",
            reply_markup=teclado,
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
