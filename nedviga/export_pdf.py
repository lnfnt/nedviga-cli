"""v0.4.7 (the task brief) F-11: PDF export via WeasyPrint (lazy import)."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from .family_card import FamilyCard, build_family_card, render_html


def _as_html(card: Any, with_contacts: bool = False) -> str:
    if isinstance(card, FamilyCard):
        fc = card
    else:
        fc = build_family_card(card, with_contacts=with_contacts)
    return render_html(fc, with_contacts=with_contacts)


def render_pdf(card: Any, with_contacts: bool = False) -> bytes:
    """Render PDF bytes via WeasyPrint. Raises RuntimeError('pdf-format-unavailable') if missing."""
    html = _as_html(card, with_contacts=with_contacts)
    try:
        from weasyprint import HTML
    except Exception as exc:  # pragma: no cover - depends on env
        raise RuntimeError("pdf-format-unavailable") from exc
    try:
        return HTML(string=html).write_pdf()
    except Exception as exc:
        raise RuntimeError(f"pdf-render-failed: {exc}") from exc


def export_pdf(card: Any, output: Any, with_contacts: bool = False) -> Path:
    """Write PDF to output path. Returns Path."""
    out = Path(output)
    data = render_pdf(card, with_contacts=with_contacts)
    out.write_bytes(data)
    return out


def catalog_pdf(cards, output, title=None, profile=None) -> "Path":
    cards = list(cards or [])
    if len(cards) > 30:
        raise RuntimeError("too_many")
    # limit photos to 6 per card
    prepared = []
    for c in cards:
        try:
            import copy
            cc = copy.copy(c)
            if hasattr(cc, "images"):
                cc.images = list(cc.images or [])[:6]
            prepared.append(cc)
        except Exception:
            prepared.append(c)
    # title page info
    districts = []
    for c in prepared:
        try:
            d = c.geo.district if getattr(c, "geo", None) else None
            if d:
                districts.append(d)
        except Exception:
            pass
    district_str = ", ".join(sorted(set(districts))) if districts else "—"
    title = title or "Каталог подбора"
    date_str = __import__("datetime").date.today().isoformat()
    who = profile or "nedviga-cli"
    parts = []
    parts.append(f"<h1>{__import__('html').escape(title)}</h1>")
    parts.append(f"<p>Дата: {date_str}</p>")
    parts.append(f"<p>Район: {__import__('html').escape(district_str)}</p>")
    parts.append(f"<p>Объектов: {len(prepared)}</p>")
    parts.append(f"<p>Собрал: {__import__('html').escape(str(who))}</p>")
    parts.append("<hr/>")
    for c in prepared:
        try:
            from .family_card import build_family_card, render_html
            fc = build_family_card(c)
            html = render_html(fc, with_contacts=False)
            # extract body content roughly: keep full html but page break
            parts.append('<div style="page-break-after: always;"></div>')
            parts.append(html)
        except Exception as exc:
            parts.append(f"<p>render error: {__import__('html').escape(str(exc))}</p>")
    full_html = "<!DOCTYPE html><html><head><meta charset='utf-8'><style>body{font-family:system-ui}</style></head><body>" + "\n".join(parts) + "</body></html>"
    try:
        from weasyprint import HTML
    except Exception as exc:
        raise RuntimeError("pdf-format-unavailable") from exc
    out = Path(output)
    HTML(string=full_html).write_pdf(str(out))
    return out


# aliases
pdf_from_card = export_pdf
to_pdf = export_pdf
