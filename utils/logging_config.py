import logging
import os
import sys
from logging.handlers import RotatingFileHandler


def setup_logging(config) -> None:
    """Configura logging a fichero rotativo y consola respetando LOG_LEVEL."""
    log_dir = os.path.dirname(config.LOG_FILE)
    if log_dir:
        os.makedirs(log_dir, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    )
    file_handler = RotatingFileHandler(
        config.LOG_FILE,
        maxBytes=5_000_000,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)
    root_logger.setLevel(config.LOG_LEVEL)
    root_logger.addHandler(file_handler)
    root_logger.addHandler(console_handler)

    # Menos ruido de bibliotecas externas.
    for nombre in ("urllib3", "telegram", "httpx", "httpcore", "apscheduler"):
        logging.getLogger(nombre).setLevel(logging.WARNING)

    # El logger del bot respeta el nivel configurado (antes se forzaba DEBUG).
    logging.getLogger("OfertasBot").setLevel(config.LOG_LEVEL)
