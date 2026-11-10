from types import SimpleNamespace

from bot.ofertas_bot import OfertasBot
from config import Config
from database.db_manager import DBManager


class FakeUpdater:
    def __init__(self, falla_webhook: bool = False):
        self.falla_webhook = falla_webhook
        self.running = False
        self.webhook_iniciado = False
        self.polling_iniciado = False

    async def start_webhook(self, **kwargs):
        self.webhook_iniciado = True
        if self.falla_webhook:
            raise RuntimeError("PTB must be installed via [webhooks]")
        self.running = True

    async def start_polling(self, **kwargs):
        self.polling_iniciado = True
        self.running = True

    async def stop(self):
        self.running = False


class FakeBot:
    async def delete_webhook(self, **kwargs):
        return True


def crear_bot(tmp_path, updater: FakeUpdater) -> OfertasBot:
    config = Config()
    config.TOKEN = "123456:ABC"
    config.USE_WEBHOOKS = True
    config.WEBHOOK_URL = "https://ejemplo.up.railway.app"
    config.PORT = 8443
    bot = OfertasBot(
        config=config,
        db_manager=DBManager(str(tmp_path / "webhook.db")),
        scrapers={},
    )
    bot.bot = FakeBot()
    bot.application = SimpleNamespace(updater=updater)
    return bot


async def test_webhook_inicia_cuando_esta_disponible(tmp_path):
    updater = FakeUpdater()
    bot = crear_bot(tmp_path, updater)

    await bot._iniciar_red()

    assert updater.webhook_iniciado is True
    assert updater.polling_iniciado is False


async def test_webhook_cae_a_polling_si_falla(tmp_path):
    updater = FakeUpdater(falla_webhook=True)
    bot = crear_bot(tmp_path, updater)

    await bot._iniciar_red()

    assert updater.webhook_iniciado is True
    assert updater.polling_iniciado is True
