import asyncio
import logging
from ofertasbot import OfertasBot

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

if __name__ == "__main__":
    bot = OfertasBot()
    asyncio.run(bot.run())