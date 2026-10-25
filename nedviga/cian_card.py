"""Offline parser for a saved Cian.ru listing card HTML page.

The parser is intentionally fail-closed: missing values become ``None`` and
malformed/unparseable input raises :class:`ParseError`.

It supports two extraction strategies:

1. The ``window._offersData`` JSON island when present.
2. A broad set of DOM selectors using Cian's real ``data-name`` attributes as
   fallback/alternative sources.

All numeric normalizers are locale-aware for the Russian format
(``54,2 м²``, ``16 900 000 ₽``, ``6/12 этаж``).
"""

from __future__ import annotations

import json
import re
from typing import Any

from bs4 import BeautifulSoup, Tag

from .models import (
    Building,
    CianClaimedMetro,
    Geo,
    Image,
    ListingCard,
    Parameters,
    PriceHistoryPoint,
    Pricing,
    Seller,
)


class ParseError(Exception):
    """Raised when input HTML is garbage or the card cannot be identified."""


# ---------------------------------------------------------------------------
# Text normalisation helpers
# ---------------------------------------------------------------------------


def _strip(text: str | None) -> str | None:
    if text is None:
        return None
    text = text.replace("\xa0", " ").strip()
    return text if text else None


def _normalize_number(text: str | None) -> float | None:
    """Convert '54,2', '16 900 000', '311 808,12' etc. to float."""
    text = _strip(text)
    if not text:
        return None
    # Keep only ASCII digits, commas, periods and spaces.
    cleaned = "".join(ch for ch in text if (ch.isascii() and ch.isdigit()) or ch in ",. ")
    cleaned = cleaned.replace(" ", "").replace("\xa0", "")
    if not cleaned:
        return None
    # Russian decimal separator is comma.
    cleaned = cleaned.replace(",", ".")
    # Guard against multiple dots: treat dots as thousands separators
    # only when every group after a dot is exactly 3 digits; else invalid.
    if cleaned.count(".") > 1:
        parts = cleaned.split(".")
        if all(len(p) == 3 and p.isdigit() for p in parts[1:]):
            cleaned = "".join(parts)
        else:
            return None
    try:
        return float(cleaned)
    except ValueError:
        return None


def _normalize_int(text: str | None) -> int | None:
    num = _normalize_number(text)
    if num is None:
        return None
    return int(num)


def _normalize_price(text: str | None) -> float | None:
    """Convert '16 900 000 ₽' to 16900000.0."""
    return _normalize_number(text)


def _normalize_area(text: str | None) -> float | None:
    """Convert '54,2 м²' to 54.2."""
    return _normalize_number(text)


def _parse_floor(text: str | None) -> tuple[int | None, int | None]:
    """Convert '6/12 этаж', '6 из 12', '6 этаж' to (floor, total)."""
    text = _strip(text)
    if not text:
        return None, None
    match = re.search(r"(\d+)\s*(?:/|из)\s*(\d+)", text)
    if match:
        return int(match.group(1)), int(match.group(2))
    match = re.search(r"(\d+)\s*этаж", text)
    if match:
        return int(match.group(1)), None
    match = re.search(r"^(\d+)$", text)
    if match:
        return int(match.group(1)), None
    return None, None


def _parse_year(text: str | None) -> int | None:
    text = _strip(text)
    if not text:
        return None
    match = re.search(r"\b(19\d{2}|20\d{2})\b", text)
    if match:
        return int(match.group(1))
    return None


def _parse_rooms(title: str | None, factoids: dict[str, str]) -> int | None:
    """Extract room count from title or 'Комнаты' factoid.

    Studio maps to ``0`` to keep the integer schema consistent.
    """
    candidates = []
    if title:
        candidates.append(title)
    if "комнаты" in factoids:
        candidates.append(factoids["комнаты"])
    for text in candidates:
        if not text:
            continue
        lower = text.lower()
        if "студия" in lower or "студию" in lower:
            return 0
        match = re.search(r"(\d+)[\s\-]*комн", lower)
        if match:
            return int(match.group(1))
        match = re.search(r"(\d+)\s*комнат", lower)
        if match:
            return int(match.group(1))
    return None


def _parse_rooms_type(text: str | None) -> str | None:
    text = _strip(text)
    if not text:
        return None
    lower = text.lower()
    if "изолирован" in lower:
        return "isolated"
    if "евро" in lower or "студи" in lower:
        return "euro"
    if "смеж" in lower:
        return "adjacent"
    if "свобод" in lower:
        return "free"
    return text


def _parse_renovation(text: str | None) -> str | None:
    text = _strip(text)
    if not text:
        return None
    lower = text.lower()
    mapping = {
        "косметический": "cosmetic",
        "евроремонт": "euro",
        "евро": "euro",
        "дизайнерский": "design",
        "без ремонта": "none",
        "предчистовая": "pre_finnish",
        "чистовая": "finnish",
        "хорошее": "good",
    }
    for key, value in mapping.items():
        if key in lower:
            return value
    if lower in ("unknown", ""):
        return None
    return lower


def _parse_building_type(text: str | None) -> str | None:
    text = _strip(text)
    if not text:
        return None
    lower = text.lower()
    mapping = {
        "панель": "panel",
        "кирпич": "brick",
        "монолит": "monolith",
        "монолитно-кирпич": "monolith_brick",
        "блочн": "block",
        "сталин": "stalin",
        "дерев": "wood",
    }
    for key, value in mapping.items():
        if key in lower:
            return value
    return lower


def _parse_floor_material(text: str | None) -> str | None:
    text = _strip(text)
    if not text:
        return None
    lower = text.lower()
    if "железобетон" in lower or "ж/б" in lower:
        return "reinforced_concrete"
    if "дерев" in lower:
        return "wood"
    if "монолит" in lower:
        return "monolith"
    return lower


