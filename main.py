import asyncio
import logging

from bot.ofertas_bot import OfertasBot
from config import Config
from utils.logging_config import setup_logging


def main() -> int:
    """Punto de entrada: valida configuración, arranca el bot y cierra limpio."""
    config = Config()
    setup_logging(config)
    logger = logging.getLogger("OfertasBot")

    try:
        config.validate()
    except ValueError as exc:
        logger.critical("Configuración inválida: %s", exc)
        return 1

    bot = OfertasBot(config=config)
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        logger.info("Bot detenido manualmente por el usuario.")
    except Exception as exc:  # noqa: BLE001 - último cortafuegos
        logger.critical("Error fatal no capturado: %s", exc, exc_info=True)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
