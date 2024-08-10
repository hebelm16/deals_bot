import asyncio
import logging
from collections import deque
from typing import List, Dict, Any
from telegram import Bot
from telegram.ext import Application
from telegram.error import NetworkError, RetryAfter, Conflict
import random
import os
import fcntl
import time

from config import Config
from database.db_manager import DBManager
from scrapers.slickdeals_scraper import SlickdealsScraper
from scrapers.dealnews_scraper import DealsnewsScraper
from bot.handlers import setup_handlers

class OfertasBot:
    def __init__(self):
        self.config = Config()
        self.db_manager = DBManager(self.config.DATABASE)
        self.fuentes = {
            'dealnews': {'url': self.config.DEALSNEWS_URL, 'tag': "#DealNews", 'habilitado': True},
            'slickdeals': {'url': self.config.SLICKDEALS_URL, 'tag': "#Slickdeals", 'habilitado': True}
        }
        self.scrapers = self.init_scrapers()
        self.application = None
        self.bot = None
        self.max_ofertas_por_ejecucion = 15
        self.is_running = True
        self.cooldowns = {
            'slickdeals': 7 * 24 * 3600,
            'dealnews': 24 * 3600
        }
        self.ofertas_recientes = deque(maxlen=1000)
        self.logger = logging.getLogger('OfertasBot')
        self.lock = asyncio.Lock()

    def init_scrapers(self) -> List:
        return [
            SlickdealsScraper(self.fuentes['slickdeals']['url'], self.fuentes['slickdeals']['tag']),
            DealsnewsScraper(self.fuentes['dealnews']['url'], self.fuentes['dealnews']['tag'])
        ]

    async def run(self) -> None:
        if not self.acquire_lock():
            self.logger.error("Otra instancia del bot ya está en ejecución. Saliendo.")
            return

        try:
            self.application = Application.builder().token(self.config.TOKEN).build()
            self.bot = Bot(self.config.TOKEN)
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling(drop_pending_updates=True)

            setup_handlers(self.application, self)

            while self.is_running:
                try:
                    await self.check_ofertas()
                except Exception as e:
                    self.logger.error(f"Error en el ciclo principal: {e}", exc_info=True)
                    await self.enviar_notificacion_error(e)
                finally:
                    await asyncio.sleep(1800)  # 30 minutos

            await self.application.stop()
            await self.application.shutdown()
        finally:
            self.release_lock()

    def acquire_lock(self) -> bool:
        lock_file = "/tmp/ofertasbot.lock"
        self.lock_fd = open(lock_file, 'w')
        try:
            fcntl.lockf(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except IOError:
            return False

    def release_lock(self) -> None:
        if hasattr(self, 'lock_fd'):
            fcntl.lockf(self.lock_fd, fcntl.LOCK_UN)
            self.lock_fd.close()

    async def stop(self) -> None:
        self.is_running = False
        if self.application:
            await self.application.stop()
            await self.application.shutdown()

    async def check_ofertas(self) -> None:
        async with self.lock:
            todas_las_ofertas = {'slickdeals': [], 'dealnews': []}
            
            for scraper in self.scrapers:
                try:
                    self.logger.info(f"Iniciando scraping de {scraper.__class__.__name__}")
                    ofertas = await asyncio.to_thread(scraper.obtener_ofertas)
                    self.logger.info(f"Se obtuvieron {len(ofertas)} ofertas de {scraper.__class__.__name__}")
                    
                    if isinstance(scraper, SlickdealsScraper):
                        todas_las_ofertas['slickdeals'] = ofertas
                    elif isinstance(scraper, DealsnewsScraper):
                        todas_las_ofertas['dealnews'] = ofertas
                except Exception as e:
                    self.logger.error(f"Error al obtener ofertas de {scraper.__class__.__name__}: {e}", exc_info=True)

            nuevas_ofertas_slickdeals = self.db_manager.filtrar_ofertas_no_enviadas(todas_las_ofertas['slickdeals'])
            nuevas_ofertas_dealnews = self.db_manager.filtrar_ofertas_no_enviadas(todas_las_ofertas['dealnews'])
            
            self.logger.info(f"Se encontraron {len(nuevas_ofertas_slickdeals)} nuevas ofertas de Slickdeals")
            self.logger.info(f"Se encontraron {len(nuevas_ofertas_dealnews)} nuevas ofertas de DealNews")
            
            ofertas_con_puntuacion_slickdeals = [(oferta, self.calcular_puntuacion_oferta(oferta)) for oferta in nuevas_ofertas_slickdeals]
            ofertas_con_puntuacion_dealnews = [(oferta, self.calcular_puntuacion_oferta(oferta)) for oferta in nuevas_ofertas_dealnews]
            
            ofertas_con_puntuacion_slickdeals.sort(key=lambda x: x[1], reverse=True)
            ofertas_con_puntuacion_dealnews.sort(key=lambda x: x[1], reverse=True)
            
            ofertas_a_enviar = self.seleccionar_ofertas_equilibradas(ofertas_con_puntuacion_slickdeals, ofertas_con_puntuacion_dealnews)
            
            ofertas_enviadas_esta_vez = 0
            
            for oferta, puntuacion in ofertas_a_enviar:
                if await self.enviar_oferta_con_reintento(oferta):
                    self.db_manager.marcar_oferta_como_enviada(oferta)
                    self.ofertas_recientes.append(oferta)
                    ofertas_enviadas_esta_vez += 1
                    
                    self.logger.info(f"Oferta enviada y guardada: {oferta['titulo']} - Fuente: {oferta['tag']} (Puntuación: {puntuacion})")
                else:
                    self.logger.error(f"No se pudo enviar la oferta después de varios intentos: {oferta['titulo']}")

            ofertas_antiguas_eliminadas = self.db_manager.limpiar_ofertas_antiguas()
            
            self.logger.info(f"Resumen de ejecución:")
            self.logger.info(f"  - Nuevas ofertas de Slickdeals: {len(nuevas_ofertas_slickdeals)}")
            self.logger.info(f"  - Nuevas ofertas de DealNews: {len(nuevas_ofertas_dealnews)}")
            self.logger.info(f"  - Ofertas enviadas en esta ejecución: {ofertas_enviadas_esta_vez}")
            self.logger.info(f"  - Ofertas antiguas eliminadas: {ofertas_antiguas_eliminadas}")

    def seleccionar_ofertas_equilibradas(self, ofertas_slickdeals: List[tuple], ofertas_dealnews: List[tuple]) -> List[tuple]:
        total_ofertas = min(self.max_ofertas_por_ejecucion, len(ofertas_slickdeals) + len(ofertas_dealnews))
        mitad = total_ofertas // 2
        
        ofertas_seleccionadas = []
        ofertas_seleccionadas.extend(ofertas_slickdeals[:mitad])
        ofertas_seleccionadas.extend(ofertas_dealnews[:mitad])
        
        # Si el total es impar, añadimos una oferta más al azar
        if total_ofertas % 2 != 0:
            if ofertas_slickdeals[mitad:]:
                ofertas_seleccionadas.append(ofertas_slickdeals[mitad])
            elif ofertas_dealnews[mitad:]:
                ofertas_seleccionadas.append(ofertas_dealnews[mitad])
        
        # Mezclar las ofertas para que no siempre vayan en el mismo orden
        random.shuffle(ofertas_seleccionadas)
        
        return ofertas_seleccionadas[:self.max_ofertas_por_ejecucion]

    async def enviar_oferta_con_reintento(self, oferta: Dict[str, Any], max_intentos: int = 3) -> bool:
        for intento in range(max_intentos):
            try:
                mensaje = self.formatear_mensaje_oferta(oferta)
                if oferta.get('imagen') and oferta['imagen'] != 'No disponible':
                    await self.bot.send_photo(chat_id=self.config.CHANNEL_ID, photo=oferta['imagen'], caption=mensaje, parse_mode='Markdown')
                else:
                    await self.bot.send_message(chat_id=self.config.CHANNEL_ID, text=mensaje, parse_mode='Markdown')
                return True
            except (NetworkError, Conflict) as e:
                self.logger.error(f"Error al enviar oferta (intento {intento + 1}/{max_intentos}): {e}")
                if intento < max_intentos - 1:
                    await asyncio.sleep(5 * (intento + 1))
            except RetryAfter as e:
                retry_time = int(str(e).split()[-1]) + 1
                self.logger.warning(f"Límite de velocidad alcanzado. Esperando {retry_time} segundos.")
                await asyncio.sleep(retry_time)
            except Exception as e:
                self.logger.error(f"Error inesperado al enviar oferta: {e}", exc_info=True)
                return False
        return False

    def formatear_mensaje_oferta(self, oferta: Dict[str, Any]) -> str:
        mensaje = f"{oferta['tag']} 📢 ¡Nueva oferta! 📢\n\n"
        mensaje += f"📌 *{oferta['titulo']}*\n\n"
        mensaje += f"💵 Precio: {oferta['precio']}\n"
        if oferta.get('precio_original'):
            mensaje += f"💰 Precio original: {oferta['precio_original']}\n"
        if oferta.get('cupon'):
            mensaje += f"🏷️ Cupón: `{oferta['cupon']}`\n"
        if oferta.get('info_cupon'):
            mensaje += f"ℹ️ Info: {oferta['info_cupon']}\n"
        mensaje += f"\n🔗 [Ver oferta]({oferta['link']})"
        return mensaje

    def calcular_puntuacion_oferta(self, oferta: Dict[str, Any]) -> float:
        puntuacion = 0
        if 'precio_original' in oferta and 'precio' in oferta and oferta['precio_original'] and oferta['precio']:
            try:
                precio_original = float(oferta['precio_original'].replace('$', '').replace(',', ''))
                precio_actual = float(oferta['precio'].replace('$', '').replace(',', ''))
                if precio_original > precio_actual:
                    descuento = (precio_original - precio_actual) / precio_original
                    puntuacion += descuento * 100  # Mayor descuento, mayor puntuación
            except ValueError:
                self.logger.warning(f"No se pudo calcular el descuento para la oferta: {oferta.get('titulo', 'Sin título')}")
        
        if oferta.get('cupon'):
            puntuacion += 20  # Bonus por tener cupón
        
        return puntuacion

    async def enviar_notificacion_error(self, error: Exception) -> None:
        mensaje = f"🚨 *Error en el bot de ofertas* 🚨\n\n"
        mensaje += f"Detalles del error:\n"
        mensaje += f"`{type(error).__name__}`: `{str(error)}`"
        try:
            await self.bot.send_message(chat_id=self.config.CHANNEL_ID, text=mensaje, parse_mode='Markdown')
        except Exception as e:
            self.logger.error(f"No se pudo enviar notificación de error: {e}", exc_info=True)
