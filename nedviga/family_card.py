"""v0.4.7 (the task brief) F-11: Family Decision Card.

Контент-модель карточки из ListingCard + рендеры HTML/Telegram.
"""
from __future__ import annotations

import html as html_mod
from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from .models import ListingCard
from .pii import PHONE_MASK, sanitize_contacts


@dataclass
class FamilyCard:
    listing: ListingCard
    title: str = ""
    address: str = ""
    district: str = ""
    okrug: str = ""
    price_total_rub: Optional[float] = None
    price_per_m2_rub: Optional[float] = None
    rooms: Optional[int] = None
    area_total_m2: Optional[float] = None
    area_living_m2: Optional[float] = None
    area_kitchen_m2: Optional[float] = None
    floor: Optional[int] = None
    floors_total: Optional[int] = None
    house_series: Optional[str] = None
    year_built: Optional[int] = None
    building_type: Optional[str] = None
    floor_material: Optional[str] = None
    elevators_passenger: Optional[int] = None
    elevators_cargo: Optional[int] = None
    has_garbage_chute: Optional[bool] = None
    renovation_program: Optional[bool] = None
    metro_station: Optional[str] = None
    claimed_time_minutes: Optional[int] = None
    walk_distance_meters: Optional[int] = None
    walk_duration_minutes: Optional[float] = None
    routing_provider: Optional[str] = None
    route_verified: bool = False
    photos: list[str] = field(default_factory=list)
    pros: list[str] = field(default_factory=list)
    cons: list[str] = field(default_factory=list)

    # aliases for compatibility
    @property
    def card(self) -> ListingCard:
        return self.listing

    @property
    def source_card(self) -> ListingCard:
        return self.listing

    @property
    def listing_card(self) -> ListingCard:
        return self.listing

    @property
    def images(self) -> list[str]:
        return self.photos


FamilyDecisionCard = FamilyCard


def _listing(card: Any) -> ListingCard:
    if isinstance(card, ListingCard):
        return card
    if isinstance(card, FamilyCard):
        return card.listing
    if isinstance(card, dict):
        try:
            return ListingCard(**card)
        except Exception:
            # maybe already a family card dump
            if "listing" in card:
                return _listing(card["listing"])
            raise
    raise TypeError(f"unsupported card type: {type(card)!r}")


def _none(v: Any) -> str:
    if v is None:
        return "нет данных"
    if isinstance(v, bool):
        return "да" if v else "нет"
    s = str(v).strip()
    return s if s else "нет данных"


def _evaluate(card: ListingCard) -> tuple[list[str], list[str]]:
    pros: list[str] = []
    cons: list[str] = []
    p = card.parameters
    b = card.building
    g = card.geo

    # kitchen
    if p.area_kitchen_m2 is not None and p.area_kitchen_m2 >= 7.5:
        pros.append(f"Кухня {p.area_kitchen_m2:g} м² (подходит под стандарт семьи)")
    elif p.area_kitchen_m2 is not None:
        cons.append(f"Кухня {p.area_kitchen_m2:g} м² — небольшая")

    # floor
    if p.floor is not None:
        if p.floor == 1:
            cons.append("Первый этаж")
        elif p.floors_total and p.floor == p.floors_total:
            cons.append("Крайний (последний) этаж")
        else:
            if p.floors_total:
                pros.append(f"Средний комфортный этаж ({p.floor} из {p.floors_total})")
            else:
                pros.append(f"Этаж {p.floor}")

    # ceilings / floor material
    fm = (b.floor_material or "").lower()
    if "железобетон" in fm or fm == "жб" or "жб" in fm:
        pros.append("ЖБ перекрытия")
    elif b.floor_material:
        # mixed/wood -> nuance
        if "дерев" in fm:
            cons.append("Деревянные перекрытия")
        elif "смеш" in fm:
            cons.append("Смешанные перекрытия")

    # gas
    if b.gas is True:
        cons.append("Газ (газовая плита)")

    # balcony / loggia
    if p.balcony:
        pros.append("Балкон/лоджия")
    else:
        if p.balconies_count is None and p.loggias_count is None:
            pass
        else:
            if (p.balconies_count or 0) + (p.loggias_count or 0) == 0:
                cons.append("Без балкона/лоджии")

    if p.balcony is None and (p.balconies_count or 0) + (p.loggias_count or 0) == 0 and p.balcony is None:
        # only flag if explicitly no balcony info? keep conservative: no minus without data
        pass

    # bathroom
    if p.bathroom and "раздел" in p.bathroom.lower():
        pros.append("С/у раздельный")

    # rooms isolated (best-effort from description? skip)

    # window view
    wv = (p.window_view or "").lower()
    if "двор" in wv or "зелен" in wv or "парк" in wv:
        pros.append("Окна во двор / зелень")

    # walk
    walk = g.honest_walk_route
    if walk and walk.walk_duration_minutes is not None:
        if walk.walk_duration_minutes < 15:
            pros.append(f"{int(walk.walk_duration_minutes)} минут пешком до метро без горок")
        elif walk.walk_duration_minutes > 15:
            cons.append(f"Длинный пеший маршрут ({int(walk.walk_duration_minutes)} мин)")

    # cargo elevator
    if b.elevators_cargo is None or (b.elevators_cargo or 0) == 0:
        # only minus if building has elevators info? conservative: flag if elevators_passenger known
        if b.elevators_passenger is not None:
            cons.append("Нет грузового лифта")

    # house series note
    if b.house_series:
        pros.append(f"Дом серии {b.house_series}")

    # renovation
    if p.renovation and "евро" in p.renovation.lower():
        pros.append("Евроремонт")

    return pros, cons


