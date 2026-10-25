"""v0.3.5 (ТЗ реалтора): экспорт карточек в автономный HTML-каталог.

Команда: nedviga-cli export --input cards.json --format html
         [--embed-photos] [--output catalog.html]

Карусель: чистый CSS/JS без внешних зависимостей (offline-first).
Фото: --embed-photos вшивает base64 (сжатие до 800px, JPEG q=70),
иначе — прямые ссылки (требуют сеть при просмотре).
"""
from __future__ import annotations

import base64
import html as html_mod
import io
import json
from pathlib import Path

from .models import ListingCard

_EMBED_MAX_BYTES = 300_000  # на фото после сжатия


def _fetch_photo_bytes(url: str, timeout: float = 15.0) -> bytes | None:
    try:
        # v0.3.5: netguard (egress-guard + breaker)
        from .net_guard import guarded_get

        # CDN Циан требует браузерный UA + Referer, иначе 403 (v0.3.4)
        resp = guarded_get(
            url,
            timeout=timeout,
            stream=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (X11; Linux x86_64; rv:130.0) "
                    "Gecko/20100101 Firefox/130.0"
                ),
                "Referer": "https://www.cian.ru/",
                "Accept": "image/avif,image/webp,image/png,image/jpeg,*/*",
            },
        )
        if resp.status_code != 200:
            return None
        return resp.content
    except Exception:
        return None


def _compress(data: bytes, max_side: int = 800, quality: int = 70) -> bytes | None:
    try:
        from PIL import Image

        img = Image.open(io.BytesIO(data)).convert("RGB")
        w, h = img.size
        if max(w, h) > max_side:
            scale = max_side / max(w, h)
            img = img.resize((int(w * scale), int(h * scale)), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=quality, optimize=True)
        return buf.getvalue()
    except Exception:
        return None


def _photo_src(card: ListingCard, idx: int, embed: bool) -> str | None:
    photos = [p.url for p in (card.images or []) if getattr(p, "url", None)]
    if not photos:
        return None
    url = photos[0]  # в карусель идут все, но первый — обложка
    if not embed:
        return url
    data = _fetch_photo_bytes(url)
    if data is None:
        return url  # fallback на ссылку
    compressed = _compress(data)
    if compressed is None or len(compressed) > _EMBED_MAX_BYTES * 2:
        return url
    return "data:image/jpeg;base64," + base64.b64encode(compressed).decode("ascii")


def _safe_url(u: object) -> str:
    """v0.4.4 (независимый аудит sa-2, F-04): allow-list схем + экранирование.

    Внешние данные (images/trading_link из import cards.json) не должны
    превращаться в XSS в автономном HTML-каталоге. Пустая строка = не выводить.
    """
    s = str(u or "").strip()
    low = s.lower()
    # v0.4.5 (review R3): data:image/svg+xml может нести <script> — allow-list только
    # растров; наш собственный embed всегда jpeg, легитимных потребителей svg нет.
    if not (low.startswith("http://") or low.startswith("https://")
            or low.startswith("data:image/jpeg") or low.startswith("data:image/png")
            or low.startswith("data:image/webp") or low.startswith("data:image/gif")):
        return ""
    return html_mod.escape(s, quote=True)


def _photos_all(card: ListingCard, embed: bool, limit: int = 6) -> list[str]:
    out: list[str] = []
    for p in (card.images or [])[:limit]:
        url = getattr(p, "url", None)
        if not url:
            continue
        if not embed:
            out.append(url)
            continue
        data = _fetch_photo_bytes(url)
        compressed = _compress(data) if data else None
        if compressed:
            out.append("data:image/jpeg;base64," + base64.b64encode(compressed).decode("ascii"))
        else:
            out.append(url)
    return out


