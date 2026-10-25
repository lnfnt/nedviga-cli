"""Live Cian.ru fetcher using the native embedded browser.

Provides :func:`get_card` and :func:`search`. Both are fail-closed: any
WAF/captcha/rate-limit page is reported as :class:`ChallengeError` (CLI exit
code 2); any other fetch or parse problem is reported as :class:`FetchError`
(exit code 3).
"""

from __future__ import annotations

import re
from .net_guard import BreakerOpenError, EgressBlockedError
import time
import urllib.parse
from typing import Any

from .browser_native import get_last_http_status, native_fetch
from .cian_card import ParseError, parse_card
from .errors import ChallengeError, FetchError
from .models import ListingCard


# Substrings / selectors that reliably identify a challenge page on Cian.
_CHALLENGE_MARKERS = (
    "smartcaptcha",
    "captcha_challenge",
    "show-captcha",
    "check-captcha",
    "cloudflare",
    "cf-turnstile",
    "challenge-platform",
    "доступ ограничен",
    "доступ временно ограничен",
    "access denied",
    "access temporarily restricted",
    "проверка безопасности",
    "проверяем, что вы не робот",
    "вы робот",
    "ддос",
    "ddos",
)

# v0.4.0 (ТЗ реалтора): административные и ближайшие НП за МКАД.
_STRICT_MKAD_TOKENS = (
    "нао",
    "тао",
    "зелао",
    "новомосковский",
    "троицкий",
    "зеленоград",
    "московская область",
    "коммунарка",
    "рогозинино",
    "ватутинки",
    "первомайское",
    "сосенское",
    "красногорск",
    "мытищи",
    "люберцы",
    "балашиха",
    "одинцово",
    "химки",
    "видное",
    "реутов",
    "котельники",
)

# v0.4.0 (ТЗ реалтора): юридические стоп-слова.
_LEGAL_RISK_PHRASES = (
    "отказник от приватизации",
    "пожизненное проживание",
    "бессрочное пользование",
    "без просмотра",
    "третье лицо с правом",
)


def _is_strict_mkad(card: ListingCard) -> bool:
    """Return True when the listing address/geo is outside the strict MKAD set."""
    text = " ".join(
        [
            card.building.address_raw or "",
            card.geo.area_name or "",
            card.geo.district or "",
        ]
    ).lower()
    return any(token in text for token in _STRICT_MKAD_TOKENS)


def _is_apartment(card: ListingCard) -> bool:
    """Return True when the listing is an apartment (апартаменты)."""
    if card.building.is_apartments is True:
        return True
    text = f"{card.title or ''} {card.description_text or ''}".lower()
    return "апартамент" in text


def _is_share(card: ListingCard) -> bool:
    """Return True when the listing is a flat share (доля в квартире)."""
    if card.category == "flatShare":
        return True
    if card.parameters.share_amount is not None:
        return True
    text = f"{card.title or ''} {card.description_text or ''}".lower()
    return "доля в квартире" in text


def _has_legal_risk(card: ListingCard) -> bool:
    """Return True when the description contains a legal-risk stop phrase."""
    text = (card.description_text or "").lower()
    return any(phrase in text for phrase in _LEGAL_RISK_PHRASES)


def _normalize_url(url: str) -> str:
    url = url.strip()
    if not url.startswith("http"):
        url = "https://" + url
    return url


def _target_to_url(target: str) -> str:
    """Normalize a get-card target into a fetchable Cian URL.

    Accepts a bare numeric id, the tool's own ``cian-<digits>`` id format,
    or a URL. Normalization must happen before netguard sees the target.
    """
    target = target.strip()
    if target.isdigit():
        return f"https://www.cian.ru/sale/flat/{target}/"
    match = re.fullmatch(r"(?i:cian-)?(\d+)", target)
    if match:
        return f"https://www.cian.ru/sale/flat/{match.group(1)}/"
    return _normalize_url(target)


def _cian_id_from_url(url: str) -> str | None:
    match = re.search(r"/sale/flat/(\d+)/?", url)
    if match:
        return match.group(1)
    return None