def _parse_elevators(text: str | None) -> tuple[int | None, int | None]:
    """Return (passenger, cargo) from strings like '1 пассажирский' or
    '2 пассажирских и 1 грузовой'.
    """
    text = _strip(text)
    if not text:
        return None, None
    lower = text.lower()

    def _count(prefixes: list[str]) -> int:
        for prefix in prefixes:
            match = re.search(r"(\d+)\s*" + prefix, lower)
            if match:
                return int(match.group(1))
        return 0

    passenger = _count(["пассажирск"]) or 0
    cargo = _count(["грузов"]) or 0

    if passenger == 0 and cargo == 0:
        match = re.search(r"(\d+)\s*лифт", lower)
        if match:
            passenger = int(match.group(1))

    return (passenger if passenger else None, cargo if cargo else None)


def _parse_yes_no(text: str | None) -> bool | None:
    text = _strip(text)
    if not text:
        return None
    lower = text.lower()
    if lower in ("есть", "да", "yes", "true"):
        return True
    if lower in ("нет", "no", "false", "отсутствует"):
        return False
    return None


def _parse_window_view(text: str | None) -> str | None:
    text = _strip(text)
    if not text:
        return None
    lower = text.lower()
    if "двор" in lower:
        return "yard"
    if "улиц" in lower or "дорог" in lower:
        return "street"
    if "парк" in lower:
        return "park"
    if "лес" in lower or "зелен" in lower:
        return "forest"
    return lower


def _parse_bathroom(text: str | None) -> str | None:
    text = _strip(text)
    if not text:
        return None
    lower = text.lower()
    if "раздельн" in lower:
        return "раздельный"
    if "совмещ" in lower:
        return "совмещенный"
    if "2" in lower or "два" in lower:
        return "2 санузла"
    return text


# ---------------------------------------------------------------------------
# DOM helpers
# ---------------------------------------------------------------------------


def _find_one(soup: BeautifulSoup, selectors: list[str]) -> Tag | None:
    """Try a list of CSS selectors and return the first matching Tag."""
    for selector in selectors:
        try:
            tag = soup.select_one(selector)
        except Exception:
            continue
        if isinstance(tag, Tag):
            return tag
    return None


def _find_text(soup: BeautifulSoup, selectors: list[str]) -> str | None:
    tag = _find_one(soup, selectors)
    if tag is None:
        return None
    return _strip(tag.get_text())


def _summary_pairs_from_container(soup: BeautifulSoup) -> dict[str, str]:
    """Build {lowercase_title: value} from OfferSummaryInfoItem pairs.

    Live newbuilding cards (2026-09) present parameters as title/value
    ``<p>`` pairs inside ``[data-name='OfferSummaryInfoItem']``.
    """
    result: dict[str, str] = {}
    for item in soup.select("[data-name='OfferSummaryInfoItem']"):
        if not isinstance(item, Tag):
            continue
        texts = [p.get_text(strip=True) for p in item.select("p")]
        texts = [t for t in texts if t]
        if len(texts) >= 2:
            result[texts[0].lower().replace("\xa0", " ")] = texts[1].replace("\xa0", " ")
    return result


def _factoids_from_container(soup: BeautifulSoup) -> dict[str, str]:
    result: dict[str, str] = {}
    containers = soup.select("[data-name='OfferCardPageInfo']") or soup.select(
        "[data-name='OfferFactoids']"
    )
    for container in containers:
        if not isinstance(container, Tag):
            continue
        items = container.select("[data-name='OfferFactoidsItem']")
        if not items:
            items = [child for child in container.children if isinstance(child, Tag)]
        for item in items:
            if not isinstance(item, Tag):
                continue
            title_tag = item.select_one("[data-name='OfferFactoidsItemTitle']")
            value_tag = item.select_one("[data-name='OfferFactoidsItemValue']")
            if title_tag and value_tag:
                title = _strip(title_tag.get_text())
                value = _strip(value_tag.get_text())
                if title and value:
                    result[title.lower()] = value
    return result


def _house_info_from_container(soup: BeautifulSoup) -> dict[str, str]:
    result: dict[str, str] = {}
    containers = soup.select("[data-name='HouseInfo']")
    for container in containers:
        if not isinstance(container, Tag):
            continue
        items = container.select("[data-name='HouseInfoItem']")
        for item in items:
            if not isinstance(item, Tag):
                continue
            title_tag = item.select_one("[data-name='HouseInfoItemTitle']")
            value_tag = item.select_one("[data-name='HouseInfoItemValue']")
            if title_tag and value_tag:
                title = _strip(title_tag.get_text())
                value = _strip(value_tag.get_text())
                if title and value:
                    result[title.lower()] = value
    return result


def _extract_json_island(soup: BeautifulSoup) -> dict[str, Any]:
    """Parse ``window._offersData`` JSON island if present."""
    for script in soup.find_all("script"):
        text = script.string or ""
        if "window._offersData" not in text:
            continue
        start = text.find("window._offersData")
        eq = text.find("=", start)
        if eq == -1:
            continue
        json_text = text[eq + 1 :]
        json_text = json_text.rstrip().rstrip(";")
        try:
            return json.loads(json_text)
        except json.JSONDecodeError:
            continue
    return {}


def _extract_default_state(soup: BeautifulSoup) -> dict[str, Any]:
    """Extract the ``defaultState.offerData`` blob from the embedded
    ``window._cianConfig['frontend-offer-card']`` config script.

    Live cards (2026-09) carry the full offer payload here:
    price, areas, floor, building, geo/coordinates, phones, photos,
    priceChanges. The old ``window._offersData`` island is gone.
    """
    for script in soup.find_all("script"):
        text = script.string or ""
        if '"key":"defaultState"' not in text and "'key':'defaultState'" not in text:
            continue
        start = text.find('"key":"defaultState"')
        if start == -1:
            start = text.find("'key':'defaultState'")
        value_marker = text.find('"value":', start)
        if value_marker == -1:
            continue
        try:
            data, _ = json.JSONDecoder().raw_decode(text[value_marker + len('"value":'):])
        except (json.JSONDecodeError, ValueError):
            continue
        offer_data = data.get("offerData") if isinstance(data, dict) else None
        if isinstance(offer_data, dict):
            return offer_data
    return {}