def _card_html(card: ListingCard, embed: bool, idx: int) -> str:
    # P3-2: внешний текст мог прийти из cards.json с spotlight-маркерами —
    # для human-facing каталога снимаем их (HTML и так экранируется).
    from .net_guard import strip_spotlight
    title_escaped = html_mod.escape(strip_spotlight(card.title or ""))
    # v0.4.5 (review R3): card.id — внешние данные (import cards.json), в фолбэке экранируем
    title = title_escaped or f"Объявление {html_mod.escape(str(card.id), quote=True)}"
    price = f"{card.pricing.price_total_rub:,.0f}".replace(",", " ") if card.pricing.price_total_rub else "—"
    area = card.parameters.area_total_m2
    rooms = card.parameters.rooms
    floor = card.parameters.floor
    floors_total = card.parameters.floors_total
    year = card.building.year_built
    sale_type = card.pricing.sale_type
    is_auction = card.pricing.is_auction
    metro = card.geo.cian_claimed_metro.station if card.geo.cian_claimed_metro else None
    walk = card.geo.honest_walk_route

    walk_html = ""
    if walk:
        overclaim_flag = ""
        oc = card.geo.honest_overclaim
        if oc and oc.get("flag"):
            overclaim_flag = (' <span style="color:#c0392b">⚠ Циан занижает на '
                              f'{html_mod.escape(str(oc["overclaim_minutes"]), quote=True)} мин</span>')
        walk_html = (
            f'<div class="walk">🚇 {html_mod.escape(walk.target_station or "")}: '
            f'{html_mod.escape(str(walk.walk_distance_meters), quote=True)} м ≈ {walk.walk_duration_minutes:.0f} мин '
            f'<span class="prov">({html_mod.escape(str(walk.routing_provider), quote=True)})</span>{overclaim_flag}</div>'
        )

    auction_html = ""
    if is_auction:
        link = _safe_url(card.pricing.trading_link)  # v0.4.4 F-04: схемы фильтрует
        auction_html = (
            f'<div class="auction">🔨 Аукцион'
            + (f' — <a href="{link}">торги</a>' if link else "")
            + "</div>"
        )

    photos = _photos_all(card, embed)
    slides = ""
    dots = ""
    if photos:
        slides = "".join(
            f'<img src="{_safe_url(p)}" alt="фото {idx}-{i}" class="slide{" active" if i == 0 else ""}">'
            for i, p in enumerate(photos) if _safe_url(p)
        )
        dots = "".join(
            f'<span class="dot{" active" if i == 0 else ""}" onclick="showSlide({idx},{i},this)"></span>'
            for i in range(len(photos))
        )
    carousel = f'<div class="carousel" id="car{idx}">{slides}<div class="dots">{dots}</div></div>' if photos else ""

    # v0.4.6 (the task brief F-13): контакты продавца. Сюда попадают уже маскированные
    # card.seller.phones — export_html() применяет sanitize_contacts по умолчанию;
    # сырые номера возможны только при явном with_contacts=True.
    contacts_html = ""
    seller_phones = [
        str(p) for p in (card.seller.phones if card.seller else []) if str(p or "").strip()
    ]
    if seller_phones:
        contacts_html = (
            '<div class="contacts">📞 '
            + " · ".join(html_mod.escape(p) for p in seller_phones)
            + "</div>"
        )

    return f"""
<div class="card" id="c{idx}">
  {carousel}
  <h3>{title}</h3>
  <div class="price">{price} ₽</div>
  <div class="meta">
    {'комн: ' + str(rooms) if rooms is not None else ''} {'· ' if rooms is not None else ''}{area or '—'} м²
    {'· этаж ' + str(floor) + '/' + str(floors_total) if floor else ''}
    {'· ' + str(year) + ' г.' if year else ''}
    {'· ' + html_mod.escape(sale_type) if sale_type else ''}
  </div>
  {walk_html}
  {auction_html}
  {contacts_html}
  <div class="url"><a href="{html_mod.escape(card.url)}">{html_mod.escape(card.url)}</a></div>
</div>"""


