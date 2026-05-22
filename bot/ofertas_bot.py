import asyncio
import logging
from typing import List, Dict, Any, Set
from telegram import Bot
from telegram.ext import Application
from telegram.error import NetworkError, RetryAfter, Conflict, BadRequest, TimedOut
import random
import os
import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup, BotCommand
from filelock import FileLock, Timeout
import importlib
import inspect
from tenacity import retry, wait_fixed, stop_after_attempt, retry_if_exception_type

from config import Config
from database.db_manager import DBManager
from bot.handlers import setup_handlers
from utils.models import Oferta
from utils.ai_helper import generar_gancho_ia
import re

class OfertasBot:
    def __init__(self):
        self.config = Config()
        self.logger = logging.getLogger("OfertasBot")
        self.db_manager = DBManager(self.config.DATABASE)
        self.scrapers = self.init_scrapers()
        self.application = None
        self.bot = None
        self.is_running = True
        self.lock = asyncio.Lock()
        self.lock_file = "ofertasbot.lock"
        self.browser = None
        self.stop_event = asyncio.Event()

    def init_scrapers(self) -> Dict[str, Any]:
        scrapers = {}
        for scraper_config in self.config.SCRAPERS:
            try:
                module = importlib.import_module(scraper_config["module"])
                scraper_class = getattr(module, scraper_config["class"])
                scraper_instance = scraper_class(
                    name=scraper_config["name"],
                    url=scraper_config["url"],
                    tag=scraper_config["tag"],
                )
                scrapers[scraper_config["name"]] = {
                    "instance": scraper_instance,
                    "enabled": scraper_config["enabled"]
                }
                self.logger.info(f"Scraper '{scraper_config['name']}' cargado exitosamente.")
            except (ImportError, AttributeError) as e:
                self.logger.error(
                    f"No se pudo cargar el scraper '{scraper_config['name']}': {e}",
                    exc_info=True,
                )
        return scrapers

    async def launch_browser(self):
        """Lanza el navegador si algún scraper lo necesita."""
        for scraper_info in self.scrapers.values():
            if scraper_info["enabled"] and hasattr(scraper_info["instance"], 'launch_browser'):
                self.logger.info("Lanzando navegador para scrapers dinámicos...")
                try:
                    # Asumimos que el primer scraper con `launch_browser` puede lanzar el navegador.
                    self.browser = await scraper_info["instance"].launch_browser()
                    self.logger.info("Navegador Playwright lanzado exitosamente.")
                except Exception as e:
                    self.logger.error(
                        f"No se pudo lanzar el navegador Playwright: {e}. "
                        f"El scraper {scraper_info['instance'].name} será deshabilitado.",
                        exc_info=True
                    )
                    # Deshabilitar este scraper si falla el navegador
                    scraper_info["enabled"] = False
                break

    async def close_browser(self):
        """Cierra el navegador si está activo."""
        if self.browser:
            try:
                self.logger.info("Cerrando el navegador Playwright...")
                await self.browser.close()
            except Exception as e:
                self.logger.warning(f"Error al cerrar el navegador: {e}")
            finally:
                self.browser = None

    async def run(self) -> None:
        try:
            lock = FileLock(self.lock_file, timeout=0)
            with lock:
                self.logger.info("Bloqueo adquirido exitosamente.")
                await self.db_manager.init_db()

                # Crear application con timeout robusto
                self.application = (
                    Application.builder()
                    .token(self.config.TOKEN)
                    .build()
                )
                self.bot = Bot(self.config.TOKEN)
                self.application.bot_data["bot"] = self
                setup_handlers(self.application, self)
                await self.application.initialize()
                await self.application.start()
                
                # Configurar menú de comandos
                try:
                    comandos = [
                        BotCommand("start", "Muestra el mensaje de bienvenida y ayuda"),
                        BotCommand("ayuda", "Muestra los comandos disponibles"),
                        BotCommand("alerta", "Crea una alerta para una palabra clave"),
                        BotCommand("mis_alertas", "Mira a qué palabras estás suscrito"),
                        BotCommand("borrar_alerta", "Elimina una alerta existente"),
                        BotCommand("estado", "Ver estado de los scrapers (Admin)"),
                    ]
                    await self.bot.set_my_commands(comandos)
                    self.logger.info("Comandos de Telegram configurados en el menú.")
                except Exception as e:
                    self.logger.error(f"No se pudieron configurar los comandos: {e}")
                
                # Usar polling o webhooks según configuración
                try:
                    if self.config.USE_WEBHOOKS and self.config.WEBHOOK_URL:
                        self.logger.info(f"Iniciando en modo WEBHOOK en el puerto {self.config.PORT}")
                        # El webhook URL path por defecto es el token
                        webhook_path = f"/{self.config.TOKEN}"
                        full_webhook_url = f"{self.config.WEBHOOK_URL.rstrip('/')}{webhook_path}"
                        
                        await self.application.updater.start_webhook(
                            listen="0.0.0.0",
                            port=self.config.PORT,
                            webhook_url=full_webhook_url,
                            url_path=webhook_path
                        )
                    else:
                        self.logger.info("Iniciando en modo POLLING")
                        # Por si acaso había un webhook configurado antes, lo borramos
                        await self.application.bot.delete_webhook(drop_pending_updates=True)
                        
                        await self.application.updater.start_polling(
                            drop_pending_updates=True,
                            error_callback=self._telegram_error_callback,
                            timeout=self.config.TELEGRAM_POLLING_TIMEOUT,
                            poll_interval=self.config.TELEGRAM_POLLING_INTERVAL,
                        )
                except Exception as net_startup_error:
                    self.logger.error(f"Error al iniciar red de Telegram: {net_startup_error}", exc_info=True)
                    raise

                self.logger.info("Añadiendo tarea de scraping a JobQueue.")
                self.application.job_queue.run_repeating(
                    self.scheduled_check_ofertas,
                    interval=self.config.LOOP_INTERVAL_SECONDS,
                    first=1
                )

                # Mantener vivo el programa hasta recibir señal de parada
                await self.stop_event.wait()

                await self.application.stop()
                await self.application.shutdown()
        except Timeout:
            self.logger.error("Otra instancia del bot ya está en ejecución. Saliendo.")
            return
        except Exception as e:
            self.logger.critical(f"Error fatal al iniciar el bot: {e}", exc_info=True)
        finally:
            await self.close_browser()  # Asegurarse de cerrar el navegador
            self.logger.info("El bot se ha detenido.")

    def _telegram_error_callback(self, context) -> None:
        """Maneja errores de Telegram durante el polling. NO es async."""
        try:
            error_msg = str(context.error) if hasattr(context, 'error') else str(context)
            self.logger.error(f"Error de Telegram: {error_msg}")
            
            if hasattr(context, 'error'):
                if isinstance(context.error, NetworkError):
                    self.logger.warning("Error de red detectado. El bot intentará reconectarse automáticamente.")
                elif isinstance(context.error, TimedOut):
                    self.logger.warning("Timeout de Telegram. El bot intentará reconectarse automáticamente.")
                elif isinstance(context.error, Conflict):
                    self.logger.warning("Conflicto: Otra instancia del bot está activa. El bot se reconectará.")
        except Exception as e:
            self.logger.error(f"Error al manejar error de Telegram: {e}")

    async def stop(self) -> None:
        self.is_running = False
        self.stop_event.set()
        if self.application:
            await self.application.stop()
            await self.application.shutdown()

    async def _scrape_all_sources(self) -> Dict[str, List[Oferta]]:
        """Ejecuta todos los scrapers habilitados de forma concurrente y devuelve sus resultados."""
        scraped_deals = {name: [] for name, scraper_info in self.scrapers.items() if scraper_info["enabled"]}
        self.logger.info("Iniciando scraping concurrente de todas las fuentes habilitadas.")
        
        enabled_scrapers = [scraper_info["instance"] for scraper_info in self.scrapers.values() if scraper_info["enabled"]]
        tasks = []
        for scraper in enabled_scrapers:
            method = scraper.obtener_ofertas
            is_async = inspect.iscoroutinefunction(method)
            
            # Inspeccionar la firma del método para ver si necesita el navegador
            sig = inspect.signature(method)
            if 'browser' in sig.parameters:
                if not self.browser:
                    self.logger.error(f"El scraper {scraper.name} necesita un navegador, pero no hay uno activo.")
                    continue
                if is_async:
                    tasks.append(method(self.browser))
                else:
                    # No es ideal ejecutar una tarea de navegador en un hilo síncrono, pero se maneja
                    tasks.append(asyncio.to_thread(method, self.browser))
            else:
                if is_async:
                    tasks.append(method())
                else:
                    tasks.append(asyncio.to_thread(method))
        
        if not tasks:
            self.logger.warning("No hay tareas de scraping para ejecutar.")
            return scraped_deals

        results = await asyncio.gather(*tasks, return_exceptions=True)
        self.logger.info("Scraping concurrente finalizado.")

        for i, result in enumerate(results):
            # Es necesario un mapeo más robusto si las tareas no se mantienen en orden
            scraper = enabled_scrapers[i]
            if isinstance(result, Exception):
                self.logger.error(f"Error al obtener ofertas de {scraper.name}: {result}", exc_info=result)
            else:
                self.logger.info(f"Se obtuvieron {len(result)} ofertas de {scraper.name}")
                scraped_deals[scraper.name] = result
        
        return scraped_deals

    async def _filter_new_deals(self, all_deals: Dict[str, List[Oferta]]) -> Dict[str, List[Oferta]]:
        """Filtra las ofertas para quedarse solo con las que no están en la base de datos."""
        self.logger.info("Optimizando la verificación de duplicados...")
        recent_ids = await self.db_manager.obtener_ids_recientes()
        self.logger.info(f"Cargados {len(recent_ids)} IDs de ofertas recientes para verificación.")

        def is_new(deal: Oferta) -> bool:
            deal_id = self.db_manager.generar_id_oferta(deal)
            return deal_id not in recent_ids

        new_deals_by_source = {
            name: [deal for deal in deals if is_new(deal)]
            for name, deals in all_deals.items()
        }

        for name, deals in new_deals_by_source.items():
            self.logger.info(f"Nuevas ofertas de {name}: {len(deals)}")
            
        return new_deals_by_source

    async def _process_new_deals(self, new_deals_by_source: Dict[str, List[Oferta]]) -> int:
        """Selecciona, envía y guarda las nuevas ofertas."""
        deals_to_send = self.seleccionar_ofertas_equilibradas(
            *[deals for deals in new_deals_by_source.values()]
        )
        self.logger.info(f"Total de ofertas a enviar: {len(deals_to_send)}")

        # Obtener todas las suscripciones activas
        suscripciones = await self.db_manager.obtener_todas_las_suscripciones()

        sent_deals_count = 0
        for deal in deals_to_send:
            # Generar gancho de IA si el API KEY está configurado
            gancho = await generar_gancho_ia(deal.titulo, deal.precio, deal.precio_original)
            if gancho:
                deal.gancho_ia = gancho

            if await self.enviar_oferta_con_reintento(deal):
                await self.db_manager.guardar_oferta(deal)
                sent_deals_count += 1
                self.logger.info(f"Oferta enviada y guardada: {deal.titulo} - Fuente: {deal.tag}")
                
                # Enviar alertas a los usuarios suscritos
                for sub in suscripciones:
                    # Buscar coincidencia de palabra clave con regex para palabras completas
                    match = False
                    keyword_pattern = r'\b' + re.escape(sub['keyword'].lower()) + r'\b'
                    
                    if re.search(keyword_pattern, deal.titulo.lower()):
                        match = True
                    elif deal.info_cupon and re.search(keyword_pattern, deal.info_cupon.lower()):
                        match = True
                        
                    if match:
                        try:
                            mensaje_formateado = self.formatear_mensaje_oferta(deal)
                            mensaje_dm = f"🔔 <b>¡ALERTA DE PALABRA CLAVE: {sub['keyword']}!</b> 🔔\n\n" + mensaje_formateado["text"]
                            if deal.imagen and deal.imagen != 'No disponible':
                                await self.bot.send_photo(
                                    chat_id=sub['chat_id'],
                                    photo=deal.imagen,
                                    caption=mensaje_dm,
                                    reply_markup=mensaje_formateado["reply_markup"],
                                    parse_mode="HTML"
                                )
                            else:
                                await self.bot.send_message(
                                    chat_id=sub['chat_id'],
                                    text=mensaje_dm,
                                    reply_markup=mensaje_formateado["reply_markup"],
                                    parse_mode="HTML"
                                )
                            self.logger.info(f"Alerta enviada a {sub['chat_id']} por la palabra {sub['keyword']}")
                            await asyncio.sleep(0.5)  # Prevenir rate limiting
                        except Exception as e:
                            self.logger.error(f"Error al enviar alerta a {sub['chat_id']}: {e}")

            else:
                self.logger.error(f"No se pudo enviar la oferta después de varios intentos: {deal.titulo}")
            
            await asyncio.sleep(self.config.SEND_OFFER_INTERVAL_SECONDS)
        
        return sent_deals_count

    async def scheduled_check_ofertas(self, context) -> None:
        try:
            await self.check_ofertas()
        except (NetworkError, TimedOut) as net_error:
            self.logger.warning(f"Error de red temporal en scraping: {net_error}")
        except Exception as e:
            self.logger.error(f"Error en el ciclo principal: {e}", exc_info=True)
            await self.enviar_notificacion_error(e)

    async def check_ofertas(self) -> None:
        """
        Orquesta el proceso completo de buscar, filtrar, enviar y limpiar ofertas.
        """
        async with self.lock:
            await self.launch_browser()
            try:
                # 1. Scrape all sources
                scraped_deals = await self._scrape_all_sources()
                
                # 2. Filter for new deals
                new_deals = await self._filter_new_deals(scraped_deals)
                
                # 3. Process and send new deals
                sent_count = await self._process_new_deals(new_deals)
                
                # 4. Clean up old deals from the database
                cleaned_count = await self.db_manager.limpiar_ofertas_antiguas(
                    dias=self.config.DIAS_LIMPIEZA_OFERTAS_ANTIGUAS
                )
                
                # 5. Log summary
                self.logger.info("Resumen de ejecución:")
                self.logger.info(f"  - Ofertas enviadas en esta ejecución: {sent_count}")
                self.logger.info(f"  - Ofertas antiguas eliminadas: {cleaned_count}")
            finally:
                await self.close_browser()

    def seleccionar_ofertas_equilibradas(
        self, *listas_de_ofertas: List[List[Oferta]]
    ) -> List[Oferta]:
        
        ofertas_seleccionadas = []
        listas_no_vacias = [lista for lista in listas_de_ofertas if lista]
        
        if not listas_no_vacias:
            return []

        max_ofertas = self.config.MAX_OFERTAS_POR_EJECUCION
        num_fuentes = len(listas_no_vacias)
        
        # Iteradores para cada lista de ofertas
        iteradores = [iter(lista) for lista in listas_no_vacias]
        
        while len(ofertas_seleccionadas) < max_ofertas:
            ofertas_agregadas_en_ciclo = 0
            for i in range(num_fuentes):
                try:
                    oferta = next(iteradores[i])
                    if oferta not in ofertas_seleccionadas:
                        ofertas_seleccionadas.append(oferta)
                        ofertas_agregadas_en_ciclo += 1
                        if len(ofertas_seleccionadas) == max_ofertas:
                            break
                except StopIteration:
                    # Esta fuente no tiene más ofertas
                    continue
            
            if ofertas_agregadas_en_ciclo == 0:
                # No hay más ofertas nuevas en ninguna fuente
                break
        
        random.shuffle(ofertas_seleccionadas)
        return ofertas_seleccionadas
        
    async def enviar_oferta_con_reintento(self, oferta: Oferta) -> bool:
        for intento in range(self.config.SEND_OFFER_MAX_RETRIES):
            try:
                mensaje_formateado = self.formatear_mensaje_oferta(oferta)
                if oferta.imagen and oferta.imagen != 'No disponible':
                    await self.bot.send_photo(
                        chat_id=self.config.CHANNEL_ID, 
                        photo=oferta.imagen, 
                        caption=mensaje_formateado["text"], 
                        reply_markup=mensaje_formateado["reply_markup"],
                        parse_mode=mensaje_formateado["parse_mode"]
                    )
                else:
                    await self.bot.send_message(
                        chat_id=self.config.CHANNEL_ID, 
                        text=mensaje_formateado["text"], 
                        reply_markup=mensaje_formateado["reply_markup"],
                        parse_mode=mensaje_formateado["parse_mode"]
                    )
                return True
            except RetryAfter as e:
                retry_time = int(e.retry_after) + 1
                self.logger.warning(f"Límite de velocidad alcanzado. Esperando {retry_time} segundos.")
                await asyncio.sleep(retry_time)
            except (NetworkError, Conflict) as e:
                self.logger.error(f"Error al enviar oferta (intento {intento + 1}/{self.config.SEND_OFFER_MAX_RETRIES}): {e}")
                if intento < self.config.SEND_OFFER_MAX_RETRIES - 1:
                    await asyncio.sleep(self.config.SEND_OFFER_RETRY_SLEEP_SECONDS * (intento + 1))
            except Exception as e:
                self.logger.error(f"Error inesperado al enviar oferta '{oferta.titulo}': {e}", exc_info=True)
                return False
        return False

    def formatear_mensaje_oferta(self, oferta: Oferta) -> Dict[str, Any]:
        """Formatea el mensaje de la oferta y crea el teclado inline."""
        
        texto = ""
        if oferta.gancho_ia:
            texto += f"<i>{oferta.gancho_ia}</i>\n\n"
            
        texto += f"{oferta.emoji} <b>{oferta.titulo}</b>\n\n"
        texto += f"💰 <b>Precio:</b> {oferta.precio}\n"
        if oferta.precio_original and oferta.precio_original != "No disponible":
            texto += f"📉 <b>Antes:</b> <s>{oferta.precio_original}</s>\n"
        if oferta.info_cupon:
            texto += f"🎟️ <b>Info Extra:</b> {oferta.info_cupon}\n"
        if oferta.cupon:
            texto += f"✂️ <b>Cupón:</b> <code>{oferta.cupon}</code>\n"
        
        texto += f"\n🔗 <a href='{oferta.link}'>Ir a la Oferta</a>\n"
        texto += f"\n🏷️ {oferta.tag}"
        
        keyboard = [[InlineKeyboardButton("🔗 Ver Oferta 🔗", url=oferta.link)]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        return {
            "text": texto,
            "reply_markup": reply_markup,
            "parse_mode": 'HTML'
        }

    async def enviar_notificacion_error(self, error: Exception) -> None:
        mensaje = f"🚨 <b>Error en el bot de ofertas</b> 🚨\n\n"
        mensaje += f"Detalles del error:\n"
        mensaje += f"<code>{type(error).__name__}</code>: <code>{str(error)}</code>"
        try:
            await self.bot.send_message(
                chat_id=self.config.CHANNEL_ID, text=mensaje, parse_mode="HTML"
            )
        except Exception as e:
            self.logger.error(
                f"No se pudo enviar notificación de error: {e}", exc_info=True
            )


def main():
    bot = OfertasBot()
    asyncio.run(bot.run())


if __name__ == "__main__":
    main()
