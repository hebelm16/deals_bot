import pytest
from bs4 import BeautifulSoup

from scrapers.base_scraper import ScraperError
from scrapers.dealnews_scraper import DealsnewsScraper
from scrapers.dealsofamerica_scraper import DealsOfAmericaScraper
from scrapers.slickdeals_scraper import SlickdealsScraper


def test_slickdeals_feed_parser(mock_slickdeals_rss):
    scraper = SlickdealsScraper(
        name="slickdeals", url="https://feeds.feedburner.com/SlickdealsnetFP", tag="#Slickdeals"
    )
    ofertas = scraper.parsear_feed(mock_slickdeals_rss)

    assert len(ofertas) == 2
    primera = ofertas[0]
    assert primera.titulo == 'Laptop MSI 15.6" $799 + Free Shipping'
    assert primera.precio == "$799"
    assert primera.precio_original == "$999"
    assert primera.link == "https://slickdeals.net/f/12345-deal"
    assert primera.imagen == "https://static.slickdealscdn.com/msi.jpg"
    assert primera.cupon == "MSI20"

    segunda = ofertas[1]
    assert segunda.precio == "$49.99"
    assert segunda.precio_original == "$89.99"


def test_slickdeals_recupera_xml_malformado():
    scraper = SlickdealsScraper(
        name="slickdeals", url="https://feeds.feedburner.com/SlickdealsnetFP", tag="#Slickdeals"
    )
    rss = """<?xml version="1.0"?>
    <rss version="2.0"><channel><item>
      <title>TV & Soundbar $100</title>
      <link>https://slickdeals.net/f/1</link>
      <description>Oferta con descuento & envío gratis</description>
    </item></channel></rss>"""

    ofertas = scraper.parsear_feed(rss)

    assert len(ofertas) == 1
    assert "TV & Soundbar" in ofertas[0].titulo
    assert ofertas[0].precio == "$100"


def test_slickdeals_usa_parser_html_si_el_xml_esta_truncado():
    scraper = SlickdealsScraper(
        name="slickdeals", url="https://feeds.feedburner.com/SlickdealsnetFP", tag="#Slickdeals"
    )
    rss = """<rss version="2.0"><channel><item>
      <title>Monitor 27 pulgadas $150</title>
      <link>https://slickdeals.net/f/2</link>
      <description>Buen precio</description>
    </item>"""

    ofertas = scraper.parsear_feed(rss)

    assert len(ofertas) == 1
    assert ofertas[0].precio == "$150"


def test_slickdeals_rechaza_pagina_html():
    scraper = SlickdealsScraper(
        name="slickdeals", url="https://feeds.feedburner.com/SlickdealsnetFP", tag="#Slickdeals"
    )
    with pytest.raises(ScraperError):
        scraper.parsear_feed("<html><body>Just a moment...</body></html>")


def test_dealnews_extractor(mock_dealnews_html):
    scraper = DealsnewsScraper(name="dealnews", url="https://www.dealnews.com/", tag="#DealNews")
    soup = BeautifulSoup(mock_dealnews_html, "html.parser")
    seccion = soup.find("div", class_="flex-cell flex-cell-size-1of1")
    oferta = scraper.extraer_oferta(seccion)

    assert oferta is not None
    assert oferta.titulo == "Audífonos Sony"
    assert oferta.precio == "$49.99"
    assert oferta.precio_original == "$89.99"
    assert oferta.cupon == "SONYSAVE"
    assert oferta.link == "https://example.com/dn"
    assert oferta.imagen == "https://example.com/sony.jpg"


def test_dealsofamerica_extractor_no_confunde_code_con_cupon(mock_dealsofamerica_html):
    scraper = DealsOfAmericaScraper(
        name="dealsofamerica", url="https://www.dealsofamerica.com/", tag="#DealsOfAmerica"
    )
    soup = BeautifulSoup(mock_dealsofamerica_html, "html.parser")
    seccion = soup.find("section", class_="deal row")
    oferta = scraper.extraer_oferta(seccion)

    assert oferta is not None
    assert oferta.titulo == "Magsafe Car Phone Holder"
    assert oferta.precio == "$7.59"
    assert oferta.precio_original == "$38.99"
    assert oferta.cupon == "UN7HL3Q4"
    assert oferta.link == "https://www.dealsofamerica.com/deal/holder"
    assert oferta.imagen == "https://www.dealsofamerica.com/images/holder.jpg"
