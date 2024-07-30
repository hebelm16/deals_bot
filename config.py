import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    TOKEN = os.getenv('TELEGRAM_BOT_TOKEN')
    CHANNEL_ID = os.getenv('TELEGRAM_CHANNEL_ID')
    DATABASE = os.getenv('DATABASE_NAME', 'ofertas.db')
    USER_ID = os.getenv('TELEGRAM_USER_ID')
    SLICKDEALS_URL = os.getenv('SLICKDEALS_URL', 'https://slickdeals.net/')
    DEALSNEWS_URL = os.getenv('DEALSNEWS_URL', 'https://www.dealnews.com/')
    OFERTA_COOLDOWN = int(os.getenv('OFERTA_COOLDOWN', 72 * 3600))  # 72 horas por defecto
