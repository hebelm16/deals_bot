"""Pruebas del camino de IA con un cliente falso (sin red)."""

from types import SimpleNamespace

import pytest

from config import Config
from utils import ai_helper


class _Respuesta:
    text = "Oferta nítida, aprovecha ese precio."


class _Modelos:
    async def generate_content(self, **kwargs):
        return _Respuesta()


class _Aio:
    models = _Modelos()


class _ClienteFalso:
    def __init__(self, api_key=None):
        self.api_key = api_key
        self.aio = _Aio()


@pytest.fixture
def gemini_falso(monkeypatch):
    monkeypatch.setattr(Config, "GEMINI_API_KEYS", "clave-falsa")
    monkeypatch.setattr(Config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(Config, "GEMINI_API_KEY_BACKUP", "")
    monkeypatch.setattr(Config, "GROQ_API_KEY", "")
    monkeypatch.setattr(ai_helper, "genai", SimpleNamespace(Client=_ClienteFalso))
    monkeypatch.setattr(ai_helper, "_cache", {})


async def test_generar_gancho_con_cliente_falso(gemini_falso):
    gancho = await ai_helper.generar_gancho_ia("SSD 1TB", "$50", "$100")
    assert gancho == "Oferta nítida, aprovecha ese precio."


async def test_generar_gancho_usa_cache(gemini_falso, monkeypatch):
    llamadas = {"n": 0}

    class ModelosContador(_Modelos):
        async def generate_content(self, **kwargs):
            llamadas["n"] += 1
            return _Respuesta()

    monkeypatch.setattr(
        ai_helper,
        "genai",
        SimpleNamespace(Client=lambda api_key=None: SimpleNamespace(
            aio=SimpleNamespace(models=ModelosContador())
        )),
    )
    primero = await ai_helper.generar_gancho_ia("TV 4K", "$300", "$500")
    segundo = await ai_helper.generar_gancho_ia("TV 4K", "$300", "$500")
    assert primero == segundo
    assert llamadas["n"] == 1