def detect_challenge(html: str, http_hint: str | None = None) -> tuple[bool, str | None]:
    """Return (is_challenge, reason) for a Cian HTML response."""
    if not html or not html.strip():
        return False, None

    lowered = html.lower()

    # Explicit HTTP status markers help even when the body is tiny.
    if http_hint in ("403", "429"):
        return True, f"http_{http_hint}"

    for marker in _CHALLENGE_MARKERS:
        if marker in lowered:
            return True, f"challenge_marker:{marker}"

    # Cian's normal pages contain offer data or a search app root. A page that
    # is neither a card nor a search result and contains challenge-looking text
    # has already been caught by the markers above.
    return False, None


def _requests_get_card(url: str, *, timeout: float) -> str | None:
    """v0.3.4: requests-first транспорт для карточки (параллельный hydrate).

    Возвращает HTML если обычный HTTP отдал полноценную карточку без капчи,
    иначе None -> fallback на Camoufox.
    """
    try:
        from .net_guard import guarded_get

        resp = guarded_get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) "
                    "Gecko/20100101 Firefox/130.0"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ru-RU,ru;q=0.9",
            },
        )
        if resp.status_code == 200 and len(resp.text) > 100_000:
            http_hint = f"HTTP {resp.status_code}"
            is_challenge, _ = detect_challenge(resp.text, http_hint=http_hint)
            if not is_challenge:
                return resp.text
    except Exception as _exc:
        # v0.4.5 (панель R2): DNS-pin и breaker-вердикты не глотаются. Матчинг по
        # ИМЕНИ класса, а не только isinstance: reload(net_guard) в тестах/реальности
        # плодит свежие класс-объекты, и isinstance теряет вердикты (ловлено панелью-за-панелью).
        if isinstance(_exc, (EgressBlockedError, BreakerOpenError)) or                 type(_exc).__name__ in ("EgressBlockedError", "BreakerOpenError"):
            raise
    except Exception:
        pass
    return None


def get_card(target: str, *, timeout: float = 60.0, settle_ms: int = 1500) -> ListingCard:
    """Fetch and parse a single Cian listing card.

    ``target`` may be a full URL, a numeric Cian ID, or a ``cian-<digits>``
    ID as emitted by the tool itself.
    """
    url = _target_to_url(target)

    # v0.3.5: netguard — не идём в браузер, если хост в cooldown (защита подсети)
    from .net_guard import BreakerOpenError, check_before_fetch

    try:
        check_before_fetch(url)
    except BreakerOpenError as exc:
        raise ChallengeError(
            f"Cian is in cooldown for {url} ({exc}); retry later."
        ) from exc

    # v0.3.4: requests-first (0.4с вместо ~10с браузера); браузер — fallback
    html_req = _requests_get_card(url, timeout=timeout)
    if html_req is not None:
        try:
            return parse_card(html_req)
        except Exception:
            pass  # парсинг не удался — попробуем браузерную версию страницы

    try:
        html = native_fetch(url, timeout=timeout, settle_ms=settle_ms)
    except FetchError:
        raise
    except Exception as exc:
        raise FetchError(f"failed to fetch {url}: {exc}") from exc

    http_hint = get_last_http_status()
    is_challenge, reason = detect_challenge(html, http_hint=http_hint)
    if is_challenge:
        raise ChallengeError(
            f"Cian returned a challenge page for {url} (reason={reason}). "
            "Try again later or change network/proxy."
        )

    try:
        return parse_card(html)
    except ParseError as exc:
        # If the parser cannot find a card, the DOM may have changed or the
        # listing was removed. Surface this as a fetch-time parse error.
        raise FetchError(f"failed to parse card at {url}: {exc}") from exc


# Коды округов Москвы в cat.php (подтверждено реалтором, v0.3.3)
DISTRICT_CODES: dict[str, int] = {
    "ЦАО": 4, "САО": 5, "СВАО": 6, "ВАО": 7, "ЮВАО": 8,
    "ЮАО": 9, "ЮЗАО": 10, "ЗАО": 11, "СЗАО": 12,
}


def _district_code(raw: str) -> int | None:
    """'ЮАО' -> 9, '9' -> 9, неизвестное -> None."""
    name = raw.strip().upper()
    if name in DISTRICT_CODES:
        return DISTRICT_CODES[name]
    if raw.strip().isdigit():
        return int(raw.strip())
    return None


