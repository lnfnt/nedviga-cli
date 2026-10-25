"""v0.5.0 (the task brief) checklist."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

import os
import subprocess
from pathlib import Path as _Path

from .legal_triage import load_legal_data, triage
from .models import ListingCard


def _load_card(card_id: str, file: str) -> ListingCard:
    raw = json.loads(Path(file).read_text(encoding="utf-8"))
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
    for item in raw:
        if isinstance(item, dict) and item.get("id") == card_id:
            return ListingCard(**item)
    if raw and isinstance(raw[0], dict):
        return ListingCard(**raw[0])
    raise ValueError("card not found")


def new_checklist(card_id: str, file: str) -> str:
    card = _load_card(card_id, file)
    data = load_legal_data()
    t = triage(card)
    lines = [f"# Чек-лист юридической проверки — {card_id}", ""]
    lines.append(data.get("disclaimer", ""))
    lines.append("")
    lines.append("## Триаж (red flags)")
    if t["flags"]:
        for f in t["flags"]:
            lines.append(f"- ⚠ {f['code']} ({f['severity']}): {f['text_basis']}")
            lines.append(f"  Проверка: {f['check']}")
    else:
        lines.append("- Маркеры не выявлены (предварительно).")
    lines.append("")
    lines.append("## Пункты проверки")
    for i, item in enumerate(data.get("checklist", []), 1):
        lines.append(f"- [ ] {item}")
    return "\n".join(lines)


def _a2a_bin() -> str:
    return os.environ.get("A2A_BIN", "a2a")


def _drafts_dir() -> Path:
    base = Path(os.environ.get("NEDVIGA_STATE_DIR", str(Path.home() / ".local" / "share" / "nedviga")))
    d = base / "drafts"
    d.mkdir(parents=True, exist_ok=True)
    return d


def handoff(card_id: str, to: str, file: Optional[str] = None) -> dict:
    from .models import ListingCard
    import json as _json

    card = None
    if file:
        try:
            card = _load_card(card_id, file)
        except Exception:
            card = None
    data = load_legal_data()
    t = triage(card) if card is not None else {"flags": [], "disclaimer": data.get("disclaimer")}
    # build obfuscated fact block
    price = None
    address = None
    if card is not None:
        price = card.pricing.price_total_rub
        address = card.building.address_raw
    fact_lines = [f"Карточка: {card_id}"]
    if address:
        fact_lines.append(f"Адрес: {address}")
    if price is not None:
        fact_lines.append(f"Цена: {price}")
    fact_lines.append("Флаги triage:")
    for f in t.get("flags", []):
        fact_lines.append(f"- {f['code']} ({f['severity']}): {f['text_basis']}")
    if not t.get("flags"):
        fact_lines.append("- (нет выявленных маркеров)")
    fact_lines.append("")
    fact_lines.append("Чек-лист:")
    for item in data.get("checklist", []):
        fact_lines.append(f"- [ ] {item}")
    fact_lines.append("")
    fact_lines.append(data.get("disclaimer", ""))
    body = "\n".join(fact_lines)
    subject = f"Handoff: юридическая проверка {card_id}"

    draft_path = _drafts_dir() / f"{card_id}.md"
    draft_path.write_text(body, encoding="utf-8")

    bin_path = _a2a_bin()
    try:
        proc = subprocess.run(
            [bin_path, "mail", "send", "--to", to, "--subject", subject, "--body", body],
            capture_output=True, text=True, timeout=30,
        )
    except Exception as exc:
        return {"ok": False, "reason": f"a2a_unavailable: {exc}", "draft": str(draft_path)}
    if proc.returncode != 0:
        return {"ok": False, "reason": f"a2a_error: {proc.stderr.strip() or proc.stdout.strip()}",
                "draft": str(draft_path), "returncode": proc.returncode}
    return {"ok": True, "draft": str(draft_path), "stdout": proc.stdout.strip()}
