import logging
from logging.handlers import RotatingFileHandler
import sys
import os

def setup_logging():
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file = os.path.join(log_dir, 'bot_log.txt')
    file_handler = RotatingFileHandler(log_file, maxBytes=5000000, backupCount=5)
    console_handler = logging.StreamHandler(sys.stdout)

    formatter = logging.Formatter('%(asctime)s - %(name)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.INFO)
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