def _requests_get_search(url: str, *, timeout: float) -> str | None:
    """v0.3.3 (фидбэк реалтора): requests-first транспорт для cat.php.

    Возвращает HTML если обычный HTTP отдал полноценную выдачу без капчи,
    иначе None -> fallback на Camoufox.
    """
    try:
        from .net_guard import guarded_get

        resp = guarded_get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) "
                    "Gecko/20100101 Firefox/130.0"
                ),
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Language": "ru-RU,ru;q=0.9",
            },
        )
        if resp.status_code == 200 and len(resp.text) > 50_000:
            http_hint = f"HTTP {resp.status_code}"
            is_challenge, reason = detect_challenge(resp.text, http_hint=http_hint)
            if not is_challenge:
                return resp.text
    except Exception as _exc:
        # v0.4.5 (панель R2): DNS-pin и breaker-вердикты не глотаются. Матчинг по
        # ИМЕНИ класса, а не только isinstance: reload(net_guard) в тестах/реальности
        # плодит свежие класс-объекты, и isinstance теряет вердикты (ловлено панелью-за-панелью).
        if isinstance(_exc, (EgressBlockedError, BreakerOpenError)) or                 type(_exc).__name__ in ("EgressBlockedError", "BreakerOpenError"):
            raise
    except Exception:
        pass
    return None


def _build_search_url(
    *,
    deal_type: str | None = "sale",
    rooms: int | str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    kitchen_min: float | None = None,
    floor_not_first: bool = False,
    min_house_floors: int | None = None,
    geo_districts: str | None = None,
    limit: int | None = None,
    page: int = 1,
    metro_walk_max: int | None = None,
) -> str:
    """Build a Cian search URL from CLI-style filters.

    This is intentionally simple: the native browser fetches the URL and the
    result page is parsed for listing links. The URL is kept compatible with
    Cian's ``cat.php`` endpoint.
    """
    params: dict[str, Any] = {
        "deal_type": deal_type or "sale",
        "engine_version": 2,
        "offer_type": "flat",
        "region": 1,  # Moscow
        "p": max(1, int(page)),
    }

    if rooms is not None:
        if isinstance(rooms, str) and rooms.lower() in ("studio", "студия"):
            params["room0"] = 1
        elif rooms == 1:
            params["room1"] = 1
        elif rooms == 2:
            params["room2"] = 1
        elif rooms == 3:
            params["room3"] = 1
        elif rooms >= 4:
            params["room9"] = 1  # 4+

    if price_min is not None:
        params["minprice"] = int(price_min)
    if price_max is not None:
        params["maxprice"] = int(price_max)

    if kitchen_min is not None:
        params["kitchen[0]"] = kitchen_min

    # v0.3.2 (ТЗ реалтора, блок 1b): server-side фильтры Циан
    if floor_not_first:
        params["minfloor"] = 2  # не первый этаж
    if min_house_floors is not None:
        # Этажность ДОМА; minfloors Циан игнорирует
        params["minhousefloors"] = int(min_house_floors)
    if geo_districts:
        # 'ЮАО,ЮЗАО' или '9,10' -> district[0]=9&district[1]=10 (v0.3.3: имена тоже)
        codes = [d.strip() for d in str(geo_districts).split(",") if d.strip()]
        idx = 0
        for code in codes:
            num = _district_code(code)
            if num is None:
                raise ValueError(
                    f"unknown district '{code}'; use name (ЦАО..СЗАО) or code "
                    f"({min(DISTRICT_CODES.values())}..{max(DISTRICT_CODES.values())})"
                )
            params[f"district[{idx}]"] = num
            idx += 1
    if metro_walk_max is not None:
        params["in_metro_time"] = int(metro_walk_max)
        params["metro_transport_type"] = "walk"

    # limit: client-side slice in search().

    query = urllib.parse.urlencode(params, quote_via=urllib.parse.quote)
    return f"https://www.cian.ru/cat.php?{query}"


def _container_segments(link) -> list[str] | None:
    """v0.4.3: подняться от <a> к карточке-контейнеру выдачи (data-testid=offer-card)."""
    node = link
    for _ in range(10):
        node = getattr(node, "parent", None)
        if node is None:
            return None
        try:
            if node.attrs.get("data-testid") == "offer-card":
                return [s.strip() for s in node.stripped_strings if s.strip()]
        except AttributeError:
            return None
    return None