def build_family_card(card: Any, with_contacts: bool = False) -> FamilyCard:
    c = _listing(card)
    p = c.parameters
    b = c.building
    g = c.geo
    walk = g.honest_walk_route
    claimed = g.cian_claimed_metro.claimed_time_minutes if g.cian_claimed_metro else None
    metro = g.cian_claimed_metro.station if g.cian_claimed_metro else None
    if not metro and walk:
        metro = walk.target_station
    photos = [img.url for img in (c.images or []) if getattr(img, "url", None)]
    pros, cons = _evaluate(c)

    addr = _human(b.address_raw or c.title or "")
    # v0.4.7 контроль качества: ТЗ §2.2 — серия с фолбэком «Индивидуальный проект»
    # (у кодера был мёртвый тернарщик `... if False else ...`, всегда None).
    series = b.house_series or "Индивидуальный проект"

    fc = FamilyCard(
        listing=c,
        title=_human(c.title) or "",
        address=addr,
        district=g.district or "",
        okrug=g.area_name or "",
        price_total_rub=c.pricing.price_total_rub,
        price_per_m2_rub=c.pricing.price_per_m2_rub,
        rooms=p.rooms,
        area_total_m2=p.area_total_m2,
        area_living_m2=p.area_living_m2,
        area_kitchen_m2=p.area_kitchen_m2,
        floor=p.floor,
        floors_total=p.floors_total,
        house_series=series,
        year_built=b.year_built,
        building_type=b.building_type,
        floor_material=b.floor_material,
        elevators_passenger=b.elevators_passenger,
        elevators_cargo=b.elevators_cargo,
        has_garbage_chute=b.has_garbage_chute,
        renovation_program=b.renovation_program,
        metro_station=metro,
        claimed_time_minutes=claimed,
        walk_distance_meters=walk.walk_distance_meters if walk else None,
        walk_duration_minutes=walk.walk_duration_minutes if walk else None,
        routing_provider=walk.routing_provider if walk else None,
        route_verified=walk.route_verified if walk else False,
        photos=photos,
        pros=pros,
        cons=cons,
    )
    return fc


# aliases
build_card = build_family_card
make_family_card = build_family_card
family_card = build_family_card


_SPOT_RE = __import__("re").compile(r"</?external_untrusted_data[^>]*>")


def _human(s: Any) -> str:
    """v0.4.7 контроль качества: семейный формат очищаем от служебных маркеров
    spotlighting (это аннотация парсера, а не текст для людей)."""
    return _SPOT_RE.sub("", str(s or ""))


def _safe_url(u: Any) -> str:
    s = str(u or "").strip()
    low = s.lower()
    if not (low.startswith("http://") or low.startswith("https://")
            or low.startswith("data:image/jpeg") or low.startswith("data:image/png")
            or low.startswith("data:image/webp") or low.startswith("data:image/gif")):
        return ""
    return html_mod.escape(s, quote=True)


def _fmt_price(v: Optional[float]) -> str:
    if v is None:
        return "—"
    return f"{v:,.0f}".replace(",", " ")


def _floor_material_text(v: Optional[str]) -> str:
    if not v:
        return "нет данных"
    low = v.lower()
    if "железобетон" in low or low == "жб" or "жб" in low:
        return "ЖБ"
    return v