def _get_nested(data: dict[str, Any], *keys: str, default: Any = None) -> Any:
    for key in keys:
        if not isinstance(data, dict):
            return default
        data = data.get(key, default)
        if data is None:
            return default
    return data


# ---------------------------------------------------------------------------
# Field extractors
# ---------------------------------------------------------------------------


def _extract_id(soup: BeautifulSoup, json_data: dict[str, Any]) -> str | None:
    offers = json_data.get("offers") if isinstance(json_data, dict) else None
    if offers and isinstance(offers, list) and offers:
        first = offers[0]
        cid = first.get("cianId") or first.get("id")
        if cid is not None:
            return f"cian-{cid}"
    url = _extract_url(soup, json_data, None)
    if url:
        match = re.search(r"/sale/flat/(\d+)/", url)
        if match:
            return f"cian-{match.group(1)}"
    return None


def _extract_category(
    json_data: dict[str, Any], offer_data: dict[str, Any]
) -> str | None:
    """Return Cian listing category (e.g. flatShare, newBuildingFlatSale)."""
    offer = _offer_of(offer_data)
    if isinstance(offer, dict) and offer.get("category"):
        return _strip(str(offer["category"]))
    offers = json_data.get("offers") if isinstance(json_data, dict) else None
    if offers and isinstance(offers, list) and offers and isinstance(offers[0], dict):
        cat = offers[0].get("category")
        if cat:
            return _strip(str(cat))
    return None


def _extract_url(
    soup: BeautifulSoup, json_data: dict[str, Any], card_id: str | None
) -> str | None:
    offers = json_data.get("offers") if isinstance(json_data, dict) else None
    if offers and isinstance(offers, list) and offers:
        url = offers[0].get("url") or offers[0].get("fullUrl")
        if url:
            return url
    canonical = soup.find("link", {"rel": "canonical"})
    if isinstance(canonical, Tag):
        href = canonical.get("href")
        if href:
            return str(href)
    og_url = soup.find("meta", {"property": "og:url"})
    if isinstance(og_url, Tag):
        content = og_url.get("content")
        if content:
            return str(content)
    if card_id:
        cian_id = card_id.replace("cian-", "")
        return f"https://www.cian.ru/sale/flat/{cian_id}/"
    return None


def _extract_title(soup: BeautifulSoup, json_data: dict[str, Any]) -> str | None:
    offers = json_data.get("offers") if isinstance(json_data, dict) else None
    if offers and isinstance(offers, list) and offers:
        title = offers[0].get("title")
        if title:
            return _strip(str(title))
    return _find_text(
        soup,
        [
            "h1[data-name='OfferTitle']",
            "[data-name='OfferTitle']",
            "h1",
        ],
    )


def _extract_description(soup: BeautifulSoup) -> str | None:
    return _find_text(
        soup,
        [
            "[data-name='Description']",
            "[data-name='OfferDescription']",
            "[data-name='DescriptionText']",
        ],
    )


def _offer_of(offer_data: dict[str, Any]) -> dict[str, Any]:
    """Return the inner ``offer`` object from offerData ({} if absent)."""
    offer = offer_data.get("offer") if isinstance(offer_data, dict) else None
    return offer if isinstance(offer, dict) else {}


def _geo_address_part(offer: dict[str, Any], part_type: str) -> str | None:
    """Pick e.g. 'raion'/'street'/'house' from offer.geo.address items."""
    geo = offer.get("geo")
    items = geo.get("address") if isinstance(geo, dict) else None
    if not isinstance(items, list):
        return None
    for item in items:
        if isinstance(item, dict) and item.get("type") == part_type:
            return _strip(str(item.get("name")))
    return None


