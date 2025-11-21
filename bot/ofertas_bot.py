import asyncio
import logging
from typing import List, Dict, Any, Set
from telegram import Bot
from telegram.ext import Application
from telegram.error import NetworkError, RetryAfter, Conflict, BadRequest, TimedOut
import random
import os
import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from filelock import FileLock, Timeout
import importlib
import inspect

from config import Config
from database.db_manager import DBManager
from bot.handlers import setup_handlers
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
                await self.launch_browser()  # Lanzar navegador

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
                
                # Usar polling con configuración robusta para errores de red
                try:
                    await self.application.updater.start_polling(
                        drop_pending_updates=True,
                        error_callback=self._telegram_error_callback,
                        timeout=self.config.TELEGRAM_POLLING_TIMEOUT,
                        poll_interval=self.config.TELEGRAM_POLLING_INTERVAL,
                    )
                except Exception as polling_error:
                    self.logger.error(f"Error al iniciar polling: {polling_error}", exc_info=True)
                    raise

                while self.is_running:
                    try:
                        await self.check_ofertas()
                    except (NetworkError, TimedOut) as net_error:
                        # Errores de red temporales - registrar e intentar de nuevo
                        self.logger.warning(
                            f"Error de red temporal en el ciclo principal: {net_error}. Reintentando..."
                        )
                        await asyncio.sleep(5)  # Esperar 5 segundos antes de reintentar
                    except Exception as e:
                        self.logger.error(
                            f"Error en el ciclo principal: {e}", exc_info=True
                        )
                        await self.enviar_notificacion_error(e)
                    finally:
                        await asyncio.sleep(self.config.LOOP_INTERVAL_SECONDS)

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
        if self.application:
            await self.application.stop()
            await self.application.shutdown()

    async def _scrape_all_sources(self) -> Dict[str, List[Dict[str, Any]]]:
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

    async def _filter_new_deals(self, all_deals: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[Dict[str, Any]]]:
        """Filtra las ofertas para quedarse solo con las que no están en la base de datos."""
        self.logger.info("Optimizando la verificación de duplicados...")
        recent_ids = await self.db_manager.obtener_ids_recientes()
        self.logger.info(f"Cargados {len(recent_ids)} IDs de ofertas recientes para verificación.")

        def is_new(deal: Dict[str, Any]) -> bool:
            deal_id = self.db_manager.generar_id_oferta(deal)
            return deal_id not in recent_ids

        new_deals_by_source = {
            name: [deal for deal in deals if is_new(deal)]
            for name, deals in all_deals.items()
        }

        for name, deals in new_deals_by_source.items():
            self.logger.info(f"Nuevas ofertas de {name}: {len(deals)}")
            
        return new_deals_by_source

    async def _process_new_deals(self, new_deals_by_source: Dict[str, List[Dict[str, Any]]]) -> int:
        """Selecciona, envía y guarda las nuevas ofertas."""
        deals_to_send = self.seleccionar_ofertas_equilibradas(
            *[deals for deals in new_deals_by_source.values()]
        )
        self.logger.info(f"Total de ofertas a enviar: {len(deals_to_send)}")

        sent_deals_count = 0
        for deal in deals_to_send:
            if await self.enviar_oferta_con_reintento(deal):
                await self.db_manager.guardar_oferta(deal)
                sent_deals_count += 1
                self.logger.info(f"Oferta enviada y guardada: {deal['titulo']} - Fuente: {deal['tag']}")
            else:
                self.logger.error(f"No se pudo enviar la oferta después de varios intentos: {deal['titulo']}")
            
            await asyncio.sleep(self.config.SEND_OFFER_INTERVAL_SECONDS)
        
        return sent_deals_count

    async def check_ofertas(self) -> None:
        """
        Orquesta el proceso completo de buscar, filtrar, enviar y limpiar ofertas.
        """
        async with self.lock:
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

    def seleccionar_ofertas_equilibradas(
        self, *listas_de_ofertas: List[List[Dict[str, Any]]]
    ) -> List[Dict[str, Any]]:
        
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
        
    async def enviar_oferta_con_reintento(self, oferta: Dict[str, Any]) -> bool:
        for intento in range(self.config.SEND_OFFER_MAX_RETRIES):
            try:
                mensaje_formateado = self.formatear_mensaje_oferta(oferta)
                if oferta.get('imagen') and oferta['imagen'] != 'No disponible':
                    await self.bot.send_photo(
                        chat_id=self.config.CHANNEL_ID, 
                        photo=oferta['imagen'], 
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
                self.logger.error(f"Error inesperado al enviar oferta '{oferta.get('titulo')}': {e}", exc_info=True)
                return False
        return False

    def formatear_mensaje_oferta(self, oferta: Dict[str, Any]) -> Dict[str, Any]:
        emoji_map = {
            "#DealNews": "📰",
            "#Slickdeals": "🔥",
            "#DealsOfAmerica": "🇺🇸",
        }
        emoji_tag = emoji_map.get(oferta['tag'], '✨')
        
        # Usamos HTML para un formato más rico.
        mensaje = f"{emoji_tag} <b>¡NUEVA OFERTA!</b> {emoji_tag}\n\n"
        mensaje += f"🔥 <b>{oferta['titulo']}</b>\n\n"
        mensaje += f"💰 <b>Precio: {oferta['precio']}</b>\n"

        if oferta.get('precio_original') and oferta['precio_original'] != oferta['precio']:
            mensaje += f"💸 Antes: <del>{oferta['precio_original']}</del>\n"

        if oferta.get('cupon'):
            mensaje += f"\n🎟️ <b>CUPÓN</b>: <code>{oferta['cupon']}</code>\n"

        if oferta.get('info_cupon'):
            info_cupon_texto = oferta['info_cupon'][:250]
            mensaje += f"\nℹ️ <i>Info adicional: {info_cupon_texto}...</i>\n"

        # Crear el botón inline
        keyboard = [[InlineKeyboardButton("🔗 Ver Oferta 🔗", url=oferta['link'])]]
        reply_markup = InlineKeyboardMarkup(keyboard)

        return {
            "text": mensaje,
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
