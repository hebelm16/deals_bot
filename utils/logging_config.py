import logging
from logging.handlers import RotatingFileHandler
import sys
import os

def setup_logging(config):
    log_dir = os.path.dirname(config.LOG_FILE)
    if log_dir and not os.path.exists(log_dir):
        os.makedirs(log_dir)

    file_handler = RotatingFileHandler(config.LOG_FILE, maxBytes=5000000, backupCount=5)
    console_handler = logging.StreamHandler(sys.stdout)

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(config.LOG_LEVEL)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Reducir la verbosidad de los logs de bibliotecas externas
    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('telegram').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    
    # Configurar el logger principal del bot
    bot_logger = logging.getLogger('OfertasBot')
    bot_logger.setLevel(logging.DEBUG)

    # Filtro personalizado para reducir los warnings de timestamp inválidos
    class TimestampFilter(logging.Filter):
        def filter(self, record):
            return "Timestamp inválido" not in record.getMessage()

    bot_logger.addFilter(TimestampFilter())
