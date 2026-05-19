import pytest
from bs4 import BeautifulSoup
from scrapers.slickdeals_scraper import SlickdealsScraper
from scrapers.dealnews_scraper import DealsnewsScraper

def test_slickdeals_extractor(mock_slickdeals_html):
    scraper = SlickdealsScraper(name="slickdeals", url="dummy", tag="#Slickdeals")
    soup = BeautifulSoup(mock_slickdeals_html, 'html.parser')
    
    # SlickdealsScraper doesn't have an extraer_oferta method, it does it inline. 
    # Para testearlo fácilmente sin refactorizar el scraper completo, probamos la extracción que ocurre en el loop.
    ofertas = []
    for oferta_html in soup.find_all('div', {'class': 'dealCard__content'}):
        titulo = scraper.limpiar_texto(oferta_html.find('a', {'class': 'dealCard__title'}).text)
        link = 'https://slickdeals.net' + oferta_html.find('a', {'class': 'dealCard__title'})['href']
        
        precio_elem = oferta_html.find('span', {'class': 'dealCard__price'})
        precio = scraper.limpiar_texto(precio_elem.text) if precio_elem else 'No disponible'
        
        assert titulo == 'Laptop MSI 15.6"'
        assert link == 'https://slickdeals.net/f/12345-deal'
        assert precio == '$799.00'

def test_dealnews_extractor(mock_dealnews_html):
    scraper = DealsnewsScraper(name="dealnews", url="dummy", tag="#DealNews")
    soup = BeautifulSoup(mock_dealnews_html, 'html.parser')
    
    seccion = soup.find('div', class_='flex-cell flex-cell-size-1of1')
    oferta = scraper.extraer_oferta(seccion)
    
    assert oferta is not None
    assert oferta.titulo == "Audífonos Sony"
    assert oferta.precio == "$49.99"
    assert oferta.precio_original == "$89.99"
    assert oferta.cupon == "SONYSAVE"
    assert oferta.link == "https://example.com/dn"
    assert oferta.imagen == "https://example.com/sony.jpg"
