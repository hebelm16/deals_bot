import time

from telegram import Update
from telegram.ext import ContextTypes

from bot.admin import admin_required
from utils.events import _estado_evento, activar_evento, desactivar_evento, esta_activo


@admin_required
async def comando_evento(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    bot = context.bot_data["bot"]
    args = context.args
    if not args:
        if esta_activo():
            await update.message.reply_text(f"Modo {_estado_evento.nombre} activo. Fin: {time.strftime('%Y-%m-%d %H:%M', time.localtime(_estado_evento.fin_ts))}")
        else:
            await update.message.reply_text("Modo evento inactivo.")
        return

    if args[0] == "off":
        await desactivar_evento(bot.db_manager)
        await update.message.reply_text("Modo evento desactivado.")
        return

    try:
        nombre = args[0]
        horas = int(args[1])
        await activar_evento(bot.db_manager, nombre, horas)
        await update.message.reply_text(f"Modo {nombre} activado por {horas} horas.")
    except (IndexError, ValueError):
        await update.message.reply_text("Uso: /evento <nombre> <horas> o /evento off")

