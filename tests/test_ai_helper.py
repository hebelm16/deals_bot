from config import Config
from utils.ai_helper import gancho_respaldo, generar_gancho


def _sin_ia(monkeypatch):
    for variable in (
        "GEMINI_API_KEYS",
        "GEMINI_API_KEY",
        "GEMINI_API_KEY_BACKUP",
        "GROQ_API_KEY",
    ):
        monkeypatch.setattr(Config, variable, "")


async def test_gancho_de_respaldo_cuando_no_hay_ia(monkeypatch):
    _sin_ia(monkeypatch)
    gancho = await generar_gancho("SSD 1TB", "$50", "$100", requerido=False)
    assert gancho is not None
    assert "$50" in gancho
    assert "$100" in gancho


async def test_gancho_obligatorio_devuelve_none_sin_ia(monkeypatch):
    _sin_ia(monkeypatch)
    assert await generar_gancho("SSD 1TB", "$50", "$100", requerido=True) is None


def test_plantilla_con_precio_sin_original():
    assert "$25" in gancho_respaldo("Producto", "$25", None)


def test_plantilla_sin_precio():
    assert gancho_respaldo("Producto interesante", "No disponible", None)
