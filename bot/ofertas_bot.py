
import asyncio
import logging
from collections import deque
from typing import List, Dict, Any
from telegram import Bot
from telegram.ext import Application
from telegram.error import NetworkError, RetryAfter

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
        self.application = Application.builder().token(self.config.TOKEN).build()
        self.bot = Bot(self.config.TOKEN)
        self.max_ofertas_por_ejecucion = 15
        self.is_running = True
        self.cooldowns = {
            'slickdeals': 7 * 24 * 3600,
            'dealnews': 24 * 3600
        }
        self.ofertas_recientes = deque(maxlen=1000)
        self.logger = logging.getLogger('OfertasBot')

    def init_scrapers(self) -> List:
        return [
            SlickdealsScraper(self.fuentes['slickdeals']['url'], self.fuentes['slickdeals']['tag']),
            DealsnewsScraper(self.fuentes['dealnews']['url'], self.fuentes['dealnews']['tag'])
        ]

    async def run(self) -> None:
        await self.application.initialize()
        await self.application.start()
        await self.application.updater.start_polling()

        setup_handlers(self.application, self)

        while self.is_running:
            try:
                await self.check_ofertas()
                await asyncio.sleep(1800)  # 30 minutos
            except asyncio.CancelledError:
                self.logger.info("Tarea cancelada, finalizando el bot.")
                break
            except Exception as e:
                self.logger.error(f"Error en el ciclo principal: {e}", exc_info=True)
                await asyncio.sleep(60)

        await self.application.stop()
        await self.application.shutdown()

    async def stop(self) -> None:
        self.is_running = False
        await self.application.stop()
        await self.application.shutdown()

    async def check_ofertas(self) -> None:
        todas_las_ofertas = []
        ofertas_por_fuente = {}
        
        for scraper in self.scrapers:
            try:
                self.logger.info(f"Iniciando scraping de {scraper.__class__.__name__}")
                ofertas = await asyncio.to_thread(scraper.obtener_ofertas)
                self.logger.info(f"Se obtuvieron {len(ofertas)} ofertas de {scraper.__class__.__name__}")
                
                todas_las_ofertas.extend(ofertas)
                ofertas_por_fuente[scraper.__class__.__name__] = len(ofertas)
            except Exception as e:
                self.logger.error(f"Error al obtener ofertas de {scraper.__class__.__name__}: {e}", exc_info=True)

        nuevas_ofertas = self.db_manager.filtrar_nuevas_ofertas(todas_las_ofertas)
        
        self.logger.info(f"Se encontraron {len(nuevas_ofertas)} nuevas ofertas para enviar")
        
        ofertas_con_puntuacion = [(oferta, self.calcular_puntuacion_oferta(oferta)) for oferta in nuevas_ofertas]
        ofertas_con_puntuacion.sort(key=lambda x: x[1], reverse=True)
        
        ofertas_enviadas_esta_vez = 0
        
        for oferta, puntuacion in ofertas_con_puntuacion[:self.max_ofertas_por_ejecucion]:
            if puntuacion > 30:  # Umbral de puntuación
                if await self.enviar_oferta_con_reintento(oferta):
                    self.db_manager.guardar_oferta(oferta)
                    self.ofertas_recientes.append(oferta)
                    ofertas_enviadas_esta_vez += 1
                    
                    self.logger.info(f"Oferta enviada y guardada: {oferta['titulo']} - Fuente: {oferta['tag']} (Puntuación: {puntuacion})")
                else:
                    self.logger.error(f"No se pudo enviar la oferta después de varios intentos: {oferta['titulo']}")
            else:
                self.logger.debug(f"Oferta ignorada por baja puntuación ({puntuacion}): {oferta['titulo']}")

        ofertas_antiguas_eliminadas = self.db_manager.limpiar_ofertas_antiguas()
        
        self.logger.info(f"Resumen de ejecución:")
        self.logger.info(f"  - Total de ofertas obtenidas: {len(todas_las_ofertas)}")
        self.logger.info(f"  - Nuevas ofertas encontradas: {len(nuevas_ofertas)}")
        self.logger.info(f"  - Ofertas enviadas en esta ejecución: {ofertas_enviadas_esta_vez}")
        self.logger.info(f"  - Ofertas antiguas eliminadas: {ofertas_antiguas_eliminadas}")

    async def enviar_oferta_con_reintento(self, oferta: Dict[str, Any], max_intentos: int = 3) -> bool:
        for intento in range(max_intentos):
            try:
                mensaje = self.formatear_mensaje_oferta(oferta)
                await self.bot.send_message(chat_id=self.config.CHANNEL_ID, text=mensaje, parse_mode='Markdown')
                return True
            except NetworkError as e:
                self.logger.error(f"Error de red al enviar oferta (intento {intento + 1}/{max_intentos}): {e}")
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

<<<<<<< HEAD
    def calcular_puntuacion_oferta(self, oferta):
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
    
    # Penalización por ofertas similares recientes
    	if self.es_oferta_reciente(oferta):
        	puntuacion -= 50
=======
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
        
        # Penalización por ofertas similares recientes
        if self.es_oferta_reciente(oferta):
            puntuacion -= 50
>>>>>>> 08c82b4 (Mejorado el manejo de errores identacion)

        return puntuacion

    def es_oferta_reciente(self, oferta: Dict[str, Any]) -> bool:
        return any(self.son_ofertas_similares(oferta, oferta_reciente) for oferta_reciente in self.ofertas_recientes)

    def son_ofertas_similares(self, oferta1: Dict[str, Any], oferta2: Dict[str, Any]) -> bool:
        return (
            oferta1['titulo'].lower() == oferta2['titulo'].lower() and
            oferta1['precio'] == oferta2['precio'] and
            oferta1['link'] == oferta2['link']
        )

    async def enviar_notificacion_error(self, error: Exception) -> None:
        mensaje = f"🚨 *Error en el bot de ofertas* 🚨\n\n"
        mensaje += f"Detalles del error:\n"
        mensaje += f"`{type(error).__name__}`: `{str(error)}`"
        try:
            await self.bot.send_message(chat_id=self.config.CHANNEL_ID, text=mensaje, parse_mode='Markdown')
        except Exception as e:
            self.logger.error(f"No se pudo enviar notificación de error: {e}", exc_info=True)