def _extract_pricing(
    soup: BeautifulSoup, json_data: dict[str, Any], offer_data: dict[str, Any],
    title: str | None = None,
) -> Pricing:
    offer = _offer_of(offer_data)
    first = {}
    offers = json_data.get("offers") if isinstance(json_data, dict) else None
    if offers and isinstance(offers, list) and offers and isinstance(offers[0], dict):
        first = offers[0]

    total: float | None = None
    per_m2: float | None = None

    # 1) defaultState.offerData.offer.bargainTerms.price (primary, live source)
    bargain = offer.get("bargainTerms")
    if isinstance(bargain, dict):
        price = bargain.get("price")
        if price is not None:
            total = _normalize_price(str(price))
        prices = bargain.get("prices")
        if total is None and isinstance(prices, dict) and prices.get("rur") is not None:
            total = _normalize_price(str(prices.get("rur")))

    # 2) old _offersData island
    json_price = _get_nested(first, "price", default={})
    if total is None and isinstance(json_price, dict):
        if json_price.get("value") is not None:
            total = _normalize_price(str(json_price.get("value")))
        if json_price.get("pricePerM2") is not None:
            per_m2 = _normalize_number(str(json_price.get("pricePerM2")))

    # 3) DOM fallback
    if total is None:
        raw_price_str = _find_text(
            soup,
            [
                "[data-name='OfferPrice']",
                "[data-name='Price']",
                "[data-name='NewbuildingPriceInfo']",
            ],
        )
        # Если найден itemprop='price', сначала проверяем атрибут content
        if not raw_price_str:
            itemprop_el = soup.find(attrs={"itemprop": "price"})
            if itemprop_el:
                raw_price_str = itemprop_el.get("content") or itemprop_el.get_text()

        total = _normalize_price(raw_price_str)

    # 4) Adaptive fallback (Scrapling pattern)
    if total is None:
        from .adaptive_selectors import extract_price_adaptive
        total = extract_price_adaptive(str(soup))

    # 5) P3-3 (2026-10-20): title-fallback, затем fail-closed drift-журнал
    if total is None and title:
        from .price_guard import price_from_title
        total = price_from_title(title)

    # per-m2: from sidebar fact (e.g. '250 100 ₽/м²') or offer price/area
    if per_m2 is None:
        fact = _find_text(
            soup,
            [
                "[data-name='OfferFactItem']",
                "[data-name='OfferPricePerMeter']",
                "[data-name='PricePerMeter']",
            ],
        )
        if fact and "м²" in fact:
            per_m2 = _normalize_number(fact)
    if per_m2 is None and total is not None:
        area_text = offer.get("totalArea")
        area = _normalize_area(str(area_text)) if area_text is not None else None
        if area:
            per_m2 = round(total / area, 2)

    history: list[PriceHistoryPoint] = []
    # 1) defaultState.offerData.priceChanges (newest first in payload)
    changes = offer_data.get("priceChanges") if isinstance(offer_data, dict) else None
    if isinstance(changes, list):
        for point in changes:
            if not isinstance(point, dict):
                continue
            change_time = point.get("changeTime")
            price_data = point.get("priceData")
            price = price_data.get("price") if isinstance(price_data, dict) else None
            if change_time and price is not None:
                date_match = re.match(r"(\d{4}-\d{2}-\d{2})", str(change_time))
                if date_match:
                    history.append(
                        PriceHistoryPoint(date=date_match.group(1), price=float(price))
                    )
    # 2) old island
    if not history:
        json_history = first.get("priceHistory") if isinstance(first, dict) else None
        if isinstance(json_history, list):
            for point in json_history:
                if isinstance(point, dict):
                    date = (
                        _strip(str(point.get("date")))
                        if point.get("date") is not None
                        else None
                    )
                    price = (
                        _normalize_number(str(point.get("price")))
                        if point.get("price") is not None
                        else None
                    )
                    if date and price is not None:
                        history.append(PriceHistoryPoint(date=date, price=price))
    # 3) DOM
    if not history:
        for item in soup.select("[data-name='PriceHistoryItem']"):
            if not isinstance(item, Tag):
                continue
            date = item.get("data-date") or _strip(item.get_text())
            price_text = _strip(item.get_text())
            price = _normalize_price(price_text)
            if date and price is not None:
                if not re.match(r"\d{4}-\d{2}-\d{2}", str(date)):
                    match = re.search(r"(\d{4}-\d{2}-\d{2})", str(date))
                    if match:
                        date = match.group(1)
                    else:
                        continue
                history.append(PriceHistoryPoint(date=str(date), price=price))

    # chronological order (oldest first) + drop consecutive duplicates
    history.sort(key=lambda p: (p.date, p.price))
    deduped: list[PriceHistoryPoint] = []
    for point in history:
        if deduped and deduped[-1].date == point.date and deduped[-1].price == point.price:
            continue
        deduped.append(point)
    history = deduped

    # v0.3.1 (реалтор-аудит §1): юридические условия сделки
    bt = offer.get("bargainTerms") if isinstance(offer.get("bargainTerms"), dict) else {}
    sale_type: str | None = None
    sale = bt.get("saleType") or offer.get("saleType")
    if sale:
        sale_type = str(sale)
    mortgage: bool | None = None
    if bt.get("mortgageAllowed") is not None:
        mortgage = bool(bt["mortgageAllowed"])
    elif offer.get("mortgageAllowed") is not None:
        mortgage = bool(offer["mortgageAllowed"])
    prices_all = bt.get("prices") if isinstance(bt.get("prices"), dict) else {}
    price_usd = prices_all.get("usd") or offer.get("priceUsd") or bt.get("priceUsd")
    price_eur = prices_all.get("eur") or offer.get("priceEur") or bt.get("priceEur")

    # v0.3.4 (ТЗ реалтора): торги/аукционы ДГИ/ЦУГИ
    # (в старом формате isAuction лежит в offers[0] = first)
    is_auction = offer.get("isAuction", first.get("isAuction"))
    trading_link = (offer.get("tradingLink") or offer.get("trading_url")
                    or first.get("tradingLink") or first.get("trading_url"))

    return Pricing(
        price_total_rub=total,
        price_per_m2_rub=per_m2,
        price_history=history,
        sale_type=sale_type,
        mortgage_allowed=mortgage,
        price_usd=price_usd,
        price_eur=price_eur,
        is_auction=bool(is_auction) if is_auction is not None else None,
        trading_link=str(trading_link) if trading_link else None,
    )


