import asyncio
import logging
from bot.ofertas_bot import OfertasBot
from utils.logging_config import setup_logging
from config import Config

def main():
    """
    Punto de entrada principal de la aplicación.
    Configura el logging, inicializa y ejecuta el bot.
    """
    config = Config()
    setup_logging(config)
    
    bot = OfertasBot()
    
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logging.getLogger("OfertasBot").info("Bot detenido manualmente por el usuario.")
    except Exception as e:
        logging.getLogger("OfertasBot").critical(
            f"Error fatal no capturado en el nivel superior: {e}", exc_info=True
        )

if __name__ == "__main__":
    main()