_PRICE_RE = __import__("re").compile(r"^([\d][\d\s\u00a0\u202f]{4,})\s*₽$")
_PRICE_M2_RE = __import__("re").compile(r"^([\d][\d\s\u00a0\u202f]{2,})\s*₽/м")
_FLOOR_RE = __import__("re").compile(r"(\d+)\s*/\s*(\d+)\s*эт")
_ROOMS_RE = __import__("re").compile(r"^(\d+)[- ]комн")
_AREA_RE = __import__("re").compile(r"([\d]+(?:[.,]\d+)?)\s*м²")
_KITCHEN_RE = __import__("re").compile(r"кухня[^\d]{0,4}([\d]+(?:[.,]\d+)?)\s*м", __import__("re").IGNORECASE)
_COMPLEX_RE = __import__("re").compile(r"ЖК\s*[«\"]([^»\"]{2,40})[»\"]")
_METRO_TIME_RE = __import__("re").compile(r"^(\d+)\s*(?:мин\w*|м)\b.*?(пешком|транспортом|на метро)")


def _digits_to_amount(group: str, cap: float) -> float | None:
    """v0.4.4 (независимый аудит sa-2, F-01): цифра с верхней границей.

    Склеенные в один сегмент два ценника ('16 900 000 18 000 000 ₽') давали
    1.69e15 — несуществующую сумму, которая всё равно уходила в выдачу.
    Sanity-капер: значение выше границы = None (fail-closed), мусор не продаём.
    """
    d = __import__("re").sub(r"\D", "", group)
    if not d or len(d) > 11:
        return None
    v = float(int(d))
    return v if v <= cap else None


def _snippet_fields(segs: list[str]) -> dict:
    """v0.4.3: базовые поля из текста сниппета. Непрочитанное = None, догадок нет."""
    out: dict = {}
    price_i = None
    for i, s in enumerate(segs):
        if _PRICE_RE.match(s):
            price_i = i
            break
    scope = segs[: price_i + 2] if price_i is not None else segs[:40]

    if price_i is not None:
        m = _PRICE_RE.match(segs[price_i])
        if m:
            sane = _digits_to_amount(m.group(1), 10**11)
            if sane is not None:
                out["price_total_rub"] = sane
    for s in scope:
        if price_i is not None and s is segs[price_i]:
            continue
        m = _PRICE_M2_RE.match(s)
        if m:
            sane = _digits_to_amount(m.group(1), 10**8)
            if sane is not None:
                out["price_per_m2_rub"] = sane
                break

    short = [s for s in scope if len(s) < 120]
    for s in short:
        m = _FLOOR_RE.search(s)
        if m:
            out["floor"] = int(m.group(1))
            out["floors_total"] = int(m.group(2))
            break
    for s in short:
        m = _ROOMS_RE.match(s)
        if m:
            out["rooms"] = int(m.group(1))
            a = _AREA_RE.search(s)
            if a:
                out["area_total_m2"] = float(a.group(1).replace(",", "."))
            if "студия" in s.lower():
                out["rooms_type"] = "студия"
            break
    for s in short:
        m = _KITCHEN_RE.search(s)
        if m:
            out["area_kitchen_m2"] = float(m.group(1).replace(",", "."))
            break
    joined = " | ".join(short)
    m = _COMPLEX_RE.search(joined)
    if m:
        out["complex"] = m.group(1).strip()

    city_i = next((i for i, s in enumerate(scope) if s == "Москва" or s.startswith("Москва,")), None)
    if city_i is not None:
        parts: list[str] = []
        for s in scope[city_i:city_i + 14]:
            if _PRICE_RE.match(s) or _PRICE_M2_RE.match(s):
                break
            if s == ",":
                parts.append(",")
            else:
                parts.append(s)
        addr = " ".join(parts).replace(" ,", ",").strip(" ,")
        if addr:
            out["address_raw"] = addr

    if price_i is not None:
        for i in range(max(0, price_i - 24), price_i):
            m = _METRO_TIME_RE.match(segs[i])
            if m and i > 0 and 2 <= len(segs[i - 1]) <= 24 and segs[i - 1].isalpha():
                tt = "пешком" if "пешком" in m.group(2) else "метро/транспорт"
                out["metro"] = {"station": segs[i - 1], "claimed_time_minutes": int(m.group(1)),
                               "transport_type": tt}
                break
    return out


