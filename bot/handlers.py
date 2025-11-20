from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes, CommandHandler, CallbackQueryHandler


def setup_handlers(application, bot):
    application.add_handler(CommandHandler("estado", obtener_estado))
    application.add_handler(CommandHandler("habilitar", habilitar_fuente))
    application.add_handler(CommandHandler("deshabilitar", deshabilitar_fuente))
    application.add_handler(CallbackQueryHandler(manejar_callback_fuente))


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
