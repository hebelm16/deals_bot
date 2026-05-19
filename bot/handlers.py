from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler


def setup_handlers(application, bot):
    application.add_handler(CommandHandler("start", comando_ayuda))
    application.add_handler(CommandHandler("ayuda", comando_ayuda))
    application.add_handler(CommandHandler("estado", obtener_estado))
    application.add_handler(CommandHandler("habilitar", habilitar_fuente))
    application.add_handler(CommandHandler("deshabilitar", deshabilitar_fuente))
    application.add_handler(CommandHandler("alerta", agregar_alerta))
    application.add_handler(CommandHandler("mis_alertas", mis_alertas))
    application.add_handler(CommandHandler("borrar_alerta", borrar_alerta))
    application.add_handler(CallbackQueryHandler(manejar_callback_fuente))


async def comando_ayuda(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    mensaje = (
        "👋 <b>¡Hola! Soy Deals Bot</b> 🛍️\n\n"
        "Te ayudo a cazar las mejores ofertas. Puedes suscribirte a palabras clave "
        "y te avisaré por mensaje directo apenas encuentre algo que coincida.\n\n"
        "<b>Comandos disponibles:</b>\n"
        "🔸 /alerta <code>&lt;palabra&gt;</code> - Crea una nueva alerta (ej. <i>/alerta ssd</i>)\n"
        "🔸 /mis_alertas - Mira a qué estás suscrito\n"
        "🔸 /borrar_alerta <code>&lt;palabra&gt;</code> - Elimina una suscripción\n"
        "🔸 /ayuda - Muestra este mensaje\n"
    )
    await update.message.reply_text(mensaje, parse_mode="HTML")

async def obtener_estado(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot_data["bot"]
    if str(update.effective_user.id) != bot.config.USER_ID:
        await update.message.reply_text("No tienes permiso para usar este comando.")
        return

    estado = "Estado actual de las fuentes:\n"
    for nombre, scraper_info in bot.scrapers.items():
        estado += (
            f"{nombre}: {'Habilitada' if scraper_info['enabled'] else 'Deshabilitada'}\n"
        )
    await update.message.reply_text(estado)


async def habilitar_fuente(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot_data["bot"]
    if str(update.effective_user.id) != bot.config.USER_ID:
        await update.message.reply_text("No tienes permiso para usar este comando.")
        return

    keyboard = [
        [
            InlineKeyboardButton(nombre, callback_data=f"habilitar_{nombre}")
            for nombre in bot.scrapers.keys()
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Selecciona la fuente a habilitar:", reply_markup=reply_markup
    )


async def deshabilitar_fuente(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    bot = context.bot_data["bot"]
    if str(update.effective_user.id) != bot.config.USER_ID:
        await update.message.reply_text("No tienes permiso para usar este comando.")
        return

    keyboard = [
        [
            InlineKeyboardButton(nombre, callback_data=f"deshabilitar_{nombre}")
            for nombre in bot.scrapers.keys()
        ]
    ]
    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "Selecciona la fuente a deshabilitar:", reply_markup=reply_markup
    )


async def manejar_callback_fuente(
    update: Update, context: ContextTypes.DEFAULT_TYPE
) -> None:
    bot = context.bot_data["bot"]
    query = update.callback_query
    await query.answer()

    accion, nombre_fuente = query.data.split("_")
    if accion == "habilitar":
        bot.scrapers[nombre_fuente]["enabled"] = True
        mensaje = f"Fuente {nombre_fuente} habilitada."
    else:
        bot.scrapers[nombre_fuente]["enabled"] = False
        mensaje = f"Fuente {nombre_fuente} deshabilitada."

    try:
        await query.edit_message_text(text=mensaje)
    except Exception as e:
        bot.logger.error(f"Error al editar mensaje: {e}")
        await context.bot.send_message(chat_id=query.message.chat_id, text=mensaje)

async def agregar_alerta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot_data["bot"]
    # Si quieres restringir alertas solo a ti, descomenta:
    # if str(update.effective_user.id) != bot.config.USER_ID:
    #     await update.message.reply_text("No tienes permiso.")
    #     return

    if not context.args:
        await update.message.reply_text("Uso: /alerta <palabra_clave>\nEjemplo: /alerta laptop")
        return

    keyword = " ".join(context.args).strip()
    user_id = str(update.effective_user.id)
    chat_id = str(update.effective_chat.id)

    agregado = await bot.db_manager.agregar_suscripcion(user_id, chat_id, keyword)
    if agregado:
        await update.message.reply_text(f"✅ ¡Suscripción agregada! Te avisaré cuando encuentre ofertas para: '{keyword}'")
    else:
        await update.message.reply_text(f"⚠️ Ya estás suscrito a la palabra clave '{keyword}'.")

async def mis_alertas(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot_data["bot"]
    user_id = str(update.effective_user.id)
    suscripciones = await bot.db_manager.obtener_suscripciones_por_usuario(user_id)
    
    if not suscripciones:
        await update.message.reply_text("No tienes ninguna alerta configurada.")
        return
    
    texto = "🔔 <b>Tus alertas activas:</b>\n\n"
    for s in suscripciones:
        texto += f"- <code>{s}</code>\n"
    texto += "\nPara borrar una, usa: /borrar_alerta &lt;palabra&gt;"
    
    await update.message.reply_text(texto, parse_mode="HTML")

async def borrar_alerta(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot_data["bot"]
    if not context.args:
        await update.message.reply_text("Uso: /borrar_alerta <palabra_clave>")
        return

    keyword = " ".join(context.args).strip()
    user_id = str(update.effective_user.id)

    eliminado = await bot.db_manager.eliminar_suscripcion(user_id, keyword)
    if eliminado:
        await update.message.reply_text(f"🗑️ Alerta eliminada: '{keyword}'")
    else:
        await update.message.reply_text(f"❌ No se encontró ninguna alerta para '{keyword}'.")