def _extract_parameters(
    soup: BeautifulSoup, json_data: dict[str, Any], offer_data: dict[str, Any]
) -> Parameters:
    offer = _offer_of(offer_data)
    factoids = _factoids_from_container(soup)
    summary = _summary_pairs_from_container(soup)
    # merge: factoids + summary pairs are both {lowercase_title: value}
    merged = {**summary, **factoids}

    def _pick(*keys: str) -> str | None:
        for key in keys:
            if key in merged:
                return merged[key]
        return None

    # areas: JSON first, then summary/factoid titles
    area_total = _normalize_area(str(offer.get("totalArea"))) if offer.get("totalArea") is not None else None
    if area_total is None:
        area_total = _normalize_area(_pick("общая площадь", "общая"))
    area_living = _normalize_area(str(offer.get("livingArea"))) if offer.get("livingArea") is not None else None
    if area_living is None:
        area_living = _normalize_area(_pick("жилая площадь", "жилая"))
    area_kitchen = _normalize_area(str(offer.get("kitchenArea"))) if offer.get("kitchenArea") is not None else None
    if area_kitchen is None:
        area_kitchen = _normalize_area(_pick("площадь кухни", "кухня"))

    floor = offer.get("floorNumber")
    floors_total = None
    building_json = offer.get("building")
    if isinstance(building_json, dict) and building_json.get("floorsCount") is not None:
        floors_total = int(building_json["floorsCount"])
    if floor is None:
        floor, floors_total_json = _parse_floor(_pick("этаж"))
        if floor is not None and floors_total is None:
            floors_total = floors_total_json
    else:
        floor = int(floor)

    ceiling = None
    if isinstance(building_json, dict) and building_json.get("ceilingHeight") is not None:
        ceiling = _normalize_number(str(building_json["ceilingHeight"]))
    if ceiling is None:
        ceiling = _normalize_number(_pick("высота потолков"))

    balcony = _pick("балкон", "лоджия")
    bathroom = _parse_bathroom(_pick("санузел"))
    if bathroom is None:
        combined = offer.get("combinedWcsCount")
        separated = offer.get("separatedWcCount")
        parts = []
        if combined:
            parts.append(f"{combined} совмещенный")
        if separated:
            parts.append(f"{separated} раздельный")
        if parts:
            bathroom = ", ".join(parts)

    decoration = offer.get("decoration")
    renovation = (
        _parse_renovation(str(decoration)) if decoration else _parse_renovation(_pick("ремонт", "отделка"))
    )

    window_view = None
    wvt = offer.get("windowsViewType")
    if wvt:
        window_view = _parse_window_view(str(wvt))
    else:
        window_view = _parse_window_view(_pick("вид из окон"))

    rooms_type = _parse_rooms_type(_pick("комнаты"))

    # v0.3.1 (реалтор-аудит §3): физические параметры раздельно
    loggias_count = offer.get("loggiasCount")
    balconies_count = offer.get("balconiesCount")
    separate_wcs = offer.get("separateWcsCount")
    combined_wcs = offer.get("combinedWcsCount")
    # roomType: JSON (roomType/separate|combined) + DOM-fallback
    rooms_type_json = offer.get("roomType")
    if rooms_type_json:
        rooms_type = str(rooms_type_json)
    # addedTime/lastEditTime живут в offer, а не в offerData верхнем уровне
    added_time = offer.get("addedTime")
    edit_time = offer.get("lastEditTime")
    furniture = offer.get("isSoldFurnished") or offer.get("hasFurniture")
    furniture_str = None
    if offer.get("isSoldFurnished") is True:
        furniture_str = "furnished"
    elif offer.get("hasFurniture") is True:
        furniture_str = "partial"
    elif offer.get("hasFurniture") is False or offer.get("isSoldFurnished") is False:
        furniture_str = "no"
    layouts = []
    cl = offer.get("cianLayouts")
    if isinstance(cl, list):
        layouts = [item.get("fullUrl") or item.get("url") for item in cl
                   if isinstance(item, dict) and (item.get("fullUrl") or item.get("url"))]

    # v0.4.0 (ТЗ реалтора): доля в квартире
    share_amount = _normalize_number(str(offer.get("shareAmount"))) if offer.get("shareAmount") is not None else None

    title = _extract_title(soup, json_data)
    if not title and offer.get("title"):
        title = _strip(str(offer["title"]))
    rooms = _parse_rooms(title, merged)
    if rooms is None and offer.get("roomsCount") is not None:
        rooms = int(offer["roomsCount"])

    return Parameters(
        rooms=rooms,
        rooms_type=rooms_type,
        area_total_m2=area_total,
        area_living_m2=area_living,
        area_kitchen_m2=area_kitchen,
        floor=floor,
        floors_total=floors_total,
        ceiling_height_m=ceiling,
        balcony=balcony,
        bathroom=bathroom,
        renovation=renovation,
        window_view=window_view,
        loggias_count=int(loggias_count) if loggias_count is not None else None,
        balconies_count=int(balconies_count) if balconies_count is not None else None,
        separate_wcs_count=int(separate_wcs) if separate_wcs is not None else None,
        combined_wcs_count=int(combined_wcs) if combined_wcs is not None else None,
        furniture=furniture_str,
        layouts=layouts,
        share_amount=share_amount,
    )


def _extract_address_raw(
    soup: BeautifulSoup, json_data: dict[str, Any], offer_data: dict[str, Any] | None = None
) -> str | None:
    if offer_data:
        offer = _offer_of(offer_data)
        geo = offer.get("geo")
        items = geo.get("address") if isinstance(geo, dict) else None
        if isinstance(items, list):
            # By-design: includes city (type=location) in address.
            # SPEC examples include the city, e.g. "Москва, ЮАО, р-н Чертаново Северное, ...".
            parts = [
                _strip(str(item.get("name")))
                for item in items
                if isinstance(item, dict) and item.get("name")
            ]
            parts = [p for p in parts if p]
            if parts:
                return ", ".join(parts)

    offers = json_data.get("offers") if isinstance(json_data, dict) else None
    first = offers[0] if (offers and isinstance(offers, list) and offers) else {}
    if isinstance(first, dict):
        user_input = (first.get("geo") or {}).get("userInput")
        if user_input:
            return _strip(str(user_input))

    address_items = soup.select("[data-name='GeoAddress'] [data-name='GeoAddressItem']")
    if address_items:
        parts = [_strip(item.get_text()) for item in address_items]
        parts = [p for p in parts if p]
        if parts:
            return ", ".join(parts)

    return _find_text(
        soup,
        [
            "[data-name='GeoAddress']",
            "[data-name='Address']",
            "address",
        ],
    )


def _extract_district(area_name_text: str | None) -> str | None:
    if not area_name_text:
        return None
    # Moscow district acronyms. Order matters: longer variants first.
    match = re.search(
        r"\b(?:ЮЗАО|ЮВАО|СЗАО|СВАО|ЗелАО|ЦАО|САО|ВАО|ЮАО|ЗАО)\b",
        area_name_text,
    )
    if match:
        return match.group(0)
    return None


