import asyncio
import logging
from datetime import datetime
from typing import List, Dict, Any

from config import Config
from db_manager import DBManager
from scraper import SlickdealsScraper, DealsnewsScraper
from telegram_bot import TelegramBot

class OfertasBot:
    def __init__(self):
        self.config = Config()
        self.db_manager = DBManager(self.config.DATABASE)
        self.telegram_bot = TelegramBot(self.config.TOKEN, self.config.CHANNEL_ID)
        self.fuentes = {
            'slickdeals': {'url': self.config.SLICKDEALS_URL, 'tag': "#Slickdeals", 'habilitado': True},
            'dealnews': {'url': self.config.DEALSNEWS_URL, 'tag': "#DealNews", 'habilitado': True}
        }
        self.scrapers = self.init_scrapers()

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

        ofertas_enviadas = self.db_manager.cargar_ofertas_enviadas()
        nuevas_ofertas = self.filtrar_nuevas_ofertas(todas_las_ofertas, ofertas_enviadas)
        
        logging.info(f"Se encontraron {len(nuevas_ofertas)} nuevas ofertas para enviar")
        
        for oferta in nuevas_ofertas[:10]:  # Limitamos a 10 ofertas nuevas por revisión
            try:
                logging.debug(f"Intentando enviar oferta: {oferta['titulo']}")
                await self.telegram_bot.enviar_oferta(oferta)
                self.db_manager.guardar_oferta(oferta)
                logging.info(f"Oferta enviada y guardada: {oferta['titulo']}")
            except Exception as e:
                logging.error(f"Error al enviar oferta individual: {e}", exc_info=True)

        self.db_manager.limpiar_ofertas_antiguas()
        logging.info(f"Se enviaron {len(nuevas_ofertas[:10])} nuevas ofertas.")

    def filtrar_nuevas_ofertas(self, ofertas: List[Dict[str, Any]], ofertas_enviadas: Dict[str, Any]) -> List[Dict[str, Any]]:
        nuevas_ofertas = []
        for oferta in ofertas:
            if oferta['id'] not in ofertas_enviadas:
                nuevas_ofertas.append(oferta)
        return nuevas_ofertas

    async def run(self) -> None:
        while True:
            try:
                await self.check_ofertas()
                await asyncio.sleep(1800)  # Espera 30 minutos
            except Exception as e:
                logging.error(f"Se produjo un error en el ciclo principal: {e}", exc_info=True)
                await asyncio.sleep(60)