_TEMPLATE = """<!DOCTYPE html>
<html lang="ru"><head><meta charset="utf-8">
<title>Каталог квартир — nedviga-cli</title>
<style>
body{font-family:system-ui,sans-serif;background:#f5f6f7;margin:20px}
h1{font-size:1.4em}
.card{background:#fff;border-radius:10px;padding:16px;margin:14px 0;box-shadow:0 1px 4px rgba(0,0,0,.08)}
.price{font-size:1.3em;font-weight:700;color:#0a7d34}
.meta{color:#555;margin:6px 0}
.walk{margin:6px 0;color:#2c3e50}
.prov{color:#999;font-size:.85em}
.auction{color:#8e44ad;font-weight:600}
.contacts{color:#666;margin:4px 0;font-size:.95em}
.url a{color:#2471a3;font-size:.85em;word-break:break-all}
.carousel{position:relative;height:240px;overflow:hidden;border-radius:8px;margin-bottom:10px;background:#eee}
.slide{display:none;width:100%;height:240px;object-fit:cover}
.slide.active{display:block}
.dots{position:absolute;bottom:8px;left:0;right:0;text-align:center}
.dot{display:inline-block;width:10px;height:10px;border-radius:50%;background:#fff;opacity:.6;margin:0 3px;cursor:pointer}
.dot.active{opacity:1;background:#0a7d34}
.navbtn{position:absolute;top:50%;transform:translateY(-50%);background:rgba(255,255,255,.8);
 border:none;border-radius:50%;width:34px;height:34px;font-size:18px;cursor:pointer}
.navbtn.prev{left:8px}.navbtn.next{right:8px}
</style></head><body>
<h1>Каталог квартир — nedviga-cli</h1>
{cards}
<script>
function showSlide(ci, si, dot) {{
  const car = document.getElementById('car' + ci);
  car.querySelectorAll('.slide').forEach((s, i) => s.classList.toggle('active', i === si));
  car.querySelectorAll('.dot').forEach((d, i) => d.classList.toggle('active', i === si));
}}
document.querySelectorAll('.carousel').forEach((car, ci) => {{
  const prev = document.createElement('button'); prev.textContent = '‹'; prev.className = 'navbtn prev';
  const next = document.createElement('button'); next.textContent = '›'; next.className = 'navbtn next';
  const go = (d) => {{
    const slides = [...car.querySelectorAll('.slide')];
    const dots = [...car.querySelectorAll('.dot')];
    let cur = dots.findIndex(d => d.classList.contains('active'));
    cur = (cur + d + slides.length) % slides.length;
    showSlide(ci, cur, dots[cur]);
  }};
  prev.onclick = () => go(-1); next.onclick = () => go(1);
  car.appendChild(prev); car.appendChild(next);
}});
</script>
</body></html>"""


def export_html(
    cards: list[ListingCard],
    output: Path,
    embed_photos: bool = False,
    with_contacts: bool = False,
) -> Path:
    """Собрать автономный HTML-каталог. Возвращает путь к файлу.

    v0.4.6 (the task brief F-13): fail-closed — по умолчанию телефоны во всех
    строках карточек маскируются (``sanitize_contacts``), и в каталог
    попадает только маска. Сырые контакты выводятся лишь при явном
    ``with_contacts=True`` (CLI-флаг ``--with-contacts``).
    """
    if with_contacts:
        prepared = list(cards)
    else:
        from .pii import sanitize_contacts

        prepared = [
            ListingCard(
                **sanitize_contacts(card.model_dump(mode="json", exclude_none=False))
            )
            for card in cards
        ]
    parts = [_card_html(c, embed_photos, i) for i, c in enumerate(prepared)]
    html = _TEMPLATE.replace("{cards}", "\n".join(parts))
    # Убираем лишние {{}} из f-string-безопасного шаблона
    html = html.replace("{{", "{").replace("}}", "}")
    output.write_text(html, encoding="utf-8")
    return output
