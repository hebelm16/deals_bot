import httpx
import respx

from utils import ai_helper


def _respuesta_modelos():
    return {
        "models": [
            {"name": "models/gemini-2.5-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.5-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3.8-flash", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/gemini-3-flash-preview", "supportedGenerationMethods": ["generateContent"]},
            {"name": "models/text-embedding-004", "supportedGenerationMethods": ["embedContent"]},
            {"name": "models/imagen-4", "supportedGenerationMethods": ["generateContent"]},
        ]
    }


def _reset_cache(monkeypatch):
    monkeypatch.setattr(ai_helper, "_modelos_descubiertos", [])
    monkeypatch.setattr(ai_helper, "_modelos_cache_ts", 0.0)
    monkeypatch.setattr(ai_helper, "_modelos_intento_ts", 0.0)


@respx.mock
async def test_descubre_modelos_y_ordena_por_version(monkeypatch):
    _reset_cache(monkeypatch)
    respx.get("https://generativelanguage.googleapis.com/v1beta/models").mock(
        return_value=httpx.Response(200, json=_respuesta_modelos())
    )

    modelos = await ai_helper.descubrir_modelos_gemini(["clave"])

    assert modelos[0] == "gemini-3.8-flash"
    assert "gemini-3.5-flash" in modelos
    assert "text-embedding-004" not in modelos
    assert "imagen-4" not in modelos


@respx.mock
async def test_cachea_la_lista_de_modelos(monkeypatch):
    _reset_cache(monkeypatch)
    ruta = respx.get("https://generativelanguage.googleapis.com/v1beta/models").mock(
        return_value=httpx.Response(200, json=_respuesta_modelos())
    )

    await ai_helper.descubrir_modelos_gemini(["clave"])
    await ai_helper.descubrir_modelos_gemini(["clave"])

    assert ruta.call_count == 1


@respx.mock
async def test_si_falla_el_listado_usa_lista_vacia(monkeypatch):
    _reset_cache(monkeypatch)
    respx.get("https://generativelanguage.googleapis.com/v1beta/models").mock(
        return_value=httpx.Response(403)
    )

    assert await ai_helper.descubrir_modelos_gemini(["clave"]) == []