def _garbage_text(v: Optional[bool]) -> str:
    if v is None:
        return "нет данных"
    return "есть" if v else "нет"


def _dossier_enrichment(card) -> str:
    try:
        from .dossier import match as _match, db_path as _dbp
        if not _dbp().exists():
            return ""
        res = _match(card)
        if res.get("status") != "ok":
            return ""
        cand = (res.get("candidates") or [None])[0]
        if not cand:
            return ""
        parts = []
        if cand.get("year"):
            parts.append(f"год {cand['year']}")
        if cand.get("floors"):
            parts.append(f"эт. {cand['floors']}")
        if cand.get("cadastral"):
            parts.append(f"кадастр {cand['cadastral']}")
        src = "реестр ЖК data.mos.ru"
        if parts:
            return "🏢 Официально (" + src + "): " + ", ".join(parts)
        return "🏢 Официально (" + src + "): данные реестра"
    except Exception:
        return ""


def _developer_str(card) -> str:
    try:
        import re
        text = (card.description_text or "") + " " + (card.title or "")
        m = re.search(r"(?<!\d)(\d{10}|\d{12})(?!\d)", text)
        if not m:
            return ""
        # only if developer context
        if "застройщик" not in text.lower() and "девелопер" not in text.lower():
            return ""
        return "🏗 Застройщик: ИНН " + m.group(1) + " (кандидат из объявления, реестр 2114)"
    except Exception:
        return ""


def _poi_cached_block(card) -> str:
    try:
        from .poi import _cache_get, _cache_key, _classify
        g = card.geo
        if g.lat is None or g.lon is None:
            return ""
        radius = 15 * 80
        key = _cache_key(g.lat, g.lon, radius)
        cached = _cache_get(key)
        if cached is None:
            return ""
        cats = _classify(cached.get("elements", []) if isinstance(cached, dict) else [], g.lat, g.lon)
        parts = []
        for cat, info in cats.items():
            if isinstance(info, dict) and info.get("count", 0) > 0 and info.get("nearest_m") is not None:
                parts.append(f"{cat} {info['nearest_m']} м")
        if not parts:
            return ""
        return "🏫 Инфраструктура (прямая доступность, кэш на 30 дней): " + ", ".join(parts)
    except Exception:
        return ""


def _walk_text(fc: FamilyCard) -> str:
    if fc.walk_distance_meters is not None and fc.walk_duration_minutes is not None and fc.metro_station:
        return f"м. {fc.metro_station} — {int(fc.walk_duration_minutes)} мин пешком ({fc.walk_distance_meters} м)"
    # v0.4.7 контроль качества: честный фолбэк на заявку Циана с явной пометкой
    # «графом не проверено» — раньше при отсутствии графа блок был «нет данных»,
    # хотя станция и заявленное время в карточке есть (ТЗ §2.3).
    if fc.metro_station and fc.claimed_time_minutes is not None:
        return f"м. {fc.metro_station} — заявлено {int(fc.claimed_time_minutes)} мин пешком (графом не проверено)"
    if fc.metro_station:
        return f"м. {fc.metro_station} — время в пути нет данных"
    return "нет данных"


def _contacts_text(fc: FamilyCard, with_contacts: bool) -> str:
    card = fc.listing
    phones = [str(p) for p in (card.seller.phones if card.seller else []) if str(p or "").strip()]
    if not phones:
        return ""
    if with_contacts:
        return " · ".join(phones)
    return " · ".join(PHONE_MASK for _ in phones)


