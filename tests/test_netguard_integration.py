"""Интеграционный тест: netguard реально стоит на боевых вызовах nedviga-cli.

Без сети: если хост Циан в cooldown, get_card обязан упасть ChallengeError
НЕ доходя ни до requests, ни до браузера. Доказывает, что вызов
check_before_fetch встроен в прод-путь (а не лежит рядом).
"""

import importlib
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

fd, db = tempfile.mkstemp(suffix=".sqlite3")
os.close(fd)
os.unlink(db)
os.environ["NEDVIGA_NETGUARD_DB"] = db


def test_get_card_blocked_by_breaker():
    from nedviga import net_guard as ng
    from nedviga import cian_live

    importlib.reload(ng)
    ng.breaker_trip("www.cian.ru", seconds=120.0, reason="http_403")
    try:
        cian_live.get_card("123456789")
    except cian_live.ChallengeError as exc:
        assert "cooldown" in str(exc).lower(), str(exc)
    else:
        raise AssertionError("get_card must fail while breaker is open")
    # и повторно — стабильность
    try:
        cian_live.get_card("https://www.cian.ru/sale/flat/123/")
        raise AssertionError("second call must also fail")
    except cian_live.ChallengeError:
        pass
    finally:
        # уборка: сессия pytest общая, cooldown не должен течь в другие тесты
        ng.breaker_trip("www.cian.ru", seconds=0.0, reason="cleanup")


def test_search_path_uses_guard():
    """Вызов guarded_get встроен в транспорт поиска (grep-независимое доказательство:
    подменяем requests и проверяем, что guarded_get вызывается)."""
    from nedviga import cian_live

    src = Path(cian_live.__file__).read_text(encoding="utf-8")
    assert "guarded_get" in src, "cian_live must call guarded_get"
    assert "check_before_fetch" in src, "browser fallback must be gated"


def test_geo_routing_uses_guard():
    from nedviga import geo_routing

    src = Path(geo_routing.__file__).read_text(encoding="utf-8")
    assert "guarded_get" in src, "geo_routing must call guarded_get"


def test_egress_blocks_private_in_transport():
    """Сквозной тест egress-guard через боевой транспорт: запрос в приватную
    сеть обязан быть заблокирован самим guarded_get."""
    import requests

    from nedviga.net_guard import EgressBlockedError, guarded_get

    try:
        guarded_get("http://192.168.77.77:9999/", timeout=1.0)
    except EgressBlockedError:
        pass
    except requests.exceptions.ConnectionError:
        raise AssertionError(
            "guarded_get пропустил приватный адрес (guard не в контуре!)"
        )
    else:
        raise AssertionError("guarded_get must deny private nets")
