import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any
import signal
import hashlib
import time
from collections import deque

from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, ContextTypes, CallbackQueryHandler, CommandHandler

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
            'dealnews': {'url': self.config.DEALSNEWS_URL, 'tag': "#DealNews", 'habilitado': True},
            'slickdeals': {'url': self.config.SLICKDEALS_URL, 'tag': "#Slickdeals", 'habilitado': True}
        }
        self.scrapers = self.init_scrapers()
        self.application, self.telegram_bot = setup_bot(self.config.TOKEN, self.config.CHANNEL_ID)
        self.max_ofertas_por_ejecucion = 15
        self.is_running = True
        self.cooldowns = {
            'dealnews': 24 * 3600,  # 1 día para DealNews
            'slickdeals': 7 * 24 * 3600  # 7 días para Slickdeals
        }
        self.ofertas_recientes = deque(maxlen=1000)  # Mantiene las últimas 1000 ofertas

    def init_scrapers(self):
        scrapers = []
        for nombre, fuente in self.fuentes.items():
            if fuente['habilitado']:
                if nombre == 'dealnews':
                    scrapers.append(DealsnewsScraper(fuente['url'], fuente['tag']))
                elif nombre == 'slickdeals':
                    scrapers.append(SlickdealsScraper(fuente['url'], fuente['tag']))
        return scrapers

    def generar_id_oferta(self, oferta: Dict[str, Any]) -> str:
        campos = [
            oferta['titulo'],
            oferta['precio'],
            oferta['link'],
            oferta.get('precio_original', '') or '',
            oferta.get('imagen', '') or '',
            str(int(time.time()) // (24 * 3600))  # Día actual
        ]
        return hashlib.md5('|'.join(str(campo) for campo in campos if campo is not None).encode()).hexdigest()

    def son_ofertas_similares(self, oferta1: Dict[str, Any], oferta2: Dict[str, Any]) -> bool:
        return (
            oferta1['titulo'].lower() == oferta2['titulo'].lower() and
            oferta1['precio'] == oferta2['precio'] and
            oferta1['link'] == oferta2['link']
        )

    def es_oferta_reciente(self, oferta: Dict[str, Any]) -> bool:
        return any(self.son_ofertas_similares(oferta, oferta_reciente) for oferta_reciente in self.ofertas_recientes)

    def calcular_puntuacion_oferta(self, oferta: Dict[str, Any]) -> float:
        puntuacion = 0
        if oferta['precio_original'] and oferta['precio']:
            try:
                precio_original = float(oferta['precio_original'].replace('$', '').replace(',', ''))
                precio_actual = float(oferta['precio'].replace('$', '').replace(',', ''))
                descuento = (precio_original - precio_actual) / precio_original
                puntuacion += descuento * 100  # Mayor descuento, mayor puntuación
            except ValueError:
                pass
        
        if 'cupon' in oferta and oferta['cupon']:
            puntuacion += 20  # Bonus por tener cupón
        
        # Penalización por ofertas similares recientes
        if self.es_oferta_reciente(oferta):
            puntuacion -= 50

        return puntuacion

    async def check_ofertas(self) -> None:
        todas_las_ofertas = []
        ofertas_por_fuente = {}
        
        for scraper in self.scrapers:
            try:
                logging.info(f"Iniciando scraping de {scraper.__class__.__name__}")
                ofertas = await asyncio.to_thread(scraper.obtener_ofertas)
                logging.info(f"Se obtuvieron {len(ofertas)} ofertas de {scraper.__class__.__name__}")
                
                # Logging detallado de las ofertas obtenidas
                for oferta in ofertas:
                    logging.debug(f"Oferta obtenida de {scraper.__class__.__name__}: {oferta}")
                
                # Filtrar ofertas inválidas
                ofertas_validas = []
                for oferta in ofertas:
                    if all(oferta.get(campo) for campo in ['titulo', 'precio', 'link']):
                        ofertas_validas.append(oferta)
                    else:
                        logging.warning(f"Oferta inválida ignorada de {scraper.__class__.__name__}: {oferta}")
                
                todas_las_ofertas.extend(ofertas_validas)
                ofertas_por_fuente[scraper.__class__.__name__] = len(ofertas_validas)
            except Exception as e:
                logging.error(f"Error al obtener ofertas de {scraper.__class__.__name__}: {e}", exc_info=True)
                await self.telegram_bot.enviar_notificacion_error(e)

        logging.info(f"Total de ofertas obtenidas: {len(todas_las_ofertas)}")
        for fuente, cantidad in ofertas_por_fuente.items():
            logging.info(f"  - {fuente}: {cantidad} ofertas")

        nuevas_ofertas = self.filtrar_nuevas_ofertas(todas_las_ofertas)
        
        logging.info(f"Se encontraron {len(nuevas_ofertas)} nuevas ofertas para enviar")
        logging.info(f"Se ignoraron {len(todas_las_ofertas) - len(nuevas_ofertas)} ofertas ya enviadas anteriormente")
        
        ofertas_con_puntuacion = [(oferta, self.calcular_puntuacion_oferta(oferta)) for oferta in nuevas_ofertas]
        ofertas_con_puntuacion.sort(key=lambda x: x[1], reverse=True)
        
        ofertas_enviadas_esta_vez = 0
        ofertas_enviadas_por_fuente = {}
        
        for oferta, puntuacion in ofertas_con_puntuacion[:self.max_ofertas_por_ejecucion]:
            if puntuacion > 30:  # Umbral de puntuación
                try:
                    logging.debug(f"Intentando enviar oferta: {oferta['titulo']} (Puntuación: {puntuacion})")
                    await self.telegram_bot.enviar_oferta(oferta)
                    self.db_manager.guardar_oferta(oferta)
                    self.ofertas_recientes.append(oferta)
                    ofertas_enviadas_esta_vez += 1
                    
                    fuente = oferta['tag']
                    ofertas_enviadas_por_fuente[fuente] = ofertas_enviadas_por_fuente.get(fuente, 0) + 1
                    
                    logging.info(f"Oferta enviada y guardada: {oferta['titulo']} - Fuente: {oferta['tag']} (Puntuación: {puntuacion})")
                except Exception as e:
                    logging.error(f"Error al enviar oferta individual: {e}", exc_info=True)
            else:
                logging.debug(f"Oferta ignorada por baja puntuación ({puntuacion}): {oferta['titulo']}")

        ofertas_antiguas_eliminadas = self.db_manager.limpiar_ofertas_antiguas()
        
        logging.info(f"Resumen de ejecución:")
        logging.info(f"  - Total de ofertas obtenidas: {len(todas_las_ofertas)}")
        logging.info(f"  - Nuevas ofertas encontradas: {len(nuevas_ofertas)}")
        logging.info(f"  - Ofertas enviadas en esta ejecución: {ofertas_enviadas_esta_vez}")
        logging.info(f"  - Ofertas ignoradas (ya enviadas anteriormente): {len(todas_las_ofertas) - len(nuevas_ofertas)}")
        logging.info(f"  - Ofertas no enviadas por límite de ejecución o baja puntuación: {len(nuevas_ofertas) - ofertas_enviadas_esta_vez}")
        
        logging.info("Ofertas enviadas por fuente:")
        for fuente, cantidad in ofertas_enviadas_por_fuente.items():
            logging.info(f"  - {fuente}: {cantidad}")

        logging.info(f"Se eliminaron {ofertas_antiguas_eliminadas} ofertas antiguas de la base de datos")

    def filtrar_nuevas_ofertas(self, ofertas: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        nuevas_ofertas = []
        tiempo_actual = time.time()
        ofertas_enviadas = self.db_manager.cargar_ofertas_enviadas()
        
        for oferta in ofertas:
            oferta_id = self.generar_id_oferta(oferta)
            oferta['id'] = oferta_id
            if oferta_id in ofertas_enviadas:
                tiempo_ultima_vez = ofertas_enviadas[oferta_id].get('timestamp')
                if tiempo_ultima_vez is not None:
                    try:
                        tiempo_ultima_vez = float(tiempo_ultima_vez)
                        cooldown = self.cooldowns.get(oferta['tag'], 24 * 3600)
                        if tiempo_actual - tiempo_ultima_vez < cooldown:
                            logging.debug(f"Oferta {oferta_id} ignorada: enviada hace menos de {cooldown/3600} horas")
                            continue
                    except ValueError:
                        logging.warning(f"Timestamp inválido para la oferta {oferta_id}: {tiempo_ultima_vez}")
            
            if not any(self.son_ofertas_similares(oferta, nueva_oferta) for nueva_oferta in nuevas_ofertas):
                nuevas_ofertas.append(oferta)
            else:
                logging.debug(f"Oferta similar ignorada: {oferta['titulo']} - Fuente: {oferta['tag']}")
        
        return nuevas_ofertas

    async def run(self) -> None:
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()

        self.application.add_handler(CommandHandler("estado", self.obtener_estado))
        self.application.add_handler(CommandHandler("habilitar", self.habilitar_fuente))
        self.application.add_handler(CommandHandler("deshabilitar", self.deshabilitar_fuente))
        self.application.add_handler(CallbackQueryHandler(self.manejar_callback_fuente))

        while self.is_running:
            try:
                await self.check_ofertas()
                await asyncio.sleep(1800)  # Espera 30 minutos
            except asyncio.CancelledError:
                logging.info("Tarea cancelada, finalizando el bot.")
                break
            except Exception as e:
                logging.error(f"Se produjo un error en el ciclo principal: {e}", exc_info=True)
                await self.telegram_bot.enviar_notificacion_error(e)
                await asyncio.sleep(60)

        await self.application.stop()
        await self.application.shutdown()

    async def stop(self):
        self.is_running = False
        await self.application.stop()
        await self.application.shutdown()

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
        except Exception as e:
            logging.error(f"Error al editar mensaje: {e}")
            await context.bot.send_message(chat_id=query.message.chat_id, text=mensaje)

def main():
    bot = OfertasBot()
    loop = asyncio.get_event_loop()

    def signal_handler():
        logging.info("Señal de interrupción recibida, deteniendo el bot...")
        asyncio.create_task(bot.stop())

    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, signal_handler)

    try:
        loop.run_until_complete(bot.run())
    finally:
        loop.close()

if __name__ == "__main__":
    main()
