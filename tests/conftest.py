import sys
from pathlib import Path

import pytest
import pytest_asyncio

RAIZ = Path(__file__).resolve().parents[1]
if str(RAIZ) not in sys.path:
    sys.path.insert(0, str(RAIZ))

from database.db_manager import DBManager  # noqa: E402


@pytest_asyncio.fixture
async def db(tmp_path):
    manager = DBManager(str(tmp_path / "ofertas-test.db"))
    await manager.init_db()
    return manager


@pytest.fixture
def mock_slickdeals_rss():
    return """<?xml version="1.0" encoding="UTF-8"?>
    <rss version="2.0" xmlns:content="http://purl.org/rss/1.0/modules/content/">
      <channel>
        <title>Slickdeals Frontpage</title>
        <item>
          <title>Laptop MSI 15.6" $799 + Free Shipping</title>
          <link>https://slickdeals.net/f/12345-deal</link>
          <description>Best Buy has the MSI laptop on sale for $799, was $999. Use coupon code "MSI20".</description>
          <pubDate>Tue, 10 Nov 2026 00:35:54 +0000</pubDate>
          <content:encoded><![CDATA[<div><img src="https://static.slickdealscdn.com/msi.jpg" /></div>]]></content:encoded>
        </item>
        <item>
          <title>Audífonos Sony</title>
          <link>https://slickdeals.net/f/67890-sony</link>
          <description>Amazon has them for $49.99 (reg. $89.99).</description>
          <content:encoded><![CDATA[<div><img src="https://static.slickdealscdn.com/sony.jpg" /></div>]]></content:encoded>
        </item>
      </channel>
    </rss>
    """


@pytest.fixture
def mock_dealnews_html():
    return """
    <html><body>
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
    </body></html>
    """


@pytest.fixture
def mock_dealsofamerica_html():
    return """
    <html><body>
      <section class="deal row">
        <div class="start_div">
          <span class="our-price">$7.59</span>
          <span class="list-price">$38.99</span>
          <img src="/images/holder.jpg" />
        </div>
        <div class="title"><a href="/deal/holder">Magsafe Car Phone Holder</a></div>
        <section class="more_details">
          Click Here and add to cart for $17.99 - $10.40 Off w/Coupon Code UN7HL3Q4 = $7.59
        </section>
      </section>
    </body></html>
    """