def render_telegram(card: Any, with_contacts: bool = False) -> str:
    fc = _listing(card) if isinstance(card, ListingCard) else None
    if fc is None:
        # maybe FamilyCard
        if isinstance(card, FamilyCard):
            fc_card = card
        else:
            fc_card = build_family_card(card, with_contacts=with_contacts)
    else:
        fc_card = build_family_card(fc, with_contacts=with_contacts)

    # ensure with_contacts default from render arg
    c = fc_card.listing
    p = c.parameters
    b = c.building

    # title
    title = _human(c.title) or f"{c.id}"
    price = _fmt_price(fc_card.price_total_rub)
    ppm2 = _fmt_price(fc_card.price_per_m2_rub)

    lines: list[str] = []
    lines.append(f"🏠 {title}")
    lines.append(f"💰 {price} ₽ ({ppm2} ₽/м²)")
    lines.append("")
    lines.append(f"📍 Локация: {_walk_text(fc_card)}")
    # v0.4.7 контроль качества: район/округ в карточку (ТЗ §2.2.1) и тип здания в линию дома
    loc_bits = [b for b in (fc_card.okrug, fc_card.district) if b]
    if loc_bits:
        lines.insert(len(lines) - 1, f"🗺 Район: {', '.join(dict.fromkeys(loc_bits))}")
    # house line
    series = _none(fc_card.house_series)
    year = _none(fc_card.year_built)
    fm = _floor_material_text(fc_card.floor_material)
    elevs = []
    if fc_card.elevators_passenger is not None:
        elevs.append(f"{fc_card.elevators_passenger} пасс.")
    if fc_card.elevators_cargo is not None:
        elevs.append(f"{fc_card.elevators_cargo} груз.")
    elev_text = ", ".join(elevs) if elevs else "нет данных"
    if fc_card.elevators_passenger is None and fc_card.elevators_cargo is None:
        elev_text = "нет данных"
    garbage = _garbage_text(fc_card.has_garbage_chute)
    floor_line = ""
    if fc_card.floor is not None or fc_card.floors_total is not None:
        fl = fc_card.floor if fc_card.floor is not None else "?"
        ft = fc_card.floors_total if fc_card.floors_total is not None else "?"
        floor_line = f", этаж {fl}/{ft}"
    bt_map = {"monolith": "монолит", "brick": "кирпич", "panel": "панельный",
              "block": "блочный", "wood": "деревянный", "mixed": "смешанный"}
    bt = bt_map.get(str(fc_card.building_type or "").lower(), fc_card.building_type)
    bt_txt = f"{bt}, " if bt else ""
    lines.append(
        f"🏢 Дом: {series}{(' (' + str(year) + ' г.)') if year != 'нет данных' else ''}, "
        f"{bt_txt}{fm} перекрытия{floor_line}, "
        f"лифты: {elev_text}, мусоропровод: {garbage}"
    )
    # params line
    param_bits = []
    if fc_card.rooms is not None:
        param_bits.append(f"комн. {fc_card.rooms}")
    if fc_card.area_living_m2 is not None:
        param_bits.append(f"жил. {fc_card.area_living_m2:g} м²")
    if fc_card.area_kitchen_m2 is not None:
        param_bits.append(f"кухня {fc_card.area_kitchen_m2:g} м²")
    if fc_card.area_total_m2 is not None:
        param_bits.append(f"общ. {fc_card.area_total_m2:g} м²")
    if c.parameters.bathroom:
        param_bits.append(c.parameters.bathroom)
    if c.parameters.balcony:
        param_bits.append(c.parameters.balcony)
    lines.append("📐 Параметры: " + ", ".join(param_bits) if param_bits else "📐 Параметры: нет данных")
    if getattr(fc_card.listing, "missing_fields", None):
        lines.append("⚠ Не хватает данных: " + ", ".join(fc_card.listing.missing_fields))
    _poi = _poi_cached_block(fc_card.listing)
    if _poi:
        lines.append(_poi)
    _dos = _dossier_enrichment(fc_card.listing)
    if _dos:
        lines.append(_dos)
    _dev = _developer_str(fc_card.listing)
    if _dev:
        lines.append(_dev)
    try:
        from .legal_triage import triage as _triage
        _tr = _triage(fc_card.listing)
        if _tr.get("flags"):
            lines.append("⚠ " + ", ".join(f["code"] for f in _tr["flags"]))
    except Exception:
        pass
    lines.append("")
    lines.append("✅ Плюсы:")
    if fc_card.pros:
        for pr in fc_card.pros:
            lines.append(f"• {pr}")
    else:
        lines.append("• нет данных")
    lines.append("")
    lines.append("⚠️ На что обратить внимание:")
    if fc_card.cons:
        for cn in fc_card.cons:
            lines.append(f"• {cn}")
    else:
        lines.append("• нет данных")
    lines.append("")
    contacts = _contacts_text(fc_card, with_contacts)
    if contacts:
        lines.append(f"📞 Контакты: {contacts}")
    lines.append(f"📸 Фото: {len(fc_card.photos)} шт.")

    text = "\n".join(lines)
    # mask phones in free text (description not included, but safety)
    from .pii import mask_phones
    if not with_contacts:
        text = mask_phones(text)
    return text


