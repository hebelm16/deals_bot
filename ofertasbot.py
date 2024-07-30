import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, ContextTypes, CallbackQueryHandler

from config import Config
from db_manager import DBManager
from scraper import SlickdealsScraper, DealsnewsScraper
from telegram_bot import TelegramBot, setup_bot

class OfertasBot:
    def __init__(self):
        self.config = Config()
        self.db_manager = DBManager(self.config.DATABASE)
        self.db_manager.actualizar_estructura_db()
        self.db_manager.corregir_timestamps()
        self.fuentes = {
            'slickdeals': {'url': self.config.SLICKDEALS_URL, 'tag': "#Slickdeals", 'habilitado': True},
            'dealnews': {'url': self.config.DEALSNEWS_URL, 'tag': "#DealNews", 'habilitado': True}
        }
        self.scrapers = self.init_scrapers()
        self.application, self.telegram_bot = setup_bot(self.config.TOKEN, self.config.CHANNEL_ID)
        self.max_ofertas_por_ejecucion = 15  # Aumentado a 15 ofertas por ejecución

    def init_scrapers(self):
        scrapers = []
        for nombre, fuente in self.fuentes.items():
            if fuente['habilitado']:
                if nombre == 'slickdeals':
                    scrapers.append(SlickdealsScraper(fuente['url'], fuente['tag']))
                elif nombre == 'dealnews':
                    scrapers.append(DealsnewsScraper(fuente['url'], fuente['tag']))
        return scrapers

    async def check_ofertas(self) -> None:
        todas_las_ofertas = []
        for scraper in self.scrapers:
            try:
                logging.info(f"Iniciando scraping de {scraper.__class__.__name__}")
                ofertas = await asyncio.to_thread(scraper.obtener_ofertas)
                logging.info(f"Se obtuvieron {len(ofertas)} ofertas de {scraper.__class__.__name__}")
                todas_las_ofertas.extend(ofertas)
            except Exception as e:
                logging.error(f"Error al obtener ofertas de {scraper.__class__.__name__}: {e}", exc_info=True)
                await self.telegram_bot.enviar_notificacion_error(e)

        ofertas_enviadas = self.db_manager.cargar_ofertas_enviadas()
        nuevas_ofertas = self.db_manager.filtrar_nuevas_ofertas(todas_las_ofertas)
        
        logging.info(f"Se encontraron {len(nuevas_ofertas)} nuevas ofertas para enviar")
        
        ofertas_enviadas_esta_vez = 0
        for oferta in nuevas_ofertas[:self.max_ofertas_por_ejecucion]:
            try:
                logging.debug(f"Intentando enviar oferta: {oferta['titulo']}")
                await self.telegram_bot.enviar_oferta(oferta)
                self.db_manager.guardar_oferta(oferta)
                ofertas_enviadas_esta_vez += 1
                logging.info(f"Oferta enviada y guardada: {oferta['titulo']}")
            except Exception as e:
                logging.error(f"Error al enviar oferta individual: {e}", exc_info=True)

        self.db_manager.limpiar_ofertas_antiguas()
        logging.info(f"Se enviaron {ofertas_enviadas_esta_vez} nuevas ofertas.")

    async def run(self) -> None:
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()

        self.application.add_handler(CommandHandler("estado", self.obtener_estado))
        self.application.add_handler(CommandHandler("habilitar", self.habilitar_fuente))
        self.application.add_handler(CommandHandler("deshabilitar", self.deshabilitar_fuente))
        self.application.add_handler(CallbackQueryHandler(self.manejar_callback_fuente))

        while True:
            try:
                await self.check_ofertas()
                await asyncio.sleep(1800)  # Espera 30 minutos
            except Exception as e:
                logging.error(f"Se produjo un error en el ciclo principal: {e}", exc_info=True)
                await self.telegram_bot.enviar_notificacion_error(e)
                await asyncio.sleep(60)

    async def obtener_estado(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if str(update.effective_user.id) != self.config.USER_ID:
            await update.message.reply_text("No tienes permiso para usar este comando.")
            return

        estado = "Estado actual de las fuentes:\n"
        for nombre, fuente in self.fuentes.items():
            estado += f"{nombre}: {'Habilitada' if fuente['habilitado'] else 'Deshabilitada'}\n"
        await update.message.reply_text(estado)

    async def habilitar_fuente(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if str(update.effective_user.id) != self.config.USER_ID:
            await update.message.reply_text("No tienes permiso para usar este comando.")
            return

        keyboard = [[InlineKeyboardButton(nombre, callback_data=f"habilitar_{nombre}") for nombre in self.fuentes.keys()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Selecciona la fuente a habilitar:", reply_markup=reply_markup)

    async def deshabilitar_fuente(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        if str(update.effective_user.id) != self.config.USER_ID:
            await update.message.reply_text("No tienes permiso para usar este comando.")
            return

        keyboard = [[InlineKeyboardButton(nombre, callback_data=f"deshabilitar_{nombre}") for nombre in self.fuentes.keys()]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text("Selecciona la fuente a deshabilitar:", reply_markup=reply_markup)

    async def manejar_callback_fuente(self, update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
        query = update.callback_query
        await query.answer()

        accion, nombre_fuente = query.data.split('_')
        if accion == 'habilitar':
            self.fuentes[nombre_fuente]['habilitado'] = True
            mensaje = f"Fuente {nombre_fuente} habilitada."
        else:
            self.fuentes[nombre_fuente]['habilitado'] = False
            mensaje = f"Fuente {nombre_fuente} deshabilitada."

        self.scrapers = self.init_scrapers()
        
        try:
            await query.edit_message_text(text=mensaje)
        except telegram.error.BadRequest as e:
            if "There is no text in the message to edit" in str(e):
                await context.bot.send_message(chat_id=query.message.chat_id, text=mensaje)
            else:
                logging.error(f"Error al editar mensaje: {e}")
