import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
    DATABASE = os.getenv('DATABASE_NAME', 'ofertas.db')
    USER_ID = os.getenv('TELEGRAM_USER_ID')
    OFERTA_COOLDOWN = int(os.getenv('OFERTA_COOLDOWN', 72 * 3600))  # 72 horas por defecto

    # Bot settings
    MAX_OFERTAS_POR_EJECUCION = int(os.getenv('MAX_OFERTAS_POR_EJECUCION', 20))
    LOOP_INTERVAL_SECONDS = int(os.getenv('LOOP_INTERVAL_SECONDS', 1200)) # 20 minutes
    SEND_OFFER_INTERVAL_SECONDS = int(os.getenv('SEND_OFFER_INTERVAL_SECONDS', 5))
    SEND_OFFER_MAX_RETRIES = int(os.getenv('SEND_OFFER_MAX_RETRIES', 3))
    SEND_OFFER_RETRY_SLEEP_SECONDS = int(os.getenv('SEND_OFFER_RETRY_SLEEP_SECONDS', 5))

    # Database settings
    DIAS_LIMPIEZA_OFERTAS_ANTIGUAS = int(os.getenv('DIAS_LIMPIEZA_OFERTAS_ANTIGUAS', 30))

    # Logging settingss
    LOG_LEVEL = os.getenv('LOG_LEVEL', 'INFO').upper()
    LOG_FILE = os.getenv('LOG_FILE', 'logs/bot.log')


    SCRAPERS = [
        {
            "module": "scrapers.slickdeals_scraper",
            "class": "SlickdealsScraper",
            "name": "slickdeals",
            "url": os.getenv('SLICKDEALS_URL', 'https://slickdeals.net/'),
            "tag": "#Slickdeals",
            "enabled": True
        },
        {
            "module": "scrapers.dealnews_scraper",
            "class": "DealsnewsScraper",
            "name": "dealnews",
            "url": os.getenv('DEALSNEWS_URL', 'https://www.dealnews.com/'),
            "tag": "#DealNews",
            "enabled": True
        },
        {
            "module": "scrapers.dealsofamerica_scraper",
            "class": "DealsOfAmericaScraper",
            "name": "dealsofamerica",
            "url": os.getenv('DEALSOFAMERICA_URL', 'https://www.dealsofamerica.com/'),
            "tag": "#DealsOfAmerica",
            "enabled": True
        }
    ]

    @classmethod
    def validate(cls):
        required_vars = ['TOKEN', 'CHANNEL_ID', 'USER_ID']
        for var in required_vars:
            if not getattr(cls, var):
                raise ValueError(f"La variable de entorno {var} es requerida pero no está configurada.")
