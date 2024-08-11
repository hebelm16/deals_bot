import asyncio
import logging
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
        self.is_running = True
        self.logger = logging.getLogger('OfertasBot')
        self.lock = asyncio.Lock()
        self.lock_file = "/tmp/ofertasbot.lock"
        self.lock_fd = None
        self.max_ofertas_por_ejecucion = 20  # Limitamos a 20 ofertas por ejecución

    def init_scrapers(self) -> List:
        return [
            SlickdealsScraper(self.fuentes['slickdeals']['url'], self.fuentes['slickdeals']['tag']),
            DealsnewsScraper(self.fuentes['dealnews']['url'], self.fuentes['dealnews']['tag'])
        ]

    async def run(self) -> None:
        if not await self.acquire_lock():
            self.logger.error("Otra instancia del bot ya está en ejecución. Saliendo.")
            return

        try:
            self.application = Application.builder().token(self.config.TOKEN).build()
            self.bot = Bot(self.config.TOKEN)
            await self.application.initialize()
            await self.application.start()
            await self.application.updater.start_polling(drop_pending_updates=True)

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

    async def acquire_lock(self) -> bool:
        try:
            self.lock_fd = open(self.lock_file, 'w')
            fcntl.lockf(self.lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            self.logger.info("Bloqueo adquirido exitosamente")
            return True
        except IOError:
            self.logger.warning("No se pudo adquirir el bloqueo. Otra instancia puede estar en ejecución.")
            if self.lock_fd:
                self.lock_fd.close()
            return False

    def release_lock(self) -> None:
        if self.lock_fd:
            fcntl.lockf(self.lock_fd, fcntl.LOCK_UN)
            self.lock_fd.close()
            try:
                os.remove(self.lock_file)
                self.logger.info("Bloqueo liberado y archivo de bloqueo eliminado")
            except OSError:
                self.logger.warning("No se pudo eliminar el archivo de bloqueo")

    async def stop(self) -> None:
        self.is_running = False
        if self.application:
            await self.application.stop()
            await self.application.shutdown()
        self.release_lock()

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

            nuevas_ofertas_slickdeals = [oferta for oferta in todas_las_ofertas['slickdeals'] if not self.db_manager.es_oferta_repetida(oferta)]
            nuevas_ofertas_dealnews = [oferta for oferta in todas_las_ofertas['dealnews'] if not self.db_manager.es_oferta_repetida(oferta)]
            
            self.logger.info(f"Nuevas ofertas de Slickdeals: {len(nuevas_ofertas_slickdeals)}")
            self.logger.info(f"Nuevas ofertas de DealNews: {len(nuevas_ofertas_dealnews)}")
            
            ofertas_a_enviar = self.seleccionar_ofertas_equilibradas(nuevas_ofertas_slickdeals, nuevas_ofertas_dealnews)
            
            self.logger.info(f"Total de ofertas a enviar: {len(ofertas_a_enviar)}")
            
            ofertas_enviadas_esta_vez = 0
            
            for oferta in ofertas_a_enviar:
                if await self.enviar_oferta_con_reintento(oferta):
                    self.db_manager.guardar_oferta(oferta)
                    ofertas_enviadas_esta_vez += 1
                    self.logger.info(f"Oferta enviada y guardada: {oferta['titulo']} - Fuente: {oferta['tag']}")
                else:
                    self.logger.error(f"No se pudo enviar la oferta después de varios intentos: {oferta['titulo']}")

                await asyncio.sleep(5)  # Espera 5 segundos entre cada envío para evitar flood

            ofertas_antiguas_eliminadas = self.db_manager.limpiar_ofertas_antiguas()
            
            self.logger.info(f"Resumen de ejecución:")
            self.logger.info(f"  - Ofertas enviadas en esta ejecución: {ofertas_enviadas_esta_vez}")
            self.logger.info(f"  - Ofertas antiguas eliminadas: {ofertas_antiguas_eliminadas}")

    def seleccionar_ofertas_equilibradas(self, ofertas_slickdeals: List[Dict[str, Any]], ofertas_dealnews: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        total_ofertas = min(self.max_ofertas_por_ejecucion, len(ofertas_slickdeals) + len(ofertas_dealnews))
        mitad = total_ofertas // 2
        
        ofertas_seleccionadas = []
        ofertas_seleccionadas.extend(random.sample(ofertas_slickdeals, min(mitad, len(ofertas_slickdeals))))
        ofertas_seleccionadas.extend(random.sample(ofertas_dealnews, min(total_ofertas - len(ofertas_seleccionadas), len(ofertas_dealnews))))
        
        # Si aún no hemos alcanzado el total, completamos con las ofertas restantes
        if len(ofertas_seleccionadas) < total_ofertas:
            ofertas_restantes = ofertas_slickdeals + ofertas_dealnews
            ofertas_restantes = [oferta for oferta in ofertas_restantes if oferta not in ofertas_seleccionadas]
            ofertas_seleccionadas.extend(random.sample(ofertas_restantes, min(total_ofertas - len(ofertas_seleccionadas), len(ofertas_restantes))))
        
        random.shuffle(ofertas_seleccionadas)
        return ofertas_seleccionadas

    async def enviar_oferta_con_reintento(self, oferta: Dict[str, Any], max_intentos: int = 3) -> bool:
        for intento in range(max_intentos):
            try:
                mensaje = self.formatear_mensaje_oferta(oferta)
                if oferta.get('imagen') and oferta['imagen'] != 'No disponible':
                    await self.bot.send_photo(chat_id=self.config.CHANNEL_ID, photo=oferta['imagen'], caption=mensaje, parse_mode='Markdown')
                else:
                    await self.bot.send_message(chat_id=self.config.CHANNEL_ID, text=mensaje, parse_mode='Markdown')
                return True
            except RetryAfter as e:
                retry_time = int(e.retry_after) + 1
                self.logger.warning(f"Límite de velocidad alcanzado. Esperando {retry_time} segundos.")
                await asyncio.sleep(retry_time)
            except (NetworkError, Conflict) as e:
                self.logger.error(f"Error al enviar oferta (intento {intento + 1}/{max_intentos}): {e}")
                if intento < max_intentos - 1:
                    await asyncio.sleep(5 * (intento + 1))
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
        if oferta['tag'] == "#DealNews" and oferta.get('info_cupon'):
            mensaje += f"ℹ️ Info: {oferta['info_cupon']}\n"
        mensaje += f"\n🔗 [Ver oferta]({oferta['link']})"
        return mensaje

    async def enviar_notificacion_error(self, error: Exception) -> None:
        mensaje = f"🚨 *Error en el bot de ofertas* 🚨\n\n"
        mensaje += f"Detalles del error:\n"
        mensaje += f"`{type(error).__name__}`: `{str(error)}`"
        try:
            await self.bot.send_message(chat_id=self.config.CHANNEL_ID, text=mensaje, parse_mode='Markdown')
        except Exception as e:
            self.logger.error(f"No se pudo enviar notificación de error: {e}", exc_info=True)

def main():
    bot = OfertasBot()
    asyncio.run(bot.run())

if __name__ == "__main__":
    main()
