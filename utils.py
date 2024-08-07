import logging
from logging.handlers import RotatingFileHandler
import sys
import os

def setup_logging():
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file = os.path.join(log_dir, 'bot_log.txt')
    file_handler = RotatingFileHandler(log_file, maxBytes=5000000, backupCount=3)
    console_handler = logging.StreamHandler(sys.stdout)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[file_handler, console_handler]
    )

    # Reducir la verbosidad de los logs de bibliotecas externas
    logging.getLogger('urllib3').setLevel(logging.ERROR)
    logging.getLogger('telegram').setLevel(logging.ERROR)
    logging.getLogger('httpx').setLevel(logging.ERROR)
    logging.getLogger('httpcore').setLevel(logging.ERROR)
    
    # Configurar el logger principal del bot
    logger = logging.getLogger('OfertasBot')
    logger.setLevel(logging.INFO)

    # Filtro personalizado para reducir los warnings de timestamp inválidos
    class TimestampFilter(logging.Filter):
        def filter(self, record):
            return "Timestamp inválido" not in record.getMessage()

    logger.addFilter(TimestampFilter())
