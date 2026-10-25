"""v0.4.9 (the task brief) F-07b/F-19: risk scoring."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Optional

from .bargain import _load_cards, _ppm2, _percentile
from .models import ListingCard


URGENT_WORDS = ["срочно", "торопимся", "переоценка", "обмен", "срочная"]
DISCOUNT_WORDS = ["без торга", "реально всё", "реально все", "без посредников"]


def _listing(card: Any) -> ListingCard:
    if isinstance(card, ListingCard):
        return card
    if isinstance(card, dict):
        return ListingCard(**card)
    if isinstance(card, str):
        return _load_cards(card)[0]
    raise TypeError("unsupported card")


def _title_caps_ratio(title: str) -> float:
    letters = [ch for ch in title if ch.isalpha()]
    if not letters:
        return 0.0
    caps = [ch for ch in letters if ch.isupper()]
    return len(caps) / len(letters)


def _exclamations(title: str) -> int:
    return title.count("!")


def score_card(card: Any, corpus: Optional[Any] = None, district: Optional[str] = None,
               rooms: Optional[int] = None) -> dict[str, Any]:
    c = _listing(card)
    title = c.title or ""
    low = title.lower()
    reasons: list[str] = []
    score = 0.0

    for w in URGENT_WORDS:
        if w in low:
            reasons.append(f"urgent:{w}")
            score += 0.15

    if _title_caps_ratio(title) > 0.6:
        reasons.append("caps_ratio>0.6")
        score += 0.2

    if _exclamations(title) >= 3:
        reasons.append("exclamations>=3")
        score += 0.15

    # minus signal: discount phrases
    for w in DISCOUNT_WORDS:
        if w in low:
            reasons.append(f"discount_phrase:{w}")
            score -= 0.1

    # price vs group
    bait_reasons: list[str] = []
    bait_suspect = False
    if corpus is not None:
        try:
            corpus_cards = corpus if isinstance(corpus, list) else _load_cards(corpus) if isinstance(corpus, str) else corpus
        except Exception:
            corpus_cards = []
        # normalize
        if not isinstance(corpus_cards, list):
            corpus_cards = []
        # filter district/rooms
        t_district = district or (c.geo.district if c.geo else None)
        t_rooms = rooms if rooms is not None else c.parameters.rooms
        group_prices = []
        for cc in corpus_cards:
            try:
                lc = cc if isinstance(cc, ListingCard) else ListingCard(**cc) if isinstance(cc, dict) else None
            except Exception:
                lc = None
            if lc is None:
                continue
            cd = lc.geo.district if lc.geo else None
            cr = lc.parameters.rooms
            if t_district is not None and cd != t_district:
                continue
            if t_rooms is not None and cr is not None and abs(cr - t_rooms) > 1:
                continue
            p = _ppm2(lc)
            if p is not None:
                group_prices.append(p)
        if len(group_prices) >= 20:
            s = sorted(group_prices)
            p10 = _percentile(s, 0.10)
            median = _percentile(s, 0.5)
            target_price = _ppm2(c)
            if target_price is not None and target_price < p10:
                reasons.append("price_below_p10")
                score += 0.4
            if target_price is not None and median and target_price < 0.6 * median:
                bait_suspect = True
                bait_reasons.append("price_below_0.6_median")
        else:
            # not enough sample, no strong signal
            pass

    score = max(0.0, min(1.0, score))
    if bait_suspect:
        bait_reasons.append("похоже на недостоверное объявление — проверьте звонком")

    return {
        "risk_score": round(score, 3),
        "reasons": reasons,
        "bait_suspect": bait_suspect,
        "bait_reasons": bait_reasons,
    }


def bait_text(result: dict[str, Any]) -> str:
    if not result.get("bait_suspect"):
        return ""
    return "похоже на недостоверное объявление — проверьте звонком: " + "; ".join(result.get("bait_reasons", []))