def _extract_area_name(address: str | None, json_data: dict[str, Any]) -> str | None:
    offers = json_data.get("offers") if isinstance(json_data, dict) else None
    first = offers[0] if (offers and isinstance(offers, list) and offers) else {}
    if isinstance(first, dict):
        area = _get_nested(first, "geo", "areaName")
        if area:
            return _strip(str(area))

    if not address:
        return None
    match = re.search(r"р-н\s+([^,]+)", address)
    if match:
        return _strip(match.group(1))
    return None


def _extract_geo(
    soup: BeautifulSoup, json_data: dict[str, Any], offer_data: dict[str, Any] | None = None
) -> Geo:
    offers = json_data.get("offers") if isinstance(json_data, dict) else None
    first = offers[0] if (offers and isinstance(offers, list) and offers) else {}
    offer = _offer_of(offer_data) if offer_data else {}

    lat: float | None = None
    lon: float | None = None
    if offer:
        coords = (offer.get("geo") or {}).get("coordinates")
        if isinstance(coords, dict):
            if coords.get("lat") is not None:
                lat = _normalize_number(str(coords.get("lat")))
            if coords.get("lng") is not None:
                lon = _normalize_number(str(coords.get("lng")))
            if lon is None and coords.get("lon") is not None:
                lon = _normalize_number(str(coords.get("lon")))
    if lat is None and isinstance(first, dict):
        coords = _get_nested(first, "geo", "coordinates", default={})
        if isinstance(coords, dict):
            if coords.get("lat") is not None:
                lat = _normalize_number(str(coords.get("lat")))
            if coords.get("lng") is not None:
                lon = _normalize_number(str(coords.get("lng")))
            if lon is None and coords.get("lon") is not None:
                lon = _normalize_number(str(coords.get("lon")))

    address = _extract_address_raw(soup, json_data, offer_data)
    area_name = _extract_area_name(address, json_data)
    if area_name is None and offer:
        area_name = _geo_address_part(offer, "raion")
    district = _extract_district(address)
    if district is None and offer:
        district = _extract_district(_geo_address_part(offer, "okrug") or "")

    claimed: CianClaimedMetro | None = None
    if isinstance(first, dict):
        metro_list = first.get("metro")
        if isinstance(metro_list, list) and metro_list:
            m = metro_list[0]
            if isinstance(m, dict):
                station = (
                    _strip(str(m.get("name"))) if m.get("name") is not None else None
                )
                time = (
                    _normalize_int(str(m.get("time")))
                    if m.get("time") is not None
                    else None
                )
                transport = (
                    _strip(str(m.get("transportType")))
                    if m.get("transportType") is not None
                    else None
                )
                if station:
                    claimed = CianClaimedMetro(
                        station=station,
                        claimed_time_minutes=time,
                        transport_type=transport,
                    )

    if claimed is None:
        # Underground elements in the main offer block (skip similar-offers
        # carousels by requiring the element NOT inside SimilarOfferItem).
        for underground in soup.select("[data-name='Underground'], [data-name='Metro']"):
            if not isinstance(underground, Tag):
                continue
            if underground.find_parent("[data-name='SimilarOfferItem']"):
                continue
            name_tag = underground.select_one("[data-name='UndergroundName']")
            time_tag = underground.select_one("[data-name='UndergroundTime']")
            station = _strip(name_tag.get_text()) if name_tag else None
            time_text = _strip(time_tag.get_text()) if time_tag else None
            parsed_time: int | None = None
            if not station:
                # fallback: first non-empty text node of the container
                text = _strip(underground.get_text(" "))
                if text:
                    station = text
            if station and re.search(r"\s+\d+\s*мин\.?\s*$", station):
                # station text can carry the time: 'Станция 5 мин.'
                st_match = re.search(r"^(.*?)\s+(\d+)\s*мин\.?\s*$", station)
                if st_match:
                    station = _strip(st_match.group(1))
                    parsed_time = int(st_match.group(2))
            if station:
                time = None
                transport_type = None
                if time_text:
                    match = re.search(r"(\d+)\s*мин", time_text)
                    if match:
                        time = int(match.group(1))
                    if "пешком" in time_text.lower():
                        transport_type = "walk"
                    elif "транспорт" in time_text.lower():
                        transport_type = "transport"
                if time is None and parsed_time is not None:
                    time = parsed_time
                claimed = CianClaimedMetro(
                    station=station,
                    claimed_time_minutes=time,
                    transport_type=transport_type,
                )
                break

    return Geo(
        lat=lat,
        lon=lon,
        district=district,
        area_name=area_name,
        cian_claimed_metro=claimed,
        honest_walk_route=None,
    )


