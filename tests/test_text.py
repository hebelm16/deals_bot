from utils.text import limpiar_info, limpiar_titulo, resumen_info


def test_quita_precio_y_shipping_del_titulo():
    assert (
        limpiar_titulo("Energy ESW-C8 Subwoofer $109 + Free S&H")
        == "Energy ESW-C8 Subwoofer"
    )
    assert (
        limpiar_titulo(
            "13.6-Oz Velveeta Skillets One Pan Dinner Kit Chicken Broccoli "
            "$2.50 w/ S&S & More"
        )
        == "13.6-Oz Velveeta Skillets One Pan Dinner Kit Chicken Broccoli"
    )
    assert (
        limpiar_titulo("Wurkos TD07 1300 Lumen Tactical Flashlight w/ 18350 Battery $12.55 + Free S&H")
        == "Wurkos TD07 1300 Lumen Tactical Flashlight w/ 18350 Battery"
    )


def test_quita_prefijo_de_tienda_y_varios_precios():
    titulo = (
        "Select Costco Stores: Samsung S90F OLED 4K 120Hz Vision AI Smart TV: "
        '65" $800; 55" $500 (Pricing/Availability May Vary)'
    )
    limpio = limpiar_titulo(titulo)
    assert limpio.startswith("Samsung S90F OLED")
    assert "$800" not in limpio


def test_titulo_largo_se_recorta():
    assert len(limpiar_titulo("Producto " * 50)) <= 120


def test_info_elimina_urls_y_creditos():
    info = (
        "Amazon has the kit for $2.97 - 10% off when you clip the coupon. "
        "https://www.amazon.com/dp/ABC Thanks to Community Member ctscd"
    )
    limpio = limpiar_info(info)
    assert limpio is not None
    assert "http" not in limpio
    assert "Thanks to" not in limpio
    assert "coupon" in limpio


def test_info_solo_url_se_descarta():
    assert limpiar_info("https://www.walmart.com/ip/Marvel/9588107827") is None


def test_info_sin_utilidad_se_descarta():
    assert limpiar_info("Producto disponible en tienda") is None


def test_resumen_info_etiquetas_cortas():
    assert resumen_info("Free shipping on orders over $35") == "Envío gratis"
    assert resumen_info("Available for store pickup only") == "Pickup en tienda"
    assert resumen_info("Clip the coupon on the product page") == "Cupón en la página"
    assert resumen_info("Free shipping and in-store pickup") == (
        "Envío gratis · Pickup en tienda"
    )
    assert resumen_info("Texto sin datos útiles") is None