def _apply_snippet(card, fields: dict) -> None:
    if not fields:
        return
    p = card.parameters
    if "rooms" in fields:
        p.rooms = fields["rooms"]
    if "rooms_type" in fields:
        p.rooms_type = fields["rooms_type"]
    if "area_total_m2" in fields:
        p.area_total_m2 = fields["area_total_m2"]
    if "area_kitchen_m2" in fields:
        p.area_kitchen_m2 = fields["area_kitchen_m2"]
    if "floor" in fields:
        p.floor = fields["floor"]
    if "floors_total" in fields:
        p.floors_total = fields["floors_total"]
    if "address_raw" in fields:
        card.building.address_raw = fields["address_raw"]
    if "complex" in fields:
        card.building.complex = fields["complex"]
    if "price_total_rub" in fields:
        card.pricing.price_total_rub = fields["price_total_rub"]
    if "price_per_m2_rub" in fields:
        card.pricing.price_per_m2_rub = fields["price_per_m2_rub"]
    if "metro" in fields:
        from .models import CianClaimedMetro
        card.geo.cian_claimed_metro = CianClaimedMetro(**fields["metro"])


def _merge_snippet_into_hydrated(skel, card) -> None:
    """v0.4.3 инвариант: hydrated — источник истины; сниппет дополняет только пустое."""
    sp, cp = skel.parameters, card.parameters
    for attr in ("rooms", "rooms_type", "area_total_m2", "area_kitchen_m2", "floor", "floors_total"):
        if getattr(cp, attr) is None and getattr(sp, attr) is not None:
            setattr(cp, attr, getattr(sp, attr))
    for attr in ("address_raw", "complex"):
        if getattr(card.building, attr) is None and getattr(skel.building, attr) is not None:
            setattr(card.building, attr, getattr(skel.building, attr))
    for attr in ("price_total_rub", "price_per_m2_rub"):
        if getattr(card.pricing, attr) is None and getattr(skel.pricing, attr) is not None:
            setattr(card.pricing, attr, getattr(skel.pricing, attr))
    if card.geo.cian_claimed_metro is None and skel.geo.cian_claimed_metro is not None:
        card.geo.cian_claimed_metro = skel.geo.cian_claimed_metro


def _parse_search_result_links(html: str, limit: int | None = None) -> list[ListingCard]:
    """Extract listing cards from a Cian search result page.

    v0.4.3 (ТЗ the task brief): из контейнера сниппета (data-testid=offer-card)
    одним прогоном читаются базовые поля (цена/площадь/комнатность/адрес/
    ЖК/этаж-этажность + best-effort метро). Непрочитанное остаётся None.
    Карточка по-прежнему может быть обогащена через get_card (hydrate),
    hydrated-значения имеют приоритет (_merge_snippet_into_hydrated).
    """
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    by_id: dict[str, ListingCard] = {}
    order: list[str] = []

    # Cian search results link to /sale/flat/<id>/
    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        cid = _cian_id_from_url(href)
        if not cid:
            continue
        if cid not in by_id:
            card = ListingCard(
                id=f"cian-{cid}",
                source="cian",
                url=f"https://www.cian.ru/sale/flat/{cid}/",
                status="active",
            )
            by_id[cid] = card
            order.append(cid)
        else:
            card = by_id[cid]
        if card.parameters.floor is None:  # ещё не обогатали
            segs = _container_segments(link)
            if segs:
                _apply_snippet(card, _snippet_fields(segs))
        if limit is not None and len(order) >= limit:
            break

    return [by_id[c] for c in order[: limit or len(order)]]


