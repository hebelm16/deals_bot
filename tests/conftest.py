import pytest
import sys
import os

# Asegurar que el directorio raíz del proyecto esté en el PYTHONPATH
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

@pytest.fixture
def mock_slickdeals_html():
    return """
    <html>
        <body>
            <div class="dealCard__content">
                <a class="dealCard__title" href="/f/12345-deal">Laptop MSI 15.6"</a>
                <span class="dealCard__price">$799.00</span>
                <span class="dealCard__originalPrice">$999.00</span>
                <img class="dealCard__image" src="https://example.com/msi.jpg" />
            </div>
        </body>
    </html>
    """

@pytest.fixture
def mock_dealnews_html():
    return """
    <html>
        <body>
            <div class="flex-cell flex-cell-size-1of1">
                <div class="title limit-height limit-height-large-2 limit-height-small-2">
                    <a href="https://example.com/dn">Audífonos Sony</a>
                </div>
                <div class="callout limit-height limit-height-large-1 limit-height-small-1">
                    $49.99 <span class="callout-comparison">$89.99</span>
                </div>
                <img class="native-lazy-img" src="https://example.com/sony.jpg" />
                <a class="attractor" href="https://example.com/dn">Link</a>
                <div class="snippet summary">Use coupon code "SONYSAVE"</div>
            </div>
        </body>
    </html>
    """
