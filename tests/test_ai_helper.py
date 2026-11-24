from config import Config
from utils.ai_helper import (
    _INSTRUCCION_GANCHO,
    _INSTRUCCION_PUBLICACION,
    _hay_precio,
    _jerga_forzada,
    _limpiar_gancho,
    _prompt_oferta,
    gancho_respaldo,
    generar_gancho,
    parsear_publicacion,
)


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


def test_rechaza_gancho_cortado_a_mitad():
    assert _limpiar_gancho("Prueba de conexión 123 a solo $") is None
    assert _limpiar_gancho("Una oferta muy buena para") is None


def test_agrega_punto_si_falta():
    assert _limpiar_gancho("Oferta nítida en SSD 1TB") == "Oferta nítida en SSD 1TB."


def test_conserva_gancho_completo():
    assert _limpiar_gancho("Ese SSD está nítido, klk.") == "Ese SSD está nítido, klk."


def test_gancho_con_emoji_final_no_lleva_punto_pegado():
    assert _limpiar_gancho("Ese precio está nítido, míralo 😎.") == "Ese precio está nítido, míralo 😎"
    assert _limpiar_gancho("Ese precio está nítido, míralo 😎") == "Ese precio está nítido, míralo 😎"
    assert _limpiar_gancho("Ese precio está nítido, míralo") == "Ese precio está nítido, míralo."
    assert _limpiar_gancho("Ese precio está nítido, míralo!") == "Ese precio está nítido, míralo!"


# ---------------------------------------------------------------- jerga forzada
def test_jerga_forzada_permite_una_o_dos_palabras():
    assert not _jerga_forzada("Ese SSD está nítido, klk.")
    assert not _jerga_forzada("Klk, mira este precio.")
    assert not _jerga_forzada("Precio de hoy: $249. Venía de $399.")


def test_jerga_forzada_detecta_amontonamiento():
    assert _jerga_forzada(
        "Klk mi hermano, jevi que esto está nítido, manin, un tiguere de oferta."
    )
    assert _jerga_forzada("Jevi, qué vaina tan nítida, klk.")


def test_gancho_con_jerga_amontonada_se_descarta():
    assert (
        _limpiar_gancho("Klk, jevi, eso está nítido, manin, no hay vaina mejor.") is None
    )


def test_publicacion_descarta_gancho_con_jerga_amontonada():
    texto = (
        "TITULO: Audífonos Sony WH-1000XM5 con cancelación de ruido\n"
        "GANCHO: Klk, jevi, eso está nítido, manin, no hay vaina mejor."
    )
    assert parsear_publicacion(texto, "Sony WH-1000XM5 Wireless Headphones") is None

    limpio = (
        "TITULO: Audífonos Sony WH-1000XM5 con cancelación de ruido\n"
        "GANCHO: Bajaron casi 40%, si andabas buscando unos, este es el momento 🎧"
    )
    publicacion = parsear_publicacion(limpio, "Sony WH-1000XM5 Wireless Headphones")
    assert publicacion is not None
    assert publicacion.titulo_es.startswith("Audífonos Sony")


# ---------------------------------------------------------------- precio y descuento
def test_hay_precio_ignora_marcadores_de_ausencia():
    assert _hay_precio("$249.99")
    assert not _hay_precio("No disponible")
    assert not _hay_precio("n/a")
    assert not _hay_precio("   ")
    assert not _hay_precio(None)


def test_prompt_incluye_descuento_calculado():
    prompt = _prompt_oferta("Sony WH-1000XM5 Headphones", "$249.99", "$399.99")
    assert "Producto: Sony WH-1000XM5 Headphones" in prompt
    assert "Precio en oferta: $249.99" in prompt
    assert "Precio original: $399.99" in prompt
    assert "Descuento aproximado: 38%" in prompt


def test_prompt_sin_precio_ni_descuento():
    prompt = _prompt_oferta("Producto raro", "No disponible", None)
    assert "Precio desconocido" in prompt
    assert "Descuento" not in prompt


# ---------------------------------------------------------------- el prompt ya no exige jerga
def test_el_prompt_ya_no_obliga_a_usar_jerga():
    for instruccion in (_INSTRUCCION_GANCHO, _INSTRUCCION_PUBLICACION):
        assert "Usa jerga dominicana natural" not in instruccion
        assert "100% dominicano" not in instruccion
        assert "tigueraje verdadero" not in instruccion
        # Sí conserva la identidad y la prohibición de inventar.
        assert "OPCIONAL" in instruccion
        assert "PROHIBIDO inventar" in instruccion


def test_el_prompt_limita_longitud_y_evita_repetir_el_titulo():
    assert "100 caracteres como máximo" in _INSTRUCCION_GANCHO
    assert "No repitas el nombre del producto" in _INSTRUCCION_GANCHO
    assert "No repitas el TITULO" in _INSTRUCCION_PUBLICACION