def _post_filter_cards(
    cards: list[ListingCard],
    *,
    floor_not_first: bool = False,
    min_house_floors: int | None = None,
    geo_districts: str | None = None,
    limit: int | None = None,
) -> list[ListingCard]:
    """Apply client-side filters that lack reliable Cian URL parameters.

    ``floor_not_first`` and ``min_house_floors`` require per-card
    ``parameters`` data (floor / floors_total).  ``geo_districts`` requires
    ``geo.district``.  These fields are absent on lightweight search-result
    cards and only effective on fully hydrated cards.

    ``limit`` always applies (slice).
    """
    if floor_not_first:
        cards = [c for c in cards if c.parameters.floor != 1]
    if min_house_floors is not None:
        cards = [
            c
            for c in cards
            if c.parameters.floors_total is None
            or c.parameters.floors_total >= min_house_floors
        ]
    if geo_districts is not None:
        districts = {
            d.strip().lower() for d in geo_districts.split(",") if d.strip()
        }
        if districts:
            cards = [
                c
                for c in cards
                if c.geo.district is None
                or c.geo.district.lower() in districts
            ]
    if limit is not None:
        cards = cards[:limit]
    return cards


def search(
    *,
    deal_type: str | None = "sale",
    rooms: int | str | None = None,
    price_min: float | None = None,
    price_max: float | None = None,
    kitchen_min: float | None = None,
    floor_not_first: bool = False,
    min_house_floors: int | None = None,
    geo_districts: str | None = None,
    limit: int | None = None,
    timeout: float = 60.0,
    settle_ms: int = 2500,
    page: int = 1,
    pages: int | None = None,
    metro_walk_max: int | None = None,
    hydrate: bool = False,
    no_auction: bool = False,
    only_auction: bool = False,
    workers: int = 4,
    # v0.4.0 (ТЗ реалтора): боевые фильтры риелтора
    strict_mkad: bool = False,
    only_flat: bool = False,
    no_shares: bool = False,
    exclude_legal_risks: bool = False,
) -> list[ListingCard]:
    """Fetch Cian search result pages and return a list of listing cards.

    v0.3.2 (ТЗ реалтора):
    - ``page``/``pages``: пагинация (pages=3 соберёт страницы 1..3);
    - ``metro_walk_max``: server-side пешая доступность (in_metro_time+walk);
    - ``hydrate``: прогнать полученные URL через get_card для полных карточек.
    """

    def _fetch_page(page_no: int) -> list[ListingCard]:
        url = _build_search_url(
            deal_type=deal_type,
            rooms=rooms,
            price_min=price_min,
            price_max=price_max,
            kitchen_min=kitchen_min,
            floor_not_first=floor_not_first,
            min_house_floors=min_house_floors,
            geo_districts=geo_districts,
            limit=limit,
            page=page_no,
            metro_walk_max=metro_walk_max,
        )
        html: str | None = _requests_get_search(url, timeout=timeout)
        if html is None:
            # v0.3.5: netguard — не идём в браузер, если хост в cooldown.
            # Проверяем ТОЛЬКО breaker (без DNS-резолва: egress уже проверен
            # в _requests_get_search, а резолв здесь ломал офлайн-работу).
            from .net_guard import breaker_remaining

            remaining = breaker_remaining(url)
            if remaining > 0:
                raise ChallengeError(
                    f"Cian is in cooldown for search ({remaining:.0f}s left); retry later."
                )
            try:
                html = native_fetch(url, timeout=timeout, settle_ms=settle_ms)
            except FetchError:
                raise
            except Exception as exc:
                raise FetchError(f"failed to fetch search {url}: {exc}") from exc
            http_hint = get_last_http_status()
            is_challenge, reason = detect_challenge(html, http_hint=http_hint)
            if is_challenge:
                raise ChallengeError(
                    f"Cian returned a challenge page for search (reason={reason}). "
                    "Try again later or change network/proxy."
                )

        cards = _parse_search_result_links(html)
        if not cards:
            return []
        return _post_filter_cards(
            cards,
            floor_not_first=floor_not_first,
            min_house_floors=min_house_floors,
            geo_districts=geo_districts,
            limit=limit,
        )

    page_list = [page] if not pages or pages < 2 else list(range(1, int(pages) + 1))
    all_cards: list[ListingCard] = []
    seen_urls: set[str] = set()
    for no in page_list:
        for card in _fetch_page(no):
            if card.url in seen_urls:
                continue
            seen_urls.add(card.url)
            all_cards.append(card)
        if no != page_list[-1] and settle_ms:
            time.sleep(settle_ms / 1000.0)

    # v0.3.4 (ТЗ реалтора): фильтр торгов/аукционов (требует hydrate-полей
    # is_auction; на скелетах поле None — пропускаем без решения, фильтруем
    # только когда значение известно)
    def _auction_known(c: ListingCard) -> bool:
        return c.pricing.is_auction is not None

    def _auction_val(c: ListingCard) -> bool:
        return bool(c.pricing.is_auction)

    if no_auction or only_auction:
        unknown = [c for c in all_cards if not _auction_known(c)]
        known = [c for c in all_cards if _auction_known(c)]
        if only_auction:
            known = [c for c in known if _auction_val(c)]
        if no_auction:
            known = [c for c in known if not _auction_val(c)]
        # скелеты с неизвестным статусом сохраняем только если оба флага согласованы
        all_cards = known + unknown if not (no_auction and only_auction) else known

    if limit is not None:
        all_cards = all_cards[: int(limit)]

    if hydrate:
        from concurrent.futures import ThreadPoolExecutor, as_completed

        hydrated: list[ListingCard | None] = [None] * len(all_cards)

        def _hydrate_one(idx_url: tuple[int, str]) -> tuple[int, ListingCard]:
            idx, url = idx_url
            try:
                card = get_card(url, timeout=timeout, settle_ms=settle_ms)
                # v0.4.3: сниппет-поля дополняют пустое в hydrated (никогда не перекрывают)
                _merge_snippet_into_hydrated(all_cards[idx], card)
                return idx, card
            except (FetchError, ChallengeError):
                return idx, all_cards[idx]  # fail-open: скелет

        max_workers = max(1, min(int(workers), len(all_cards) or 1))
        with ThreadPoolExecutor(max_workers=max_workers) as pool:
            futures = [pool.submit(_hydrate_one, (i, c.url)) for i, c in enumerate(all_cards)]
            for fut in as_completed(futures):
                idx, card = fut.result()
                hydrated[idx] = card
        all_cards = [c for c in hydrated if c is not None]

    # v0.4.3 (ТЗ the task brief §2): напольные фильтры повторяются ПОСЛЕ гидрации —
    # карточки, у которых в сниппете этаж был None и не отсеялись заранее,
    # проверяются по полным данным (correctness > экономии), None проходит дальше.
    if floor_not_first:
        all_cards = [c for c in all_cards if c.parameters.floor != 1]
    if min_house_floors is not None:
        all_cards = [
            c for c in all_cards
            if c.parameters.floors_total is None
            or c.parameters.floors_total >= int(min_house_floors)
        ]
    # v0.4.4 (независимый аудит sa-2, F-02): аукционы/гео применялись только к
    # скелетам ДО гидрации (поля None => no-op) и не повторялись после — в бою
    # не фильтровали. Повтор post-hydrate: известное значение — решающее,
    # None после гидрации (не удалось прочитать) остаётся честным no-op.
    if no_auction or only_auction:
        known = [c for c in all_cards if c.pricing.is_auction is not None]
        unknown = [c for c in all_cards if c.pricing.is_auction is None]
        if only_auction:
            known = [c for c in known if bool(c.pricing.is_auction)]
        if no_auction:
            known = [c for c in known if not c.pricing.is_auction]
        all_cards = known + unknown
    if geo_districts:
        districts = {d.strip().lower() for d in geo_districts.split(",") if d.strip()}
        if districts:
            all_cards = [
                c for c in all_cards
                if c.geo.district is None or c.geo.district.lower() in districts
            ]

    # v0.4.0 (ТЗ реалтора): фильтры требуют полных карточек (hydrate=True)
    if strict_mkad:
        all_cards = [c for c in all_cards if not _is_strict_mkad(c)]
    if only_flat:
        all_cards = [c for c in all_cards if not _is_apartment(c)]
    if no_shares:
        all_cards = [c for c in all_cards if not _is_share(c)]
    if exclude_legal_risks:
        all_cards = [c for c in all_cards if not _has_legal_risk(c)]
    if limit is not None:
        all_cards = all_cards[: int(limit)]

    return all_cards
