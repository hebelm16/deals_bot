from telegram import Bot, InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import Application, CallbackContext, CallbackQueryHandler
from typing import Dict, Any
import logging
from retrying import retry

class TelegramBot:
    def __init__(self, token: str, channel_id: str):
        self.bot = Bot(token)
        self.channel_id = channel_id

    @retry(stop_max_attempt_number=3, wait_fixed=5000)
    async def enviar_oferta(self, oferta: Dict[str, Any]) -> None:
        titulo_palabras = oferta['titulo'].split()
        titulo_palabras[0] = titulo_palabras[0].capitalize()
        titulo_formateado = ' '.join(titulo_palabras)
        titulo_formateado = f"*{titulo_formateado}*"

        mensaje = f"{oferta['tag']} 🎉 ¡Nueva oferta! 🎉\n\n"
        mensaje += f"📌 {titulo_formateado}\n\n"
        mensaje += f"💵 Precio: {oferta['precio']}\n"
        if oferta.get('precio_original'):
            mensaje += f"💰 Precio original: {oferta['precio_original']}\n"
        
        keyboard = None
        if oferta.get('info_cupon'):
            mensaje += f"\nℹ️ Info: {oferta['info_cupon']}"
            if oferta.get('cupon'):
                keyboard = InlineKeyboardMarkup([[InlineKeyboardButton("Copiar Cupón", callback_data=f"copiar_cupon:{oferta['cupon']}")]])
        
        mensaje += f"\n\n🔗 Link: {oferta['link']}\n"
        
        try:
            logging.info(f"Intentando enviar oferta al canal: {self.channel_id}")
            if oferta['imagen'] != 'No disponible':
                await self.bot.send_photo(chat_id=self.channel_id, photo=oferta['imagen'], caption=mensaje, parse_mode='Markdown', reply_markup=keyboard)
            else:
                await self.bot.send_message(chat_id=self.channel_id, text=mensaje, parse_mode='Markdown', reply_markup=keyboard)
            logging.info("Oferta enviada con éxito")
        except Exception as e:
            logging.error(f"Error al enviar oferta: {e}", exc_info=True)
            raise

    async def enviar_notificacion_error(self, error: Exception) -> None:
        mensaje = f"🚨 *Error en el bot de ofertas* 🚨\n\n"
        mensaje += f"Detalles del error:\n"
        mensaje += f"`{type(error).__name__}`: `{str(error)}`"
        try:
            await self.bot.send_message(chat_id=self.channel_id, text=mensaje, parse_mode='Markdown')
        except Exception as e:
            logging.error(f"No se pudo enviar notificación de error: {e}", exc_info=True)

    async def manejar_callback_cupon(self, update: Update, context: CallbackContext) -> None:
        query = update.callback_query
        await query.answer()
        
        _, cupon = query.data.split(':')
        mensaje = f"Aquí está tu cupón:\n\n`{cupon}`\n\nPuedes copiar fácilmente el código seleccionándolo."
        
        await query.edit_message_text(text=mensaje, parse_mode='Markdown')

def setup_bot(token: str, channel_id: str) -> Application:
    application = Application.builder().token(token).build()
    bot = TelegramBot(token, channel_id)
    application.add_handler(CallbackQueryHandler(bot.manejar_callback_cupon, pattern='^copiar_cupon:'))
    return application, bot
