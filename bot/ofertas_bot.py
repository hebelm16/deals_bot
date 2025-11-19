import asyncio
import logging
from typing import List, Dict, Any
from telegram import Bot
from telegram.ext import Application
from telegram.error import NetworkError, RetryAfter, Conflict
import random
import os
import time
from telegram import InlineKeyboardButton, InlineKeyboardMarkup
from filelock import FileLock, Timeout

from config import Config
from database.db_manager import DBManager
from scrapers.slickdeals_scraper import SlickdealsScraper
from scrapers.dealnews_scraper import DealsnewsScraper
from scrapers.dealsofamerica_scraper import DealsOfAmericaScraper


class OfertasBot:
    def __init__(self):
        self.config = Config()
        self.db_manager = DBManager(self.config.DATABASE)
        self.fuentes = {
            "dealnews": {
                "url": self.config.DEALSNEWS_URL,
                "tag": "#DealNews",
                "habilitado": True,
            },
            "slickdeals": {
                "url": self.config.SLICKDEALS_URL,
                "tag": "#Slickdeals",
                "habilitado": True,
            },
            "dealsofamerica": {
                "url": self.config.DEALSOFAMERICA_URL,
                "tag": "#DealsOfAmerica",
                "habilitado": True,
            },
        }
        self.scrapers = self.init_scrapers()
        self.application = None
        self.bot = None
        self.is_running = True
        self.logger = logging.getLogger("OfertasBot")
        self.lock = asyncio.Lock()
        self.lock_file = "ofertasbot.lock"
        self.max_ofertas_por_ejecucion = 20  # Limitamos a 20 ofertas por ejecución

    def init_scrapers(self) -> List:
        scrapers = []
        if self.fuentes["slickdeals"]["habilitado"]:
            scrapers.append(SlickdealsScraper(
                self.fuentes["slickdeals"]["url"], self.fuentes["slickdeals"]["tag"]
            ))
        if self.fuentes["dealnews"]["habilitado"]:
            scrapers.append(DealsnewsScraper(
                self.fuentes["dealnews"]["url"], self.fuentes["dealnews"]["tag"]
            ))
        if self.fuentes["dealsofamerica"]["habilitado"]:
            scrapers.append(DealsOfAmericaScraper(
                self.fuentes["dealsofamerica"]["url"], self.fuentes["dealsofamerica"]["tag"]
            ))
        return scrapers

    async def run(self) -> None:
        try:
            lock = FileLock(self.lock_file, timeout=0)
            with lock:
                self.logger.info("Bloqueo adquirido exitosamente.")
                self.application = Application.builder().token(self.config.TOKEN).build()
                self.bot = Bot(self.config.TOKEN)
                await self.application.initialize()
                await self.application.start()
                await self.application.updater.start_polling(drop_pending_updates=True)

                while self.is_running:
                    try:
                        await self.check_ofertas()
                    except Exception as e:
                        self.logger.error(
                            f"Error en el ciclo principal: {e}", exc_info=True
                        )
                        await self.enviar_notificacion_error(e)
                    finally:
                        await asyncio.sleep(1800)  # 30 minutos

                await self.application.stop()
                await self.application.shutdown()
        except Timeout:
            self.logger.error("Otra instancia del bot ya está en ejecución. Saliendo.")
            return
        except Exception as e:
            self.logger.critical(f"Error fatal al iniciar el bot: {e}", exc_info=True)
        finally:
            self.logger.info("El bot se ha detenido.")


    async def stop(self) -> None:
        self.is_running = False
        if self.application:
            await self.application.stop()
            await self.application.shutdown()

    async def check_ofertas(self) -> None:
        async with self.lock:
            todas_las_ofertas = {"slickdeals": [], "dealnews": [], "dealsofamerica": []}

            self.logger.info("Iniciando scraping concurrente de todas las fuentes.")
            tasks = []
            for scraper in self.scrapers:
                if isinstance(scraper, DealsOfAmericaScraper):
                    # This scraper is async, so we can call it directly
                    tasks.append(scraper.obtener_ofertas())
                else:
                    # These scrapers are sync, so they run in a thread
                    tasks.append(asyncio.to_thread(scraper.obtener_ofertas))
            
            results = await asyncio.gather(*tasks, return_exceptions=True)
            self.logger.info("Scraping concurrente finalizado.")

            for i, result in enumerate(results):
                scraper = self.scrapers[i]
                scraper_name = scraper.__class__.__name__
                if isinstance(result, Exception):
                    self.logger.error(
                        f"Error al obtener ofertas de {scraper_name}: {result}",
                        exc_info=result,
                    )
                else:
                    self.logger.info(
                        f"Se obtuvieron {len(result)} ofertas de {scraper_name}"
                    )
                    if isinstance(scraper, SlickdealsScraper):
                        todas_las_ofertas["slickdeals"] = result
                    elif isinstance(scraper, DealsnewsScraper):
                        todas_las_ofertas["dealnews"] = result
                    elif isinstance(scraper, DealsOfAmericaScraper):
                        todas_las_ofertas["dealsofamerica"] = result


            nuevas_ofertas_slickdeals = [
                oferta
                for oferta in todas_las_ofertas["slickdeals"]
                if not self.db_manager.es_oferta_repetida(oferta)
            ]
            nuevas_ofertas_dealnews = [
                oferta
                for oferta in todas_las_ofertas["dealnews"]
                if not self.db_manager.es_oferta_repetida(oferta)
            ]
            nuevas_ofertas_dealsofamerica = [
                oferta
                for oferta in todas_las_ofertas["dealsofamerica"]
                if not self.db_manager.es_oferta_repetida(oferta)
            ]

            self.logger.info(
                f"Nuevas ofertas de Slickdeals: {len(nuevas_ofertas_slickdeals)}"
            )
            self.logger.info(
                f"Nuevas ofertas de DealNews: {len(nuevas_ofertas_dealnews)}"
            )
            self.logger.info(
                f"Nuevas ofertas de DealsOfAmerica: {len(nuevas_ofertas_dealsofamerica)}"
            )

            ofertas_a_enviar = self.seleccionar_ofertas_equilibradas(
                nuevas_ofertas_slickdeals,
                nuevas_ofertas_dealnews,
                nuevas_ofertas_dealsofamerica,
            )

            self.logger.info(f"Total de ofertas a enviar: {len(ofertas_a_enviar)}")

            ofertas_enviadas_esta_vez = 0

            for oferta in ofertas_a_enviar:
                if await self.enviar_oferta_con_reintento(oferta):
                    self.db_manager.guardar_oferta(oferta)
                    ofertas_enviadas_esta_vez += 1
                    self.logger.info(
                        f"Oferta enviada y guardada: {oferta['titulo']} - Fuente: {oferta['tag']}"
                    )
                else:
                    self.logger.error(
                        f"No se pudo enviar la oferta después de varios intentos: {oferta['titulo']}"
                    )

                await asyncio.sleep(
                    5
                )  # Espera 5 segundos entre cada envío para evitar flood

            ofertas_antiguas_eliminadas = self.db_manager.limpiar_ofertas_antiguas()

            self.logger.info(f"Resumen de ejecución:")
            self.logger.info(
                f"  - Ofertas enviadas en esta ejecución: {ofertas_enviadas_esta_vez}"
            )
            self.logger.info(
                f"  - Ofertas antiguas eliminadas: {ofertas_antiguas_eliminadas}"
            )

    def seleccionar_ofertas_equilibradas(
        self,
        ofertas_slickdeals: List[Dict[str, Any]],
        ofertas_dealnews: List[Dict[str, Any]],
        ofertas_dealsofamerica: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        total_ofertas = min(
            self.max_ofertas_por_ejecucion,
            len(ofertas_slickdeals)
            + len(ofertas_dealnews)
            + len(ofertas_dealsofamerica),
        )
        tercio = total_ofertas // 3

        ofertas_seleccionadas = []
        # Tomar una porción de cada fuente
        ofertas_seleccionadas.extend(
            random.sample(ofertas_slickdeals, min(tercio, len(ofertas_slickdeals)))
        )
        ofertas_seleccionadas.extend(
            random.sample(ofertas_dealnews, min(tercio, len(ofertas_dealnews)))
        )
        ofertas_seleccionadas.extend(
            random.sample(
                ofertas_dealsofamerica, min(tercio, len(ofertas_dealsofamerica))
            )
        )

        # Si aún no hemos alcanzado el total, completamos con las ofertas restantes
        if len(ofertas_seleccionadas) < total_ofertas:
            ofertas_restantes = (
                ofertas_slickdeals + ofertas_dealnews + ofertas_dealsofamerica
            )
            ofertas_restantes = [
                oferta
                for oferta in ofertas_restantes
                if oferta not in ofertas_seleccionadas
            ]
            ofertas_seleccionadas.extend(
                random.sample(
                    ofertas_restantes,
                    min(
                        total_ofertas - len(ofertas_seleccionadas),
                        len(ofertas_restantes),
                    ),
                )
            )

        random.shuffle(ofertas_seleccionadas)
        return ofertas_seleccionadas

    async def enviar_oferta_con_reintento(self, oferta: Dict[str, Any], max_intentos: int = 3) -> bool:
        for intento in range(max_intentos):
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
                self.logger.error(f"Error al enviar oferta (intento {intento + 1}/{max_intentos}): {e}")
                if intento < max_intentos - 1:
                    await asyncio.sleep(5 * (intento + 1))
            except Exception as e:
                self.logger.error(f"Error inesperado al enviar oferta: {e}", exc_info=True)
                return False
        return False

    def formatear_mensaje_oferta(self, oferta: Dict[str, Any]) -> Dict[str, Any]:
        emoji_map = {
            "#DealNews": "🏷️",
            "#Slickdeals": "🛍️",
            "#DealsOfAmerica": "🇺🇸"
        }
        emoji_tag = emoji_map.get(oferta['tag'], '🔥')
        
        mensaje = f"{emoji_tag} *¡OFERTA ESPECIAL!* {emoji_tag}\n\n"
        mensaje += f"🔥 *{oferta['titulo']}*\n\n"
        mensaje += f"💰 Precio: {oferta['precio']}\n"
        if oferta.get('precio_original'):
            mensaje += f"🏷️ Precio original: {oferta['precio_original']}\n"
        if oferta.get('cupon'):
            mensaje += f"🎟️ Cupón: `{oferta['cupon']}`\n"
        if oferta['tag'] == "#DealNews" and oferta.get('info_cupon'):
            mensaje += f"ℹ️ Info adicional: {oferta['info_cupon']}\n"
        
        # Crear el botón inline
        keyboard = [[InlineKeyboardButton("🔗 Ver Oferta 🔗", url=oferta['link'])]]
        reply_markup = InlineKeyboardMarkup(keyboard)
        
        return {
            "text": mensaje,
            "reply_markup": reply_markup,
            "parse_mode": 'Markdown'
        }

    async def enviar_notificacion_error(self, error: Exception) -> None:
        mensaje = f"🚨 *Error en el bot de ofertas* 🚨\n\n"
        mensaje += f"Detalles del error:\n"
        mensaje += f"`{type(error).__name__}`: `{str(error)}`"
        try:
            await self.bot.send_message(
                chat_id=self.config.CHANNEL_ID, text=mensaje, parse_mode="Markdown"
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
