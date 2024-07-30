import logging
from logging.handlers import RotatingFileHandler
import sys
import os

def setup_logging():
    log_dir = 'logs'
    if not os.path.exists(log_dir):
        os.makedirs(log_dir)

    log_file = os.path.join(log_dir, 'bot_log.txt')
    file_handler = RotatingFileHandler(log_file, maxBytes=10000000, backupCount=5)
    console_handler = logging.StreamHandler(sys.stdout)

    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[file_handler, console_handler]
    )

    logging.getLogger('urllib3').setLevel(logging.WARNING)
    logging.getLogger('telegram').setLevel(logging.WARNING)
    logging.getLogger('httpx').setLevel(logging.WARNING)
    logging.getLogger('httpcore').setLevel(logging.WARNING)
    
    logging.getLogger('OfertasBot').setLevel(logging.DEBUG)
