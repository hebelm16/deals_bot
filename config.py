import logging
import os

from dotenv import load_dotenv

load_dotenv()


def _env_bool(name: str, default: bool = False) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "yes", "on", "t")


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not str(value).strip():
        return default
    try:
        return int(value)
    except ValueError:
        logging.getLogger("OfertasBot").warning(
            "Valor no numérico para %s=%r; se usa %s", name, value, default
        )
        return default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not str(value).strip():
        return default
    try:
        return float(value)
    except ValueError:
        return default


class Config:
    # Telegram
    TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
    CHANNEL_ID = os.getenv("TELEGRAM_CHANNEL_ID")
    USER_ID = os.getenv("TELEGRAM_USER_ID")

    # Persistencia
    DATABASE = os.getenv("DATABASE") or os.getenv("DATABASE_NAME") or "ofertas.db"

    # Ritmo de publicación
    MAX_OFERTAS_POR_EJECUCION = _env_int("MAX_OFERTAS_POR_EJECUCION", 20)
    LOOP_INTERVAL_SECONDS = _env_int("LOOP_INTERVAL_SECONDS", 7200)
    SEND_OFFER_INTERVAL_SECONDS = _env_int("SEND_OFFER_INTERVAL_SECONDS", 8)
    SEND_OFFER_MAX_RETRIES = _env_int("SEND_OFFER_MAX_RETRIES", 3)
    SEND_OFFER_RETRY_SLEEP_SECONDS = _env_int("SEND_OFFER_RETRY_SLEEP_SECONDS", 5)
    CYCLE_TIMEOUT_SECONDS = _env_int("CYCLE_TIMEOUT_SECONDS", 600)
    SCRAPER_TIMEOUT_SECONDS = _env_int("SCRAPER_TIMEOUT_SECONDS", 60)

    # IA
    GEMINI_API_KEYS = os.getenv("GEMINI_API_KEYS", "")
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    GEMINI_API_KEY_BACKUP = os.getenv("GEMINI_API_KEY_BACKUP", "")
    GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
    GROQ_MODEL = os.getenv("GROQ_MODEL", "openai/gpt-oss-20b")
    AI_HOOK_REQUIRED = _env_bool("AI_HOOK_REQUIRED", False)
    AI_HOOK_TIMEOUT_SECONDS = _env_int("AI_HOOK_TIMEOUT_SECONDS", 45)
    GEMINI_CALL_TIMEOUT_SECONDS = _env_int("GEMINI_CALL_TIMEOUT_SECONDS", 8)
    GROQ_CALL_TIMEOUT_SECONDS = _env_int("GROQ_CALL_TIMEOUT_SECONDS", 20)

    # Imágenes: si Telegram no puede descargar la URL, se baja y se sube el fichero.
    DESCARGAR_IMAGENES = _env_bool("DESCARGAR_IMAGENES", True)
    IMAGE_MAX_BYTES = _env_int("IMAGE_MAX_BYTES", 5_000_000)
    IMAGE_TIMEOUT_SECONDS = _env_int("IMAGE_TIMEOUT_SECONDS", 20)
    USAR_PLACEHOLDER = _env_bool("USAR_PLACEHOLDER", True)
    PLACEHOLDER_IMAGE = os.getenv(
        "PLACEHOLDER_IMAGE", "assets/oferta_sin_imagen.jpg"
    )

    # Telegram polling / webhook
    TELEGRAM_POLLING_TIMEOUT = _env_int("TELEGRAM_POLLING_TIMEOUT", 30)
    TELEGRAM_POLLING_INTERVAL = _env_float("TELEGRAM_POLLING_INTERVAL", 0.0)
    USE_WEBHOOKS = _env_bool("USE_WEBHOOKS", False)
    WEBHOOK_URL = os.getenv("WEBHOOK_URL", "").rstrip("/")
    WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "")
    PORT = _env_int("PORT", 8443)
    HEALTH_PORT = _env_int("HEALTH_PORT", 0)

    # Alertas y usuarios
    MAX_ALERTAS_POR_USUARIO = _env_int("MAX_ALERTAS_POR_USUARIO", 20)
    KEYWORD_MIN_LENGTH = _env_int("KEYWORD_MIN_LENGTH", 2)
    KEYWORD_MAX_LENGTH = _env_int("KEYWORD_MAX_LENGTH", 64)
    ALERT_SEND_INTERVAL_SECONDS = _env_float("ALERT_SEND_INTERVAL_SECONDS", 0.4)

    # Operación
    HEARTBEAT_INTERVAL_SECONDS = _env_int("HEARTBEAT_INTERVAL_SECONDS", 3600)
    HEARTBEAT_MAX_HOURS = _env_int("HEARTBEAT_MAX_HOURS", 6)
    DIAS_LIMPIEZA_OFERTAS_ANTIGUAS = _env_int("DIAS_LIMPIEZA_OFERTAS_ANTIGUAS", 30)
    LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
    LOG_FILE = os.getenv("LOG_FILE", "logs/bot.log")

    SCRAPERS = [
        {
            "module": "scrapers.slickdeals_scraper",
            "class": "SlickdealsScraper",
            "name": "slickdeals",
            # Feed RSS público (FeedBurner): la web de Slickdeals responde 403 a bots.
            "url": os.getenv(
                "SLICKDEALS_URL", "https://feeds.feedburner.com/SlickdealsnetFP"
            ),
            "tag": "#Slickdeals",
            "enabled": True,
        },
        {
            "module": "scrapers.dealnews_scraper",
            "class": "DealsnewsScraper",
            "name": "dealnews",
            "url": os.getenv("DEALSNEWS_URL", "https://www.dealnews.com/"),
            "tag": "#DealNews",
            "enabled": True,
        },
        {
            "module": "scrapers.dealsofamerica_scraper",
            "class": "DealsOfAmericaScraper",
            "name": "dealsofamerica",
            "url": os.getenv("DEALSOFAMERICA_URL", "https://www.dealsofamerica.com/"),
            "tag": "#DealsOfAmerica",
            "enabled": True,
        },
    ]

    @classmethod
    def gemini_model_preferidos(cls) -> list[str]:
        """Modelo principal elegido para el canal y alternativas de respaldo."""
        raw = (
            os.getenv("GEMINI_MODEL_PREFERIDOS")
            or os.getenv("GEMINI_MODEL")
            or "gemini-3-flash-preview"
        )
        modelos = []
        for modelo in raw.split(","):
            modelo = modelo.strip()
            if modelo and modelo not in modelos:
                modelos.append(modelo)
        return modelos

    @classmethod
    def gemini_models(cls) -> list[str]:
        raw = (
            os.getenv("GEMINI_MODELS")
            or os.getenv("GEMINI_MODEL")
            or "gemini-3-flash-preview,gemini-3-flash,gemini-3.6-flash,"
            "gemini-3.5-flash,gemini-3.7-flash,gemini-3.8-flash"
        )
        models = []
        for model in raw.split(","):
            model = model.strip()
            if model and model not in models:
                models.append(model)
        return models

    @classmethod
    def has_ai(cls) -> bool:
        keys = cls.GEMINI_API_KEYS or cls.GEMINI_API_KEY or cls.GEMINI_API_KEY_BACKUP
        return bool(keys or cls.GROQ_API_KEY)

    @classmethod
    def validate(cls) -> None:
        """Valida la configuración mínima al arrancar y avisa de degradaciones."""
        missing = [
            name
            for name in ("TOKEN", "CHANNEL_ID", "USER_ID")
            if not getattr(cls, name)
        ]
        if missing:
            raise ValueError(
                "Faltan variables de entorno obligatorias: " + ", ".join(missing)
            )

        if cls.USE_WEBHOOKS and not cls.WEBHOOK_URL:
            raise ValueError("USE_WEBHOOKS=true requiere WEBHOOK_URL")

        if cls.AI_HOOK_REQUIRED and not cls.has_ai():
            raise ValueError(
                "AI_HOOK_REQUIRED=true requiere GEMINI_* o GROQ_API_KEY"
            )

        logger = logging.getLogger("OfertasBot")
        if not cls.has_ai():
            logger.warning(
                "No hay proveedor de IA configurado: las ofertas se publicarán "
                "con gancho de plantilla. Define GEMINI_API_KEY/GEMINI_API_KEYS "
                "o GROQ_API_KEY para usar IA."
            )
        if cls.USAR_PLACEHOLDER and not os.path.exists(cls.PLACEHOLDER_IMAGE):
            logger.warning(
                "No existe la imagen de respaldo %s; las ofertas sin foto se "
                "publicarán como texto.",
                cls.PLACEHOLDER_IMAGE,
            )