def _extract_building(
    soup: BeautifulSoup, json_data: dict[str, Any], offer_data: dict[str, Any] | None = None
) -> Building:
    house = _house_info_from_container(soup)
    address = _extract_address_raw(soup, json_data, offer_data)
    offer = _offer_of(offer_data) if offer_data else {}
    building_json = offer.get("building") if isinstance(offer, dict) else None
    building_json = building_json if isinstance(building_json, dict) else {}

    building_type = _parse_building_type(house.get("тип дома"))
    if building_type is None:
        material = building_json.get("materialType") or building_json.get("houseMaterialType")
        if material:
            building_type = _parse_building_type(str(material))

    year = _parse_year(house.get("год постройки"))
    if year is None and building_json.get("buildYear") is not None:
        # v0.3.1 fix (реалтор-аудит): у 100% вторички год лежит в
        # offer.building.buildYear, а не в deadline.year новостройки
        year = _parse_year(str(building_json.get("buildYear")))
    if year is None:
        # v0.4.0 (ТЗ реалтора): год встречается и в house.yearBuilt
        house_json = offer.get("house") if isinstance(offer, dict) else None
        if isinstance(house_json, dict) and house_json.get("yearBuilt") is not None:
            year = _parse_year(str(house_json.get("yearBuilt")))
        elif isinstance(offer_data, dict):
            top_house = offer_data.get("house")
            if isinstance(top_house, dict) and top_house.get("yearBuilt") is not None:
                year = _parse_year(str(top_house.get("yearBuilt")))
    if year is None and building_json.get("deadline", {}).get("isComplete"):
        year = _parse_year(str(building_json["deadline"].get("year")))

    series = _strip(house.get("серия дома"))

    floor_material = _parse_floor_material(house.get("перекрытия"))

    elevators_passenger, elevators_cargo = _parse_elevators(house.get("лифты"))
    if elevators_passenger is None and building_json.get("passengerLiftsCount") is not None:
        elevators_passenger = int(building_json["passengerLiftsCount"])
    # v0.3.1 (реалтор-аудит §2): грузовые лифты из JSON
    if elevators_cargo is None and building_json.get("cargoLiftsCount") is not None:
        elevators_cargo = int(building_json["cargoLiftsCount"])

    gas = _parse_yes_no(house.get("газоснабжение"))

    renovation_program = None
    if "реновация" in house:
        renovation_program = _parse_yes_no(house["реновация"])

    # v0.3.1 (реалтор-аудит §2, §4): здание + флаги + парк
    garbage = building_json.get("hasGarbageChute")
    parking = building_json.get("parkingType")
    parking_str = str(parking) if parking else None
    apartments = offer.get("isApartments") if isinstance(offer, dict) else None
    illegal = offer.get("isIllegalConstruction") if isinstance(offer, dict) else None

    return Building(
        address_raw=address,
        house_series=series,
        year_built=year,
        building_type=building_type,
        floor_material=floor_material,
        renovation_program=renovation_program,
        elevators_passenger=elevators_passenger,
        elevators_cargo=elevators_cargo,
        gas=gas,
        has_garbage_chute=bool(garbage) if garbage is not None else None,
        parking_type=parking_str,
        is_apartments=bool(apartments) if apartments is not None else None,
        is_illegal_construction=bool(illegal) if illegal is not None else None,
    )


def _extract_seller(
    soup: BeautifulSoup, offer_data: dict[str, Any] | None = None
) -> Seller:
    name = _strip(
        _find_text(
            soup,
            [
                "[data-name='OfferCardContactsName']",
                "[data-name='ContactName']",
            ],
        )
    )
    phone = _strip(
        _find_text(
            soup,
            [
                "[data-name='OfferCardContactsPhone']",
                "[data-name='ContactPhone']",
            ],
        )
    )
    note = _strip(
        _find_text(
            soup,
            [
                "[data-name='OfferCardContactsNote']",
                "[data-name='ContactNote']",
            ],
        )
    )

    seller_type: str | None = None
    if note:
        lower = note.lower()
        if "агентство" in lower or "агент" in lower:
            seller_type = "realtor"
        elif "застройщик" in lower:
            seller_type = "developer"
        elif "собственник" in lower:
            seller_type = "owner"

    # 1) defaultState.offerData.agent (accountType: agency/developer/owner etc.)
    agent = offer_data.get("agent") if isinstance(offer_data, dict) else None
    if isinstance(agent, dict):
        account_type = agent.get("accountType")
        if account_type == "agency" or account_type == "realtor":
            seller_type = seller_type or "realtor"
        elif account_type == "developer":
            seller_type = seller_type or "developer"
        elif account_type == "owner" or account_type == "private":
            seller_type = seller_type or "owner"
        if not name and agent.get("companyName"):
            name = _strip(str(agent["companyName"]))
        elif not name and agent.get("name"):
            name = _strip(str(agent["name"]))
        # developer name from newObject
        developer = offer_data.get("newObject", {}).get("developer")
        if not name and isinstance(developer, dict) and developer.get("name"):
            name = _strip(str(developer["name"]))
            seller_type = seller_type or "developer"
        if not phone:
            agent_phones = agent.get("phones")
            if isinstance(agent_phones, list) and agent_phones:
                first_phone = agent_phones[0]
                if isinstance(first_phone, dict) and first_phone.get("number"):
                    country = first_phone.get("countryCode") or "+7"
                    phone = _strip(f"{country} {first_phone['number']}")

    # 2) DOM fallback: PhonesContainer text may name the contact type
    if seller_type is None or not name:
        phones_text = _strip(
            _find_text(soup, ["[data-name='PhonesContainer']"])
        )
        if phones_text:
            lower = phones_text.lower()
            if "застройщик" in lower:
                seller_type = seller_type or "developer"
            elif "агент" in lower or "агентство" in lower:
                seller_type = seller_type or "realtor"

    # v0.3.1 (реалтор-аудит §4, §5): собственник, все телефоны, даты
    is_by_homeowner = None
    if isinstance(offer_data, dict):
        # флаг в самом оффере
        if offer_data.get("isByHomeowner") is not None:
            is_by_homeowner = bool(offer_data["isByHomeowner"])
        elif isinstance(offer_data.get("user"), dict) and offer_data["user"].get("isByHomeowner") is not None:
            is_by_homeowner = bool(offer_data["user"]["isByHomeowner"])
    if is_by_homeowner is None and seller_type == "owner":
        is_by_homeowner = True

    phones_list: list[str] = []
    if isinstance(agent, dict):
        agent_phones_all = agent.get("phones")
        if isinstance(agent_phones_all, list):
            for ph in agent_phones_all:
                if isinstance(ph, dict) and ph.get("number"):
                    country = ph.get("countryCode") or "+7"
                    phones_list.append(_strip(f"{country} {ph['number']}"))
    if not phones_list and isinstance(offer_data, dict):
        offer_phones = (offer_data.get("offer", {}) or {}).get("phones") or offer_data.get("phones") or []
        if isinstance(offer_phones, list):
            for ph in offer_phones:
                if isinstance(ph, dict) and ph.get("number"):
                    country = ph.get("countryCode") or "+7"
                    phones_list.append(f"{country} {ph['number']}".strip())
    if not phones_list and phone:
        phones_list = [phone]

    offer_for_dates = offer_data.get("offer") if isinstance(offer_data, dict) else {}
    created_at = (offer_data.get("addedTime")
                  or (offer_for_dates.get("addedTime") if isinstance(offer_for_dates, dict) else None))
    edit_date = (offer_data.get("lastEditTime")
                 or (offer_for_dates.get("lastEditTime") if isinstance(offer_for_dates, dict) else None))

    return Seller(
        seller_type=seller_type,
        name=name,
        agent_phone_masked=phone,
        is_by_homeowner=is_by_homeowner,
        phones=phones_list,
        created_at=str(created_at) if created_at else None,
        edit_date=str(edit_date) if edit_date else None,
    )


