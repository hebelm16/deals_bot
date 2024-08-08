import asyncio
from bot.ofertas_bot import OfertasBot
from utils.logging_config import setup_logging

def main():
    setup_logging()
    bot = OfertasBot()
    
    async def run_bot():
        try:
            await bot.run()
        except Exception as e:
            bot.logger.error(f"Error en la ejecución del bot: {e}", exc_info=True)
        finally:
            await bot.stop()

    asyncio.run(run_bot())

if __name__ == "__main__":
    main()
