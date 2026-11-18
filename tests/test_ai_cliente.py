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

    async def sin_descubrimiento(_keys):
        return []

    monkeypatch.setattr(ai_helper, "descubrir_modelos_gemini", sin_descubrimiento)


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


async def test_prefiere_gemini_3_6_flash(monkeypatch):
    usados: list[str] = []

    class ModelosGrabadores:
        async def generate_content(self, **kwargs):
            usados.append(kwargs["model"])
            return _Respuesta()

    monkeypatch.setattr(Config, "GEMINI_API_KEYS", "clave-falsa")
    monkeypatch.setattr(Config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(Config, "GEMINI_API_KEY_BACKUP", "")
    monkeypatch.setattr(Config, "GROQ_API_KEY", "")
    monkeypatch.setattr(
        ai_helper,
        "genai",
        SimpleNamespace(
            Client=lambda api_key=None: SimpleNamespace(
                aio=SimpleNamespace(models=ModelosGrabadores())
            )
        ),
    )
    monkeypatch.setattr(ai_helper, "_cache", {})

    async def descubiertos(_keys):
        return ["gemini-3.8-flash", "gemini-3.6-flash", "gemini-3-flash"]

    monkeypatch.setattr(ai_helper, "descubrir_modelos_gemini", descubiertos)

    await ai_helper.generar_gancho_ia("SSD 1TB", "$50", "$100")
    assert usados[0] == "gemini-3.6-flash"


async def test_cuota_diaria_pone_la_clave_en_pausa_larga(monkeypatch):
    import time

    class Modelos:
        async def generate_content(self, **kwargs):
            raise RuntimeError(
                "429 RESOURCE_EXHAUSTED. quota exceeded: "
                "GenerateRequestsPerDayPerProjectPerModel-FreeTier"
            )

    monkeypatch.setattr(Config, "GEMINI_API_KEYS", "clave-cuota")
    monkeypatch.setattr(Config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(Config, "GEMINI_API_KEY_BACKUP", "")
    monkeypatch.setattr(Config, "GROQ_API_KEY", "")
    monkeypatch.setattr(
        ai_helper,
        "genai",
        SimpleNamespace(
            Client=lambda api_key=None: SimpleNamespace(
                aio=SimpleNamespace(models=Modelos())
            )
        ),
    )
    monkeypatch.setattr(ai_helper, "_cache", {})
    monkeypatch.setattr(ai_helper, "_key_cooldowns", {})

    async def sin_descubrimiento(_keys):
        return []

    monkeypatch.setattr(ai_helper, "descubrir_modelos_gemini", sin_descubrimiento)

    assert await ai_helper.generar_gancho_ia("SSD 1TB", "$50", "$100") is None
    restante = ai_helper._key_cooldowns["clave-cuota"] - time.time()
    assert restante > 1000


async def test_clave_en_pausa_larga_va_directo_a_groq_sin_dormir(monkeypatch):
    import time

    dormido = []

    async def dormir_falso(segundos):
        dormido.append(segundos)

    async def groq_falso(prompt, instruccion, parser=None):
        return "Ese precio está nítido, míralo."

    monkeypatch.setattr(Config, "GEMINI_API_KEYS", "clave-pausada")
    monkeypatch.setattr(Config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(Config, "GEMINI_API_KEY_BACKUP", "")
    monkeypatch.setattr(ai_helper, "genai", SimpleNamespace(Client=lambda api_key=None: None))
    monkeypatch.setattr(ai_helper, "_cache", {})
    monkeypatch.setattr(
        ai_helper, "_key_cooldowns", {"clave-pausada": time.time() + 1800}
    )
    monkeypatch.setattr(ai_helper.asyncio, "sleep", dormir_falso)
    monkeypatch.setattr(ai_helper, "fallback_groq", groq_falso)

    async def sin_descubrimiento(_keys):
        return []

    monkeypatch.setattr(ai_helper, "descubrir_modelos_gemini", sin_descubrimiento)

    assert await ai_helper.generar_gancho_ia("SSD 1TB", "$50", "$100")
    assert dormido == []


async def test_429_en_un_modelo_prueba_el_siguiente_modelo(monkeypatch):
    usados: list[str] = []

    class Modelos:
        async def generate_content(self, **kwargs):
            usados.append(kwargs["model"])
            if kwargs["model"] == "gemini-3.6-flash":
                raise RuntimeError("429 RESOURCE_EXHAUSTED. quota exceeded")
            return _Respuesta()

    monkeypatch.setattr(Config, "GEMINI_API_KEYS", "clave-a")
    monkeypatch.setattr(Config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(Config, "GEMINI_API_KEY_BACKUP", "")
    monkeypatch.setattr(Config, "GROQ_API_KEY", "")
    monkeypatch.setattr(
        Config,
        "gemini_model_preferidos",
        classmethod(lambda cls: ["gemini-3.6-flash", "gemini-3.1-flash-lite"]),
    )
    monkeypatch.setattr(
        ai_helper,
        "genai",
        SimpleNamespace(
            Client=lambda api_key=None: SimpleNamespace(
                aio=SimpleNamespace(models=Modelos())
            )
        ),
    )
    monkeypatch.setattr(ai_helper, "_cache", {})
    monkeypatch.setattr(ai_helper, "_key_cooldowns", {})
    monkeypatch.setattr(ai_helper, "_modelo_cooldowns", {})

    async def sin_descubrimiento(_keys):
        return []

    monkeypatch.setattr(ai_helper, "descubrir_modelos_gemini", sin_descubrimiento)

    assert await ai_helper.generar_gancho_ia("SSD 1TB", "$50", "$100")
    assert "gemini-3.1-flash-lite" in usados

    # La siguiente oferta ya no pierde tiempo con el modelo sin cuota.
    usados.clear()
    assert await ai_helper.generar_gancho_ia("TV 4K", "$300", "$500")
    assert usados and "gemini-3.6-flash" not in usados


async def test_modelo_preferido_se_prueba_antes_que_los_descubiertos(monkeypatch):
    usados: list[str] = []

    class Modelos:
        async def generate_content(self, **kwargs):
            usados.append(kwargs["model"])
            if kwargs["model"] != "gemini-3.1-flash-lite":
                raise RuntimeError("429 RESOURCE_EXHAUSTED. quota exceeded")
            return _Respuesta()

    monkeypatch.setattr(Config, "GEMINI_API_KEYS", "clave-orden")
    monkeypatch.setattr(Config, "GEMINI_API_KEY", "")
    monkeypatch.setattr(Config, "GEMINI_API_KEY_BACKUP", "")
    monkeypatch.setattr(Config, "GROQ_API_KEY", "")
    monkeypatch.setattr(
        Config, "gemini_model_preferidos", classmethod(lambda cls: ["gemini-3.6-flash"])
    )
    monkeypatch.setattr(
        Config,
        "gemini_models",
        classmethod(lambda cls: ["gemini-3.6-flash", "gemini-3.1-flash-lite"]),
    )
    monkeypatch.setattr(
        ai_helper,
        "genai",
        SimpleNamespace(
            Client=lambda api_key=None: SimpleNamespace(
                aio=SimpleNamespace(models=Modelos())
            )
        ),
    )
    for nombre in ("_cache", "_key_cooldowns", "_modelo_cooldowns"):
        monkeypatch.setattr(ai_helper, nombre, {})

    async def descubiertos(_keys):
        return ["gemini-3.5-flash-lite", "gemini-3.1-flash-lite", "gemini-3.6-flash"]

    monkeypatch.setattr(ai_helper, "descubrir_modelos_gemini", descubiertos)

    assert await ai_helper.generar_gancho_ia("SSD 1TB", "$50", "$100")
    # El respaldo configurado va antes que lo que solo descubrió la API.
    assert usados.index("gemini-3.1-flash-lite") < (
        usados.index("gemini-3.5-flash-lite")
        if "gemini-3.5-flash-lite" in usados
        else 99
    )
    assert usados[-1] == "gemini-3.1-flash-lite"


def test_gemini_3_usa_thinking_level_y_no_budget():
    cfg = ai_helper._config_para_modelo("gemini-3.1-flash-lite", "sistema", True)
    assert cfg.thinking_config.thinking_level is not None
    assert not cfg.thinking_config.thinking_budget
    cfg25 = ai_helper._config_para_modelo("gemini-2.5-flash", "sistema", True)
    assert cfg25.thinking_config.thinking_budget == 0