def _extract_images(
    soup: BeautifulSoup, offer_data: dict[str, Any] | None = None
) -> list[Image]:
    images: list[Image] = []

    # 1) defaultState.offerData.offer.photos (full objects with URLs)
    offer = _offer_of(offer_data) if offer_data else {}
    photos = offer.get("photos")
    if isinstance(photos, list):
        for photo in photos:
            if not isinstance(photo, dict):
                continue
            url = photo.get("fullUrl") or photo.get("thumbnailUrl")
            if not url:
                continue
            images.append(Image(url=str(url), category=None))

    # 2) DOM fallback (and for pages without JSON state)
    if not images:
        for img in soup.select("[data-name='OfferGalleryImage']"):
            if not isinstance(img, Tag):
                continue
            src = img.get("src") or img.get("data-src")
            alt = _strip(img.get("alt"))
            category: str | None = None
            if alt:
                lower = alt.lower()
                if "план" in lower or "планировк" in lower:
                    category = "plan"
                elif "интерьер" in lower or "комнат" in lower:
                    category = "interior"
                elif "экстерьер" in lower or "дом" in lower:
                    category = "exterior"
            if src:
                images.append(Image(url=str(src), category=category))
        if not images:
            seen: set[str] = set()
            for img in soup.select("img"):
                if not isinstance(img, Tag):
                    continue
                src = img.get("src") or img.get("data-src") or ""
                if "cdn-cian" not in src or not re.search(r"\.(jpe?g|webp|png)", src):
                    continue
                if src in seen:
                    continue
                seen.add(src)
                images.append(Image(url=src, category=None))
    return images


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def _extract_status(
    soup: BeautifulSoup, offer_data: dict[str, Any]
) -> str:
    offer = _offer_of(offer_data)
    raw_status = offer.get("status")
    if raw_status:
        mapping = {"published": "active", "removed": "removed", "sold": "sold"}
        mapped = mapping.get(str(raw_status).lower())
        if mapped:
            return mapped

    # Narrow scan: only title/h1/short leaf elements. A broad scan over all
    # div/span would false-positive on description text like
    # "в ЖК уже продано 100 квартир" (fail-closed: prefer 'active' on doubt).
    for tag in soup.find_all(["title", "h1", "p", "span"]):
        text = (tag.get_text() or "").strip().lower()
        if not text or len(text) > 120:
            continue
        if "объявление удалено" in text or "объявление снято" in text:
            return "removed"
        if "продано" in text and len(text) <= 40:
            return "sold"

    return "active"


def parse_card(html: str) -> ListingCard:
    """Parse a saved Cian card HTML into a :class:`ListingCard`.

    Raises:
        ParseError: if the HTML is empty or no card identity can be extracted.
    """
    if html is None or not html.strip():
        raise ParseError("empty_html")

    try:
        soup = BeautifulSoup(html, "lxml")
    except Exception as exc:
        raise ParseError(f"html_parse_error: {exc}") from exc

    json_data = _extract_json_island(soup)
    offer_data = _extract_default_state(soup)

    card_id = _extract_id(soup, json_data)
    if not card_id:
        # try the defaultState offer id
        offer = _offer_of(offer_data)
        cid = offer.get("cianId") or offer.get("id")
        if cid is not None:
            card_id = f"cian-{cid}"
    if not card_id:
        raise ParseError("cannot_extract_id")

    url = _extract_url(soup, json_data, card_id)
    title = _extract_title(soup, json_data)
    if not title:
        offer_title = _offer_of(offer_data).get("title")
        if offer_title:
            title = _strip(str(offer_title))
    description = _extract_description(soup)
    if not description:
        description = _strip(str(_offer_of(offer_data).get("description") or ""))

    parameters = _extract_parameters(soup, json_data, offer_data)
    building = _extract_building(soup, json_data, offer_data)

    # v0.4.0 (ТЗ реалтора): в домах 14+ этажей газа по строительным нормам нет
    if parameters.floors_total is not None and parameters.floors_total >= 14:
        building.gas = False

    category = _extract_category(json_data, offer_data)

    pricing = _extract_pricing(soup, json_data, offer_data, title=title)
    # P3-3: цена пропала после всех фолбэков — не тишина, а карантин-событие
    if pricing.price_total_rub is None:
        from .price_guard import record_price_drift
        record_price_drift(card_id, url, title)

    return ListingCard(
        id=card_id,
        source="cian",
        url=url or f"https://www.cian.ru/sale/flat/{card_id.replace('cian-', '')}/",
        status=_extract_status(soup, offer_data),
        title=title,
        pricing=pricing,
        parameters=parameters,
        building=building,
        geo=_extract_geo(soup, json_data, offer_data),
        description_text=description,
        category=category,
        seller=_extract_seller(soup, offer_data),
        images=_extract_images(soup, offer_data),
    )
