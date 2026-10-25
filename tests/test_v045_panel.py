"""v0.4.5 — регресс внешнего ревью (review)."""
import json, pickle, hashlib, pytest
from pathlib import Path


def test_safe_url_blocks_data_svg():
    from nedviga.export_html import _safe_url
    assert _safe_url('data:image/svg+xml;base64,AAAA<script>') == ''
    assert _safe_url('data:image/jpeg;base64,/9j/AAAA').startswith('data:image/jpeg')


def test_export_escapes_external_fields():
    from nedviga.models import ListingCard
    from nedviga.export_html import _card_html
    c = ListingCard(id='x" onmouseover="alert(1)', source='cian', url='https://www.cian.ru/sale/flat/1/')
    html = _card_html(c, embed=False, idx=0)
    assert 'onmouseover="alert' not in html


def test_breaker_and_egress_reraise(monkeypatch):
    import nedviga.cian_live as cl
    import nedviga.net_guard as ng
    def boom(*a, **k):
        raise ng.BreakerOpenError("www.cian.ru", 30.0)
    monkeypatch.setattr(ng, "guarded_get", boom)
    with pytest.raises(ng.BreakerOpenError):
        cl._requests_get_search("https://x", timeout=5)
    with pytest.raises(ng.BreakerOpenError):
        cl._requests_get_card("https://x", timeout=5)
    # и EgressBlockedError тоже пробивается
    def blocked(*a, **k):
        raise ng.EgressBlockedError("dns-pin verdict: private ip")
    monkeypatch.setattr(ng, "guarded_get", blocked)
    with pytest.raises(ng.EgressBlockedError):
        cl._requests_get_search("https://x", timeout=5)


def test_drift_no_pii(tmp_path, monkeypatch):
    import nedviga.price_guard as pg
    monkeypatch.setattr(pg, 'drift_file', lambda: tmp_path / 'drift.jsonl')
    pg.record_price_drift('cian-1', 'https://www.cian.ru/sale/flat/123/?x=Иванов', 'Продам квартиру, звонить Иванову')
    line = json.loads((tmp_path / 'drift.jsonl').read_text().splitlines()[-1])
    assert 'title' not in line and 'Иванов' not in json.dumps(line, ensure_ascii=False)
    assert line['url_host'] == 'www.cian.ru'


def test_graph_requires_sha256(tmp_path, monkeypatch):
    import nedviga.graph as g
    p = tmp_path / 'graph_moscow.pkg'
    data = {"nodes": {}, "edges": {}, "version": 1, "built_at": "x"}
    p.write_bytes(pickle.dumps(data))
    monkeypatch.delenv('NEDVIGA_GRAPH_PATH', raising=False)
    monkeypatch.delenv('NEDVIGA_GRAPH_ALLOW_UNSIGNED', raising=False)
    import pytest
    with pytest.raises(g.GraphNotAvailable):
        g.load_graph(Path(p))
    # с валидным sidecar — грузит
    (tmp_path / 'graph_moscow.pkg.sha256').write_text(hashlib.sha256(p.read_bytes()).hexdigest())
    g._graph = None
    gr = g.load_graph(Path(p))
    assert gr is not None
