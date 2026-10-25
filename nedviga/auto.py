"""v0.5.6 (the task brief) auto selection."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from .models import ListingCard
from .scorefit import score_card
from . import pipeline
from .profiles import get_profile


def _load_cards(path: Optional[str]) -> list[ListingCard]:
    if not path:
        return []
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    if isinstance(raw, dict):
        if "cards" in raw and isinstance(raw["cards"], list):
            raw = raw["cards"]
        elif "data" in raw:
            d = raw["data"]
            raw = d if isinstance(d, list) else ([d] if isinstance(d, dict) else [])
        else:
            raw = [raw]
    if not isinstance(raw, list):
        raw = [raw]
    out = []
    for x in raw:
        if isinstance(x, dict):
            try:
                out.append(ListingCard(**x))
            except Exception:
                pass
        elif isinstance(x, ListingCard):
            out.append(x)
    return out


def _load_profile(profile) -> dict:
    if profile is None:
        return {}
    p = Path(profile)
    if p.exists():
        return json.loads(p.read_text(encoding="utf-8"))
    try:
        return get_profile(profile)
    except Exception:
        return {}


def run(profile=None, file=None, project=None, out=None, live=False, top=20) -> dict:
    prof = _load_profile(profile)
    cards = _load_cards(file)
    if project:
        from .projects import project_cards
        ids = project_cards(project)
        # skeleton cards without geo; still score
        cards = cards + [ListingCard(id=cid, source="cian", url="") for cid in ids]
    # score
    scored = []
    for c in cards:
        r = score_card(c, profile=prof)
        scored.append((r["score"], c))
    scored.sort(key=lambda x: x[0], reverse=True)
    top_cards = [c for _, c in scored[:top]]
    # propose pipeline status=new (idempotent-ish via set_status)
    proposed = []
    for c in top_cards:
        try:
            pipeline.set_status(c.id, "new", note="auto-propose")
            proposed.append(c.id)
        except Exception:
            pass
    result = {"profile": prof, "count": len(top_cards), "proposed": proposed,
              "cards": [{"id": c.id, "score": next(s for s, cc in scored if cc.id == c.id)} for c in top_cards]}
    if out:
        Path(out).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def report(days=7, out=None) -> dict:
    from .digest import build_digest, render
    d = build_digest(days=days)
    text = render(d, fmt="telegram")
    if out:
        Path(out).write_text(text, encoding="utf-8")
    return {"days": days, "text": text, "output": out}
