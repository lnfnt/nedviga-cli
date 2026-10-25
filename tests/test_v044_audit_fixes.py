"""v0.4.4: регресс-тесты находок независимого аудита (sa-2, 21.10).
F-04 XSS export / F-02 post-hydrate фильтры / F-03 маскирование фикстуры."""
from nedviga.export_html import _safe_url, _card_html
from nedviga.models import ListingCard, Image


def test_safe_url_blocks_javascript():
    assert _safe_url('javascript:alert(1)') == ''
    assert _safe_url('x" onerror="alert(2)') == ''
    ok = _safe_url('https://x.example/a.jpg?b=1&c=2')
    assert ok.startswith('https://') and '&amp;' in ok


def test_export_html_no_raw_external_attrs():
    card = ListingCard(id='cian-1', source='cian', url='https://www.cian.ru/sale/flat/1/',
                       title='Тест',
                       images=[Image(url='x" onerror="alert(2)" src="y'), Image(url='javascript:alert(3)')])
    card.pricing.is_auction = True
    card.pricing.trading_link = 'javascript:alert(42)'
    html = _card_html(card, embed=False, idx=0)
    assert 'onerror=' not in html
    assert 'javascript:' not in html


def test_fixture_phones_masked():
    from pathlib import Path
    import re
    t = (Path(__file__).resolve().parent.parent / 'fixtures' / 'cian_search_results_scrubbed.html').read_text(encoding='utf-8')
    assert not re.search(r'"number":"\d{10}"', t)
    assert not re.search(r'\+7[\s(]*9\d{2}[\s)-]*\d{3}[\s-]*\d{2}[\s-]*\d{2}', t)


def test_auction_filter_applies_post_hydrate():
    # логика пост-гидрационного среза: известное is_auction решающее
    from nedviga.models import Pricing
    known_auct = ListingCard(id='cian-2', source='cian', url='u2')
    known_auct.pricing = Pricing(is_auction=True)
    known_flat = ListingCard(id='cian-3', source='cian', url='u3')
    known_flat.pricing = Pricing(is_auction=False)
    unknown = ListingCard(id='cian-4', source='cian', url='u4')
    cards = [known_auct, known_flat, unknown]
    known = [c for c in cards if c.pricing.is_auction is not None]
    unk = [c for c in cards if c.pricing.is_auction is None]
    survivors = [c for c in known if not c.pricing.is_auction] + unk
    assert {c.id for c in survivors} == {'cian-3', 'cian-4'}


def test_glued_prices_fail_closed():
    """F-01: склейка двух цен в один сегмент не должна рождать 1.69e15."""
    from nedviga.cian_live import _snippet_fields
    r = _snippet_fields(['3 комната', '16 900 000 18 000 000 ₽', '54,3 м²'])
    assert 'price_total_rub' not in r
    ok = _snippet_fields(['16 900 000 ₽', '54,3 м²'])
    assert ok.get('price_total_rub') == 16900000.0
