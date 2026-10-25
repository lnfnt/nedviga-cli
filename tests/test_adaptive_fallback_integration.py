from nedviga.cian_card import parse_card


def test_adaptive_price_fallback_uses_data_name_without_itemprop():
    # Fully synthetic fixture: no live listing URL, address, ID, or scraped data.
    obfuscated_html = """
    <html>
    <head>
        <link rel="canonical" href="https://example.invalid/sale/flat/000000000/" />
    </head>
    <body>
        <div class="dynamic_container_synthetic">
            <h1>Объект тестовый, 99 м²</h1>
            <div class="unknown_wrapper">
                <span data-name="PriceInfo">11 111 111 ₽</span>
            </div>
            <div data-name="Geo">
                <span class="address">Тестовый адрес, дом 0</span>
            </div>
        </div>
    </body>
    </html>
    """
    card = parse_card(obfuscated_html)
    assert card.pricing.price_total_rub == 11111111.0
    assert card.pricing.price_total_rub is not None
    assert card.pricing.price_total_rub != 0.0