def render_html(card: Any, with_contacts: bool = False, embed_photos: bool = False) -> str:
    # resolve
    if isinstance(card, ListingCard):
        fc = build_family_card(card, with_contacts=with_contacts)
    elif isinstance(card, FamilyCard):
        fc = card
    else:
        try:
            fc = build_family_card(card, with_contacts=with_contacts)
        except Exception:
            fc = build_family_card(_listing(card), with_contacts=with_contacts)

    c = fc.listing
    triage_codes = []
    try:
        from .legal_triage import triage as _triage
        triage_codes = [f["code"] for f in _triage(c).get("flags", [])]
    except Exception:
        pass
    # contacts
    contacts_html = ""
    phones = [str(p) for p in (c.seller.phones if c.seller else []) if str(p or "").strip()]
    if phones:
        if with_contacts:
            shown = phones
        else:
            shown = [PHONE_MASK for _ in phones]
        contacts_html = '<div class="contacts">📞 ' + " · ".join(html_mod.escape(p) for p in shown) + "</div>"

    # photos carousel
    slides = ""
    dots = ""
    if fc.photos:
        safe_photos = [u for u in ( _safe_url(p) for p in fc.photos) if u]
        slides = "".join(
            f'<img src="{u}" alt="фото {i}" class="slide{" active" if i == 0 else ""}">'
            for i, u in enumerate(safe_photos)
        )
        dots = "".join(
            f'<span class="dot{" active" if i == 0 else ""}" onclick="showSlide(0,{i},this)"></span>'
            for i in range(len(safe_photos))
        )
    carousel = f'<div class="carousel" id="car0">{slides}<div class="dots">{dots}</div></div>' if fc.photos else ""

    # house details
    def row(label, value):
        return f"<tr><th>{html_mod.escape(label)}</th><td>{html_mod.escape(str(value))}</td></tr>"

    house_rows = ""
    house_rows += row("Серия дома", _none(fc.house_series))
    house_rows += row("Год постройки", _none(fc.year_built))
    house_rows += row("Материал/перекрытия", _none(fc.floor_material))
    house_rows += row("Тип здания", _none(fc.building_type))
    elev = "нет данных"
    if fc.elevators_passenger is not None or fc.elevators_cargo is not None:
        parts = []
        if fc.elevators_passenger is not None:
            parts.append(f"пасс. {fc.elevators_passenger}")
        if fc.elevators_cargo is not None:
            parts.append(f"груз. {fc.elevators_cargo}")
        elev = ", ".join(parts) if parts else "нет данных"
    house_rows += row("Лифты", elev)
    house_rows += row("Мусоропровод", _garbage_text(fc.has_garbage_chute))
    cap = "да" if fc.renovation_program else ("нет" if fc.renovation_program is False else "нет данных")
    house_rows += row("Капремонт", cap)

    walk_str = _walk_text(fc)
    # pros/cons
    pros_html = "".join(f"<li>{html_mod.escape(x)}</li>" for x in fc.pros) or "<li>нет данных</li>"
    cons_html = "".join(f"<li>{html_mod.escape(x)}</li>" for x in fc.cons) or "<li>нет данных</li>"

    params_html = []
    if fc.rooms is not None:
        params_html.append(f"Комнат: {fc.rooms}")
    if fc.area_total_m2 is not None:
        params_html.append(f"Общая: {fc.area_total_m2:g} м²")
    if fc.area_living_m2 is not None:
        params_html.append(f"Жилая: {fc.area_living_m2:g} м²")
    if fc.area_kitchen_m2 is not None:
        params_html.append(f"Кухня: {fc.area_kitchen_m2:g} м²")
    if fc.floor is not None or fc.floors_total is not None:
        params_html.append(f"Этаж: {fc.floor}/{fc.floors_total}")
    params_str = " · ".join(params_html) if params_html else "нет данных"

    html = f"""<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>Семейная карточка — nedviga-cli</title>
<style>
body{{font-family:system-ui,sans-serif;background:#f7f7f7;margin:0;padding:20px;font-size:18px;line-height:1.5;color:#222}}
.card{{max-width:900px;margin:0 auto;background:#fff;border-radius:12px;padding:24px;box-shadow:0 2px 8px rgba(0,0,0,.08)}}
h1{{font-size:1.6em;margin:0 0 8px}}
.price{{font-size:1.5em;font-weight:700;color:#0a7d34;margin:8px 0}}
.meta{{color:#444;margin:8px 0}}
.section{{margin:16px 0}}
.section h2{{font-size:1.2em;margin:0 0 8px;color:#333}}
table{{width:100%;border-collapse:collapse}}
th,td{{text-align:left;padding:6px 8px;border-bottom:1px solid #eee}}
th{{color:#666;width:40%}}
.carousel{{position:relative;height:360px;overflow:hidden;border-radius:10px;margin:12px 0;background:#eee}}
.slide{{display:none;width:100%;height:360px;object-fit:contain;background:#eee}}
.slide.active{{display:block}}
.dots{{position:absolute;bottom:10px;left:0;right:0;text-align:center}}
.dot{{display:inline-block;width:12px;height:12px;border-radius:50%;background:#fff;opacity:.6;margin:0 4px;cursor:pointer}}
.dot.active{{opacity:1;background:#0a7d34}}
ul{{margin:6px 0 6px 20px}}
.contacts{{color:#666;margin:8px 0}}
.walk{{margin:8px 0;color:#2c3e50;font-weight:600}}
</style></head><body>
<div class="card">
  <h1>{html_mod.escape(fc.title or fc.listing.id)}</h1>
  <div class="price">{_fmt_price(fc.price_total_rub)} ₽</div>
  <div class="meta">{html_mod.escape(params_str)} · {_fmt_price(fc.price_per_m2_rub)} ₽/м²</div>
  <div class="meta">{html_mod.escape(fc.address)}</div>
  {carousel}
  <div class="section">
    <h2>Локация</h2>
    <div class="walk">🚇 {html_mod.escape(walk_str)}</div>
  </div>
  <div class="section">
    <h2>Дом</h2>
    <table>{house_rows}</table>
  </div>
  <div class="section">
    <h2>Параметры</h2>
    <div>{html_mod.escape(params_str)}</div>
  </div>
  <div class="section">
    <h2>Плюсы</h2>
    <ul>{pros_html}</ul>
  </div>
  <div class="section">
    <h2>На что обратить внимание</h2>
    <ul>{cons_html}</ul>
  </div>
  {contacts_html}
  <div class="meta">📸 Фото: {len(fc.photos)} шт.</div>
  {'<div class="meta">⚠ Не хватает данных: ' + html_mod.escape(", ".join(fc.listing.missing_fields)) + '</div>' if getattr(fc.listing, "missing_fields", None) else ''}
  {'<div class="meta">⚠ ' + html_mod.escape(", ".join(triage_codes)) + '</div>' if triage_codes else ''}
  {('<div class="meta">' + html_mod.escape(_poi_cached_block(fc.listing)) + '</div>') if _poi_cached_block(fc.listing) else ''}
  {('<div class="meta">' + html_mod.escape(_dossier_enrichment(fc.listing)) + '</div>') if _dossier_enrichment(fc.listing) else ''}
  {('<div class="meta">' + html_mod.escape(_developer_str(fc.listing)) + '</div>') if _developer_str(fc.listing) else ''}
</div>
<script>
function showSlide(ci, si, dot) {{
  const car = document.getElementById('car' + ci);
  if (!car) return;
  car.querySelectorAll('.slide').forEach((s, i) => s.classList.toggle('active', i === si));
  car.querySelectorAll('.dot').forEach((d, i) => d.classList.toggle('active', i === si));
}}
document.querySelectorAll('.carousel').forEach((car, ci) => {{
  const prev = document.createElement('button'); prev.textContent = '‹'; prev.className = 'navbtn prev';
  const next = document.createElement('button'); next.textContent = '›'; next.className = 'navbtn next';
  const go = (d) => {{
    const slides = [...car.querySelectorAll('.slide')];
    const dots = [...car.querySelectorAll('.dot')];
    if (!slides.length) return;
    let cur = dots.findIndex(d => d.classList.contains('active'));
    if (cur < 0) cur = 0;
    cur = (cur + d + slides.length) % slides.length;
    showSlide(ci, cur, dots[cur]);
  }};
  prev.onclick = () => go(-1); next.onclick = () => go(1);
  car.appendChild(prev); car.appendChild(next);
}});
</script>
</body></html>"""

    # mask phones in html text if needed (already handled contacts)
    if not with_contacts:
        from .pii import mask_phones
        html = mask_phones(html)
    return html


# convenience: render methods on FamilyCard
def _attach_methods():
    FamilyCard.render_telegram = lambda self, with_contacts=False: render_telegram(self, with_contacts=with_contacts)
    FamilyCard.render_html = lambda self, with_contacts=False, embed_photos=False: render_html(self, with_contacts=with_contacts, embed_photos=embed_photos)
    FamilyCard.to_telegram = FamilyCard.render_telegram
    FamilyCard.to_html = FamilyCard.render_html


_attach_methods()
