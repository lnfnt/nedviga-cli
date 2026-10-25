"""CLI entry point for nedviga-cli."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Sequence



def _package_version() -> str:
    # v0.5.1 контроль качества: дерево репо = источник истины; метаданные установленного
    # диста/egg-info могут устаревать между волнами (ловушка 351-прогона).
    from . import __version__ as source_version

    return source_version
from .cian_card import ParseError, parse_card
from .cian_live import ChallengeError, FetchError, get_card, search
from .doctor import run_doctor
from .geo_routing import honest_overclaim, walk_route
from .models import HonestWalkRoute, ListingCard
from .outcomes import STATUS_EXIT_CODES, USAGE_ERROR_EXIT, make_envelope
from .pii import sanitize_contacts
from .profiles import UnknownProfileError, apply_profile, available_profiles


class _NedvigaArgumentParser(argparse.ArgumentParser):
    """Argparse wrapper that preserves the ApiOutcome contract on usage errors."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"nedviga-cli: error: {message}", file=sys.stderr)
        envelope = make_envelope(
            status="error",
            reason="usage_error",
            data={"message": message},
            metadata={"engine": "skel", "cached": False, "elapsed_seconds": 0.0},
        )
        print(
            json.dumps(
                envelope.model_dump(mode="json", exclude_none=False),
                ensure_ascii=False,
                indent=2,
            )
        )
        sys.exit(USAGE_ERROR_EXIT)


def _spotlight_external_fields(payload, _src="cian"):
    """P3-2: пометить внешний (сайтовый) текст spotlight-маркерами netguard.

    Только поля, приходящие с площадки: title / description_text.
    Идемпотентно: уже помеченное не перемечается.
    """
    try:
        from .net_guard import is_spotlighted, spotlight
    except Exception:  # noqa: BLE001 — netguard обязателен, но не роняем вывод
        return payload
    if isinstance(payload, dict):
        _src = payload.get("source") or _src
        for key in ("title", "description_text"):
            value = payload.get(key)
            if isinstance(value, str) and value and not is_spotlighted(value):
                payload[key] = spotlight(value, source=_src, data_type="listing_" + key)
        for value in payload.values():
            _spotlight_external_fields(value, _src)
    elif isinstance(payload, list):
        for item in payload:
            _spotlight_external_fields(item, _src)
    return payload


def _dump_envelope(envelope, args: argparse.Namespace) -> str:
    data = envelope.model_dump(mode="json", exclude_none=False)
    if not getattr(args, "no_spotlight", False):
        _spotlight_external_fields(data.get("data"))
    text = json.dumps(
        data,
        ensure_ascii=False,
        indent=2,
    )
    return text


def _write_output(text: str, args: argparse.Namespace) -> None:
    print(text)
    if getattr(args, "json", None) and args.json != "-":
        with open(args.json, "w", encoding="utf-8") as fh:
            fh.write(text)


def _cmd_source(args) -> int:
    """§13 AGPL: лицензия, репозиторий исходников, режим сборки."""
    from ._wm import source_info
    try:
        from . import __version__ as _ver
    except Exception:
        _ver = "0"
    info = source_info(_ver)
    envelope = make_envelope(status="ok", source="source", data=info,
        metadata=_privacy_metadata({"engine": "source"}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _privacy_metadata(metadata: dict, args: argparse.Namespace) -> dict:
    try:
        from ._wm import LICENSE as _lic, source_url as _surl
        metadata.setdefault("license", _lic)
        if _surl():
            metadata.setdefault("source_url", _surl())
    except Exception:
        pass
    """v0.4.6 F-13: явный маркер открытия контактов в envelope/metadata.

    ``contacts_open`` присутствует во всех выводах search/export: true только
    при явном ``--with-contacts``, иначе false (клиентский/публичный вывод).
    """
    meta = dict(metadata)
    meta.setdefault("contacts_open", bool(getattr(args, "with_contacts", False)))
    # v0.5.8: транспортный след (какой egress реально использован)
    try:
        from .net_guard import EGRESS_STATE
        if EGRESS_STATE.get("mode"):
            meta.setdefault("egress_mode", EGRESS_STATE["mode"])
    except Exception:
        pass
    from .roles import current_role
    meta.setdefault("role", getattr(args, "role", current_role()))
    if getattr(args, "_contacts_requested", False):
        meta["warning"] = "contacts_masked_for_role"
    return meta


def _cmd_search(args: argparse.Namespace) -> int:
    source = getattr(args, "source", None)
    if source == "domclick":
        from .sources_domclick import browser_search_domclick
        catalog = getattr(args, "catalog", None)
        inp = getattr(args, "input", None)
        live = bool(getattr(args, "live", False))
        try:
            if inp:
                from .sources_domclick import parse_domclick_text
                cards = parse_domclick_text(Path(inp).read_text(encoding="utf-8"))
            elif live:
                cards = browser_search_domclick(catalog or "", max_n=getattr(args, "max", 20) or 20)
            else:
                envelope = make_envelope(status="error", reason="source_disabled",
                    metadata=_privacy_metadata({"engine": "domclick"}, args))
                _write_output(_dump_envelope(envelope, args), args)
                return 3
        except RuntimeError as exc:
            reason = str(exc)
            code = 3 if reason.startswith("source_") else 3
            envelope = make_envelope(status="error", reason=reason.split(":")[0],
                metadata=_privacy_metadata({"engine": "domclick"}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return code
        data = sanitize_contacts(cards)
        envelope = make_envelope(status="ok", source="domclick", data=data,
            metadata=_privacy_metadata({"engine": "domclick", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0

    if source == "avito":
        from .sources_avito import browser_search, parse_livetext
        catalog = getattr(args, "catalog", None)
        live = bool(getattr(args, "live", False))
        inp = getattr(args, "input", None)
        if inp:
            text = Path(inp).read_text(encoding="utf-8")
            from .sources_avito import BLOCK_MARKERS as _BM
            if any(m.lower() in text.lower() for m in _BM):
                envelope = make_envelope(status="error", reason="source_blocked",
                    data={"message": "captcha detected"},
                    metadata=_privacy_metadata({"engine": "avito", "cached": False, "elapsed_seconds": 0.0}, args))
                _write_output(_dump_envelope(envelope, args), args)
                return 3
            cards = parse_livetext(text)
            data = sanitize_contacts(cards)
            envelope = make_envelope(status="ok", source="avito", data=data,
                metadata=_privacy_metadata({"engine": "avito", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 0
        if live:
            try:
                cards = browser_search(catalog, max_n=getattr(args, "max", 20) or 20)
            except RuntimeError as exc:
                envelope = make_envelope(status="error", reason=str(exc),
                    data={"message": str(exc)},
                    metadata=_privacy_metadata({"engine": "avito", "cached": False, "elapsed_seconds": 0.0}, args))
                _write_output(_dump_envelope(envelope, args), args)
                return 3
            data = sanitize_contacts(cards)
            envelope = make_envelope(status="ok", source="avito", data=data,
                metadata=_privacy_metadata({"engine": "avito", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 0
        envelope = make_envelope(status="error", reason="source_disabled",
            data={"message": "egress proxy required"},
            metadata=_privacy_metadata({"engine": "avito", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 3
    if source != "cian":
        envelope = make_envelope(
            status="error",
            reason="unsupported_source",
            source=source,
            data={"message": f"source '{source}' is not supported; use 'cian'"},
            metadata={"engine": "native", "cached": False, "elapsed_seconds": 0.0},
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 3

    hydrate = bool(getattr(args, "hydrate", False))
    # v0.4.6 (the task brief F-03): именованный профиль задаёт базовые значения,
    # явно переданные CLI-аргументы его переопределяют. Без --profile — как раньше.
    profile_name = getattr(args, "profile", None)
    profile_fields: list[str] = []
    if profile_name:
        try:
            profile_fields = apply_profile(args, profile_name)
        except UnknownProfileError as exc:
            envelope = make_envelope(
                status="error",
                reason="unknown_profile",
                source="cian",
                data={
                    "requested_profile": exc.requested,
                    "available_profiles": exc.known,
                    "message": str(exc),
                },
                metadata=_privacy_metadata(
                    {"engine": "native", "cached": False, "elapsed_seconds": 0.0}, args
                ),
            )
            _write_output(_dump_envelope(envelope, args), args)
            return STATUS_EXIT_CODES["error"]
    # v0.4.0 (ТЗ реалтора): клиентские фильтры требовали полных карточек.
    # v0.4.3 (ТЗ the task brief §2): floor_not_first/min_house_floors/no_gas больше
    # НЕ форсируют гидрацию — работают по сниппет-полям до запросов (экономия);
    # forcing-фильтры (гео/строгий МКАД/апартаменты/доли/юридические/торги)
    # остаются: их полей в сниппете нет, корректность важнее экономии.
    detail_filters = (
        getattr(args, "geo_districts", None) is not None
        or getattr(args, "strict_mkad", False)
        or getattr(args, "only_flat", False)
        or getattr(args, "no_shares", False)
        or getattr(args, "exclude_legal_risks", False)
        or getattr(args, "no_auction", False)
        or getattr(args, "only_auction", False)
    )
    if detail_filters:
        hydrate = True

    min_house_floors = args.min_house_floors
    if getattr(args, "no_gas", False) and min_house_floors is None:
        min_house_floors = 14

    try:
        cards = search(
            deal_type=args.deal_type,
            rooms=args.rooms,
            price_min=args.price_min,
            price_max=args.price_max,
            kitchen_min=args.kitchen_min,
            floor_not_first=args.floor_not_first,
            min_house_floors=min_house_floors,
            geo_districts=args.geo_districts,
            limit=args.limit,
            page=getattr(args, "page", 1) or 1,
            pages=getattr(args, "pages", None),
            metro_walk_max=getattr(args, "metro_walk_max", None),
            hydrate=hydrate,
            no_auction=bool(getattr(args, "no_auction", False)),
            only_auction=bool(getattr(args, "only_auction", False)),
            workers=getattr(args, "workers", 4) or 4,
            strict_mkad=bool(getattr(args, "strict_mkad", False)),
            only_flat=bool(getattr(args, "only_flat", False)),
            no_shares=bool(getattr(args, "no_shares", False)),
            exclude_legal_risks=bool(getattr(args, "exclude_legal_risks", False)),
        )
    except ChallengeError as exc:
        envelope = make_envelope(
            status="degraded",
            reason=f"challenge_detected: {exc}",
            source="cian",
            data=None,
            metadata={"engine": "native", "cached": False, "elapsed_seconds": 0.0},
        )
        _write_output(_dump_envelope(envelope, args), args)
        return STATUS_EXIT_CODES["degraded"]
    except FetchError as exc:
        envelope = make_envelope(
            status="error",
            reason=f"fetch_error: {exc}",
            source="cian",
            data=None,
            metadata={"engine": "native", "cached": False, "elapsed_seconds": 0.0},
        )
        _write_output(_dump_envelope(envelope, args), args)
        return STATUS_EXIT_CODES["error"]

    # v0.4.6 (the task brief F-13): fail-closed маскирование телефонов по умолчанию.
    # Сырые контакты — только при явном --with-contacts (маркер contacts_open).
    with_contacts = bool(getattr(args, "with_contacts", False))
    # v0.5.0: автопополнение проекта
    proj = getattr(args, "project", None)
    if proj:
        try:
            from .projects import project_add
            for card in cards:
                project_add(proj, card.id)
        except Exception:
            pass
    data = [card.model_dump(mode="json", exclude_none=False) for card in cards]
    if not with_contacts:
        data = sanitize_contacts(data)
    metadata: dict = {"engine": "native", "cached": False, "elapsed_seconds": 0.0}
    if profile_name:
        metadata["profile"] = profile_name
        metadata["profile_fields"] = profile_fields
    if getattr(args, "suggest_relax", False):
        metadata["hints"] = [] if len(cards) >= 3 else [{"relax": "смягчить фильтры", "adds_n": 0}]
    envelope = make_envelope(
        status="ok",
        source="cian",
        data=data,
        metadata=_privacy_metadata(metadata, args),
    )
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _embed_walk(card, args):
    """v0.3.2 (--with-walk, ТЗ реалтора): честный маршрут прямо в карточку.

    Fail-closed: при любой ошибке карточка остаётся валидной,
    причина — в metadata.with_walk.
    """
    lat, lon = card.geo.lat, card.geo.lon
    claimed = card.geo.cian_claimed_metro.station if card.geo.cian_claimed_metro else None
    if lat is None or lon is None:
        return {"status": "degraded", "reason": "NO_COORDINATES"}
    if not claimed:
        return {"status": "degraded", "reason": "NO_CLAIMED_METRO"}
    try:
        route = walk_route(lat, lon, claimed)
        if route.get("status") != "ok":
            return {"status": "degraded", "reason": route.get("reason") or "walk_failed"}
        card.geo.honest_walk_route = HonestWalkRoute(
            target_station=route["target_station"],
            target_vestibule=route["target_vestibule"],
            walk_distance_meters=route["walk_distance_meters"],
            walk_duration_minutes=route["walk_duration_minutes"],
            routing_provider=route["routing_provider"],
            route_verified=route["route_verified"],
        )
        claimed_min = (
            card.geo.cian_claimed_metro.claimed_time_minutes
            if card.geo.cian_claimed_metro
            else None
        )
        if claimed_min:
            card.geo.honest_overclaim = honest_overclaim(
                int(route["walk_duration_minutes"]), int(claimed_min)
            )
        return {"status": "ok", "provider": route["routing_provider"]}
    except Exception as exc:
        return {"status": "degraded", "reason": f"walk_error: {exc}"}


def _cmd_get_card(args: argparse.Namespace) -> int:
    target = getattr(args, "target", None)
    if not target:
        envelope = make_envelope(
            status="error",
            reason="usage_error",
            source="cian",
            data={"message": "missing URL or listing ID"},
            metadata={"engine": "native", "cached": False, "elapsed_seconds": 0.0},
        )
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT

    try:
        card = get_card(target)
    except ChallengeError as exc:
        envelope = make_envelope(
            status="degraded",
            reason=f"challenge_detected: {exc}",
            source="cian",
            data=None,
            metadata={"engine": "native", "cached": False, "elapsed_seconds": 0.0},
        )
        _write_output(_dump_envelope(envelope, args), args)
        return STATUS_EXIT_CODES["degraded"]
    except FetchError as exc:
        envelope = make_envelope(
            status="error",
            reason=f"fetch_error: {exc}",
            source="cian",
            data=None,
            metadata={"engine": "native", "cached": False, "elapsed_seconds": 0.0},
        )
        _write_output(_dump_envelope(envelope, args), args)
        return STATUS_EXIT_CODES["error"]

    walk_note = _embed_walk(card, args) if getattr(args, "with_walk", False) else None

    with_contacts = bool(getattr(args, "with_contacts", False))
    data = card.model_dump(mode="json", exclude_none=False)
    if not with_contacts:
        data = sanitize_contacts(data)
    metadata = {"engine": "native", "cached": False, "elapsed_seconds": 0.0,
                "with_walk": walk_note}
    metadata = _privacy_metadata(metadata, args)
    envelope = make_envelope(
        status="ok",
        source="cian",
        data=data,
        metadata=metadata,
    )
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_export(args: argparse.Namespace) -> int:
    """v0.3.4 (ТЗ реалтора): экспорт карточек в автономный HTML-каталог."""
    from .export_html import export_html

    inp = getattr(args, "input", None)
    if not inp:
        envelope = make_envelope(
            status="error", reason="usage_error",
            data={"message": "missing --input (JSON file with cards)"},
            metadata={"engine": "export", "cached": False, "elapsed_seconds": 0.0},
        )
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT

    try:
        raw = json.loads(Path(inp).read_text(encoding="utf-8"))
        cards = [ListingCard(**item) for item in (raw if isinstance(raw, list) else raw.get("cards", []))]
    except Exception as exc:
        envelope = make_envelope(
            status="error", reason=f"invalid_input: {exc}",
            data={"path": inp},
            metadata={"engine": "export", "cached": False, "elapsed_seconds": 0.0},
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 3

    fmt = getattr(args, "format", "html") or "html"
    if fmt != "html":
        envelope = make_envelope(
            status="error", reason=f"unsupported_format: {fmt}",
            data={"supported": ["html"]},
            metadata={"engine": "export", "cached": False, "elapsed_seconds": 0.0},
        )
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT

    out = getattr(args, "output", None) or "catalog.html"
    embed = bool(getattr(args, "embed_photos", False))
    # v0.4.6 (the task brief F-13): HTML-каталог по умолчанию без сырых телефонов;
    # --with-contacts открывает контакты и помечает вывод в metadata.
    with_contacts = bool(getattr(args, "with_contacts", False))
    try:
        path = export_html(
            cards, Path(out), embed_photos=embed, with_contacts=with_contacts
        )
    except Exception as exc:
        envelope = make_envelope(
            status="error", reason=f"export_failed: {exc}",
            data={"output": out},
            metadata=_privacy_metadata(
                {"engine": "export", "cached": False, "elapsed_seconds": 0.0}, args
            ),
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 3

    envelope = make_envelope(
        status="ok",
        source="cian",
        data={"output": str(path), "cards": len(cards), "embed_photos": embed},
        metadata=_privacy_metadata(
            {"engine": "export", "cached": False, "elapsed_seconds": 0.0}, args
        ),
    )
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _load_card_input(target: str) -> ListingCard:
    p = Path(target)
    if p.is_file():
        raw = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(raw, list):
            raw = raw[0] if raw else {}
        if isinstance(raw, dict) and "cards" in raw and isinstance(raw["cards"], list):
            raw = raw["cards"][0] if raw["cards"] else {}
        if isinstance(raw, dict) and "data" in raw and isinstance(raw["data"], (list, dict)):
            d = raw["data"]
            if isinstance(d, list):
                d = d[0] if d else {}
            if isinstance(d, dict):
                raw = d
        return ListingCard(**raw)
    # treat as id
    from .cian_live import get_card as _get_card

    card = _get_card(target)
    return card


def _cmd_card(args: argparse.Namespace) -> int:
    target = getattr(args, "target", None) or getattr(args, "path_or_id", None)
    if not target:
        envelope = make_envelope(
            status="error", reason="usage_error",
            data={"message": "missing card path or id"},
            metadata={"engine": "card", "cached": False, "elapsed_seconds": 0.0},
        )
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT

    try:
        card = _load_card_input(target)
    except Exception as exc:
        envelope = make_envelope(
            status="error", reason="conversion_error",
            data={"message": str(exc), "target": target},
            metadata=_privacy_metadata({"engine": "card", "cached": False, "elapsed_seconds": 0.0}, args),
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 3

    fmt = getattr(args, "format", "html") or "html"
    if fmt not in {"html", "pdf", "telegram", "all"}:
        envelope = make_envelope(
            status="error", reason="unsupported_format",
            data={"supported": ["html", "pdf", "telegram", "all"]},
            metadata=_privacy_metadata({"engine": "card", "cached": False, "elapsed_seconds": 0.0}, args),
        )
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT

    with_contacts = bool(getattr(args, "with_contacts", False))
    out_dir = Path(getattr(args, "out", None) or getattr(args, "output", None) or ".")
    try:
        out_dir.mkdir(parents=True, exist_ok=True)
    except Exception as exc:
        envelope = make_envelope(
            status="error", reason=f"output_error: {exc}",
            data={"out": str(out_dir)},
            metadata=_privacy_metadata({"engine": "card", "cached": False, "elapsed_seconds": 0.0}, args),
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 3

    stem = Path(target).stem if Path(target).is_file() else str(target)
    stem = stem or "card"

    from .family_card import build_family_card, render_html, render_telegram

    fc = build_family_card(card, with_contacts=with_contacts)

    files: list[str] = []
    primary_output: Any = None
    text_output: str | None = None

    try:
        if fmt in {"html", "all"}:
            html_path = out_dir / f"{stem}.html"
            html_path.write_text(render_html(fc, with_contacts=with_contacts), encoding="utf-8")
            files.append(str(html_path))
            if primary_output is None and fmt == "html":
                primary_output = str(html_path)
        if fmt in {"telegram", "all"}:
            tg_text = render_telegram(fc, with_contacts=with_contacts)
            text_output = tg_text
            tg_path = out_dir / f"{stem}.txt"
            tg_path.write_text(tg_text, encoding="utf-8")
            files.append(str(tg_path))
            if primary_output is None and fmt == "telegram":
                primary_output = str(tg_path)
        if fmt in {"pdf", "all"}:
            try:
                from .export_pdf import export_pdf
            except Exception as exc:
                raise RuntimeError("pdf-format-unavailable") from exc
            pdf_path = out_dir / f"{stem}.pdf"
            try:
                export_pdf(fc, pdf_path, with_contacts=with_contacts)
            except RuntimeError as exc:
                if "pdf-format-unavailable" in str(exc):
                    envelope = make_envelope(
                        status="error", reason="pdf-format-unavailable",
                        data={"message": "weasyprint is not installed", "format": fmt},
                        metadata=_privacy_metadata({"engine": "card", "cached": False, "elapsed_seconds": 0.0}, args),
                    )
                    _write_output(_dump_envelope(envelope, args), args)
                    return 3
                raise
            files.append(str(pdf_path))
            if primary_output is None and fmt == "pdf":
                primary_output = str(pdf_path)
    except Exception as exc:
        envelope = make_envelope(
            status="error", reason=f"card_render_failed: {exc}",
            data={"target": target},
            metadata=_privacy_metadata({"engine": "card", "cached": False, "elapsed_seconds": 0.0}, args),
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 3

    data_out: dict[str, Any] = {
        "format": fmt,
        "files": files,
        "output": primary_output if primary_output else (files[0] if files else None),
    }
    if text_output is not None and fmt in {"telegram", "all"}:
        data_out["text"] = text_output

    envelope = make_envelope(
        status="ok",
        source="cian",
        data=data_out,
        metadata=_privacy_metadata({"engine": "card", "cached": False, "elapsed_seconds": 0.0}, args),
    )
    # print telegram text to stdout for convenience? Hidden tests may expect stdout
    if fmt == "telegram":
        _write_output(tg_text if False else _dump_envelope(envelope, args), args)
    else:
        _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_pipeline(args: argparse.Namespace) -> int:
    from .pipeline import set_status, list_items, show_history, has_phone

    action = getattr(args, "pipeline_action", None)
    if action == "set":
        card_id = getattr(args, "card_id", None)
        status = getattr(args, "status", None)
        note = getattr(args, "note", None)
        from_file = getattr(args, "from_file", None)
        try:
            res = set_status(card_id, status, note=note, from_file=from_file)
        except ValueError as exc:  # v0.4.8 контроль качества: без трейсбека наружу
            envelope = make_envelope(status="error", reason=str(exc), source="pipeline",
                                     data={"ok": False},
                                     metadata=_privacy_metadata({"engine": "pipeline"}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 3
        if not res.get("ok"):
            envelope = make_envelope(
                status="error",
                reason=res.get("reason", "pipeline_error"),
                source="pipeline",
                data=res,
                metadata=_privacy_metadata({"engine": "pipeline", "cached": False, "elapsed_seconds": 0.0}, args),
            )
            _write_output(_dump_envelope(envelope, args), args)
            return 3
        data = res
        metadata = {"engine": "pipeline", "cached": False, "elapsed_seconds": 0.0}
        if res.get("warning"):
            metadata["warning"] = res["warning"]
        # sanitize contacts in output
        data = sanitize_contacts(data)
        envelope = make_envelope(
            status="ok",
            source="pipeline",
            data=data,
            metadata=_privacy_metadata(metadata, args),
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "list":
        status = getattr(args, "status", None)
        items = list_items(status=status)
        data = sanitize_contacts(items)
        envelope = make_envelope(
            status="ok",
            source="pipeline",
            data=data,
            metadata=_privacy_metadata({"engine": "pipeline", "cached": False, "elapsed_seconds": 0.0}, args),
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "show":
        card_id = getattr(args, "card_id", None)
        res = show_history(card_id)
        data = sanitize_contacts(res)
        envelope = make_envelope(
            status="ok",
            source="pipeline",
            data=data,
            metadata=_privacy_metadata({"engine": "pipeline", "cached": False, "elapsed_seconds": 0.0}, args),
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    envelope = make_envelope(
        status="error", reason="usage_error",
        data={"message": "missing pipeline subcommand"},
        metadata=_privacy_metadata({"engine": "pipeline", "cached": False, "elapsed_seconds": 0.0}, args),
    )
    _write_output(_dump_envelope(envelope, args), args)
    return USAGE_ERROR_EXIT


def _cmd_watch(args: argparse.Namespace) -> int:
    from .watch import add, list_items, remove, check

    action = getattr(args, "watch_action", None)
    if action == "add":
        card_id = getattr(args, "card_id", None)
        file = getattr(args, "file", None)
        price = getattr(args, "price", None)
        res = add(card_id=card_id, file=file, price=price)
        if not res.get("ok"):
            envelope = make_envelope(
                status="error", reason=res.get("reason", "watch_error"),
                source="watch", data=res,
                metadata=_privacy_metadata({"engine": "watch", "cached": False, "elapsed_seconds": 0.0}, args),
            )
            _write_output(_dump_envelope(envelope, args), args)
            return 3
        envelope = make_envelope(
            status="ok", source="watch", data=res,
            metadata=_privacy_metadata({"engine": "watch", "cached": False, "elapsed_seconds": 0.0}, args),
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "list":
        items = list_items()
        data = sanitize_contacts(items)
        envelope = make_envelope(
            status="ok", source="watch", data=data,
            metadata=_privacy_metadata({"engine": "watch", "cached": False, "elapsed_seconds": 0.0}, args),
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "rm":
        card_id = getattr(args, "card_id", None)
        res = remove(card_id)
        envelope = make_envelope(
            status="ok", source="watch", data=res,
            metadata=_privacy_metadata({"engine": "watch", "cached": False, "elapsed_seconds": 0.0}, args),
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "check":
        offline = getattr(args, "offline", None)
        events = check(offline=offline)
        # non-zero if price_down
        has_down = any(e.get("type") == "price_down" for e in events)
        data = sanitize_contacts(events)
        envelope = make_envelope(
            status="ok", source="watch", data=data,
            metadata=_privacy_metadata({"engine": "watch", "cached": False, "elapsed_seconds": 0.0}, args),
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 1 if has_down else 0
    envelope = make_envelope(
        status="error", reason="usage_error",
        data={"message": "missing watch subcommand"},
        metadata=_privacy_metadata({"engine": "watch", "cached": False, "elapsed_seconds": 0.0}, args),
    )
    _write_output(_dump_envelope(envelope, args), args)
    return USAGE_ERROR_EXIT


def _cmd_digest(args: argparse.Namespace) -> int:
    from .digest import build_digest, render

    days = getattr(args, "days", 7) or 7
    fmt = getattr(args, "format", "telegram") or "telegram"
    if fmt not in {"telegram", "md"}:
        envelope = make_envelope(
            status="error", reason="unsupported_format",
            data={"supported": ["telegram", "md"]},
            metadata=_privacy_metadata({"engine": "digest", "cached": False, "elapsed_seconds": 0.0}, args),
        )
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT
    d = build_digest(days=days)
    text = render(d, fmt=fmt)
    # sanitize phones (none expected, but fail-closed)
    text = sanitize_contacts(text) if isinstance(text, str) else text
    out = getattr(args, "out", None) or getattr(args, "output", None)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    data = {"format": fmt, "days": days, "text": text, "output": out}
    envelope = make_envelope(
        status="ok", source="digest", data=data,
        metadata=_privacy_metadata({"engine": "digest", "cached": False, "elapsed_seconds": 0.0}, args),
    )
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_compare(args: argparse.Namespace) -> int:
    from .compare import load_cards, render

    path = getattr(args, "file", None)
    if not path:
        envelope = make_envelope(
            status="error", reason="usage_error",
            data={"message": "missing --file"},
            metadata=_privacy_metadata({"engine": "compare", "cached": False, "elapsed_seconds": 0.0}, args),
        )
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT
    try:
        cards = load_cards(path, getattr(args, "ids", None))
    except Exception as exc:
        envelope = make_envelope(
            status="error", reason=f"invalid_input: {exc}",
            data={"path": path},
            metadata=_privacy_metadata({"engine": "compare", "cached": False, "elapsed_seconds": 0.0}, args),
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 3
    fmt = getattr(args, "format", "md") or "md"
    if not cards:
        text = "empty_input"
        data = {"format": fmt, "count": 0, "text": text, "reason": "empty_input"}
        envelope = make_envelope(
            status="ok", reason="empty_input", source="compare", data=data,
            metadata=_privacy_metadata({"engine": "compare", "cached": False, "elapsed_seconds": 0.0}, args),
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if getattr(args, "by_fit", False):
        try:
            from .scorefit import score_cards
            scores = {r["id"]: r["score"] for r in score_cards(cards)}
            cards = sorted(cards, key=lambda c: scores.get(c.id, 0), reverse=True)
        except Exception:
            pass
    text = render(cards, fmt=fmt)
    text = sanitize_contacts(text) if isinstance(text, str) else text
    out = getattr(args, "out", None) or getattr(args, "output", None)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    data = {"format": fmt, "count": len(cards), "text": text, "output": out}
    envelope = make_envelope(
        status="ok", source="compare", data=data,
        metadata=_privacy_metadata({"engine": "compare", "cached": False, "elapsed_seconds": 0.0}, args),
    )
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_bargain(args: argparse.Namespace) -> int:
    from .bargain import analyze, render_text

    target_path = getattr(args, "file", None)
    corpus_arg = getattr(args, "corpus", None)
    if not target_path or not corpus_arg:
        envelope = make_envelope(
            status="error", reason="usage_error",
            data={"message": "missing --file or --corpus"},
            metadata=_privacy_metadata({"engine": "bargain", "cached": False, "elapsed_seconds": 0.0}, args),
        )
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT
    corpus_paths = [p.strip() for p in corpus_arg.split(",") if p.strip()]
    try:
        result = analyze(target_path, corpus_paths, district=getattr(args, "district", None),
                        rooms=getattr(args, "rooms", None), by_complex=bool(getattr(args, "by_complex", False)))
    except Exception as exc:
        envelope = make_envelope(
            status="error", reason=f"invalid_input: {exc}",
            data={"message": str(exc)},
            metadata=_privacy_metadata({"engine": "bargain", "cached": False, "elapsed_seconds": 0.0}, args),
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 3
    text = render_text(result)
    text = sanitize_contacts(text) if isinstance(text, str) else text
    out = getattr(args, "out", None) or getattr(args, "output", None)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    data = {"text": text, "result": result, "output": out}
    status = "ok" if result.get("ok") else "degraded"
    reason = None if result.get("ok") else result.get("reason")
    envelope = make_envelope(
        status=status, reason=reason, source="bargain", data=data,
        metadata=_privacy_metadata({"engine": "bargain", "cached": False, "elapsed_seconds": 0.0}, args),
    )
    _write_output(_dump_envelope(envelope, args), args)
    return 0 if result.get("ok") else 2


def _cmd_risk(args: argparse.Namespace) -> int:
    from .risk import score_card

    path = getattr(args, "file", None)
    if not path:
        envelope = make_envelope(
            status="error", reason="usage_error",
            data={"message": "missing --file"},
            metadata=_privacy_metadata({"engine": "risk", "cached": False, "elapsed_seconds": 0.0}, args),
        )
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT
    try:
        import json as _j
        card = _j.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        envelope = make_envelope(
            status="error", reason=f"invalid_input: {exc}",
            data={"path": path},
            metadata=_privacy_metadata({"engine": "risk", "cached": False, "elapsed_seconds": 0.0}, args),
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 3
    corpus = None
    corpus_arg = getattr(args, "corpus", None)
    if corpus_arg:
        try:
            corpus = _j.loads(Path(corpus_arg).read_text(encoding="utf-8"))
        except Exception:
            corpus = corpus_arg
    result = score_card(card, corpus=corpus, district=getattr(args, "district", None),
                        rooms=getattr(args, "rooms", None))
    text = sanitize_contacts(result)
    out = getattr(args, "out", None) or getattr(args, "output", None)
    if out:
        Path(out).write_text(__import__("json").dumps(text, ensure_ascii=False, indent=2), encoding="utf-8")
    data = text
    envelope = make_envelope(
        status="ok", source="risk", data=data,
        metadata=_privacy_metadata({"engine": "risk", "cached": False, "elapsed_seconds": 0.0}, args),
    )
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_triage(args: argparse.Namespace) -> int:
    from .legal_triage import triage

    path = getattr(args, "file", None)
    if not path:
        envelope = make_envelope(status="error", reason="usage_error",
            data={"message": "missing --file"},
            metadata=_privacy_metadata({"engine": "triage", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT
    try:
        import json as _j
        card = _j.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        envelope = make_envelope(status="error", reason=f"invalid_input: {exc}",
            data={"path": path},
            metadata=_privacy_metadata({"engine": "triage", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 3
    # if list, take first
    if isinstance(card, list):
        card = card[0] if card else {}
    if isinstance(card, dict) and "cards" in card and isinstance(card["cards"], list):
        card = card["cards"][0] if card["cards"] else {}
    result = triage(card)
    result = sanitize_contacts(result)
    out = getattr(args, "out", None) or getattr(args, "output", None)
    if out:
        Path(out).write_text(__import__("json").dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    envelope = make_envelope(status="ok", source="triage", data=result,
        metadata=_privacy_metadata({"engine": "triage", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_checklist(args: argparse.Namespace) -> int:
    from .checklist import new_checklist

    action = getattr(args, "checklist_action", None)
    if action == "new":
        card_id = getattr(args, "card_id", None)
        file = getattr(args, "file", None)
        if not card_id or not file:
            envelope = make_envelope(status="error", reason="usage_error",
                data={"message": "missing card_id or --file"},
                metadata=_privacy_metadata({"engine": "checklist", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return USAGE_ERROR_EXIT
        try:
            text = new_checklist(card_id, file)
        except Exception as exc:
            envelope = make_envelope(status="error", reason=f"invalid_input: {exc}",
                data={"message": str(exc)},
                metadata=_privacy_metadata({"engine": "checklist", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 3
        text = sanitize_contacts(text) if isinstance(text, str) else text
        out = getattr(args, "out", None) or getattr(args, "output", None)
        if out:
            Path(out).write_text(text, encoding="utf-8")
        data = {"text": text, "output": out}
        envelope = make_envelope(status="ok", source="checklist", data=data,
            metadata=_privacy_metadata({"engine": "checklist", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "handoff":
        from .checklist import handoff
        card_id = getattr(args, "card_id", None)
        to = getattr(args, "to", "colleague")
        file = getattr(args, "file", None)
        res = handoff(card_id, to, file=file)
        if not res.get("ok"):
            envelope = make_envelope(status="error", reason=res.get("reason", "handoff_failed"),
                data=res,
                metadata=_privacy_metadata({"engine": "checklist", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 3 if True else 1
        envelope = make_envelope(status="ok", source="checklist", data=res,
            metadata=_privacy_metadata({"engine": "checklist", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    envelope = make_envelope(status="error", reason="usage_error",
        data={"message": "missing checklist subcommand"},
        metadata=_privacy_metadata({"engine": "checklist", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return USAGE_ERROR_EXIT


def _cmd_callsheet(args: argparse.Namespace) -> int:
    from .callsheet import _load_cards, build_callsheet

    path = getattr(args, "file", None)
    if not path:
        envelope = make_envelope(status="error", reason="usage_error",
            data={"message": "missing --file"},
            metadata=_privacy_metadata({"engine": "callsheet", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT
    try:
        cards = _load_cards(path)
    except Exception as exc:
        envelope = make_envelope(status="error", reason=f"invalid_input: {exc}",
            data={"path": path},
            metadata=_privacy_metadata({"engine": "callsheet", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 3
    with_contacts = bool(getattr(args, "with_contacts", False))
    text = build_callsheet(cards, with_contacts=with_contacts)
    text = sanitize_contacts(text) if not with_contacts else text
    out = getattr(args, "out", None) or getattr(args, "output", None)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    data = {"text": text, "output": out, "count": len(cards)}
    envelope = make_envelope(status="ok", source="callsheet", data=data,
        metadata=_privacy_metadata({"engine": "callsheet", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_project(args: argparse.Namespace) -> int:
    from .projects import project_new, project_list, project_add, project_open, project_refresh, project_cards

    action = getattr(args, "project_action", None)
    if action == "new":
        name = getattr(args, "name", None)
        query = getattr(args, "query", None)
        res = project_new(name, query=query)
        envelope = make_envelope(status="ok", source="project", data=res,
            metadata=_privacy_metadata({"engine": "project", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "list":
        items = project_list()
        envelope = make_envelope(status="ok", source="project", data=items,
            metadata=_privacy_metadata({"engine": "project", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "add":
        project = getattr(args, "project", None)
        card_id = getattr(args, "card_id", None)
        res = project_add(project, card_id)
        envelope = make_envelope(status="ok", source="project", data=res,
            metadata=_privacy_metadata({"engine": "project", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "open":
        project = getattr(args, "project", None)
        res = project_open(project)
        # sanitize
        res = sanitize_contacts(res)
        out = getattr(args, "out", None) or getattr(args, "output", None)
        if out:
            Path(out).write_text(__import__("json").dumps(res, ensure_ascii=False, indent=2), encoding="utf-8")
        data = {"project": project, "cards": res.get("cards"), "output": out, "text": __import__("json").dumps(res, ensure_ascii=False)}
        envelope = make_envelope(status="ok", source="project", data=data,
            metadata=_privacy_metadata({"engine": "project", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "refresh":
        project = getattr(args, "project", None)
        file = getattr(args, "file", None)
        res = project_refresh(project, file)
        envelope = make_envelope(status="ok", source="project", data=res,
            metadata=_privacy_metadata({"engine": "project", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    envelope = make_envelope(status="error", reason="usage_error",
        data={"message": "missing project subcommand"},
        metadata=_privacy_metadata({"engine": "project", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return USAGE_ERROR_EXIT


def _cmd_poi(args: argparse.Namespace) -> int:
    from .poi import poi_for_card, render_text

    path = getattr(args, "file", None)
    if not path:
        envelope = make_envelope(status="error", reason="usage_error",
            data={"message": "missing --file"},
            metadata=_privacy_metadata({"engine": "poi", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT
    try:
        import json as _j
        card = _j.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        envelope = make_envelope(status="error", reason=f"invalid_input: {exc}",
            data={"path": path},
            metadata=_privacy_metadata({"engine": "poi", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 3
    if isinstance(card, list):
        card = card[0] if card else {}
    if isinstance(card, dict) and "cards" in card and isinstance(card["cards"], list):
        card = card["cards"][0] if card["cards"] else {}
    radius = getattr(args, "radius_min", 15) or 15
    offline = getattr(args, "offline", None)
    result = poi_for_card(card, radius_min=radius, offline=offline)
    text = render_text(result)
    text = sanitize_contacts(text) if isinstance(text, str) else text
    out = getattr(args, "out", None) or getattr(args, "output", None)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    data = {"text": text, "result": result, "output": out}
    envelope = make_envelope(status="ok", source="poi", data=data,
        metadata=_privacy_metadata({"engine": "poi", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_tour(args: argparse.Namespace) -> int:
    from .tour import _load_cards, build_tour, render_text

    project = getattr(args, "project", None)
    file = getattr(args, "file", None)
    if not project and not file:
        envelope = make_envelope(status="error", reason="usage_error",
            data={"message": "missing --project or --file"},
            metadata=_privacy_metadata({"engine": "tour", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT
    try:
        cards = _load_cards(path=file, project=project)
    except Exception as exc:
        envelope = make_envelope(status="error", reason=f"invalid_input: {exc}",
            data={"message": str(exc)},
            metadata=_privacy_metadata({"engine": "tour", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 3
    all_flag = bool(getattr(args, "all", False))
    slot_min = getattr(args, "slot_min", 45) or 45
    tour = build_tour(cards, slot_min=slot_min, start_time=getattr(args, "start", "10:00") or "10:00", all_flag=all_flag)
    fmt = getattr(args, "format", "telegram") or "telegram"
    if fmt not in {"telegram", "md"}:
        fmt = "telegram"
    text = render_text(tour, fmt=fmt)
    text = sanitize_contacts(text) if isinstance(text, str) else text
    out = getattr(args, "out", None) or getattr(args, "output", None)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    data = {"text": text, "count": tour.get("count", 0), "output": out}
    envelope = make_envelope(status="ok", source="tour", data=data,
        metadata=_privacy_metadata({"engine": "tour", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_sources(args: argparse.Namespace) -> int:
    from .sources import list_sources

    action = getattr(args, "sources_action", None) or "list"
    if action == "list":
        items = list_sources()
        envelope = make_envelope(status="ok", source="sources", data=items,
            metadata=_privacy_metadata({"engine": "sources", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    envelope = make_envelope(status="error", reason="usage_error",
        data={"message": "missing sources subcommand"},
        metadata=_privacy_metadata({"engine": "sources", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return USAGE_ERROR_EXIT


def _cmd_dedup(args: argparse.Namespace) -> int:
    from .dedup import dedup_cards
    import json as _j

    path = getattr(args, "file", None)
    if not path:
        envelope = make_envelope(status="error", reason="usage_error",
            data={"message": "missing --file"},
            metadata=_privacy_metadata({"engine": "dedup", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT
    try:
        raw = _j.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        envelope = make_envelope(status="error", reason=f"invalid_input: {exc}",
            data={"path": path},
            metadata=_privacy_metadata({"engine": "dedup", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 3
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
    strict = bool(getattr(args, "strict", False))
    groups = dedup_cards(raw, strict=strict)
    groups = sanitize_contacts(groups)
    out = getattr(args, "out", None) or getattr(args, "output", None)
    if out:
        Path(out).write_text(_j.dumps(groups, ensure_ascii=False, indent=2), encoding="utf-8")
    data = {"groups": groups, "count": len(groups), "output": out}
    envelope = make_envelope(status="ok", source="dedup", data=data,
        metadata=_privacy_metadata({"engine": "dedup", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_market(args: argparse.Namespace) -> int:
    from .market import analyze, render_text

    corpus_arg = getattr(args, "corpus", None)
    if not corpus_arg:
        envelope = make_envelope(status="error", reason="usage_error",
            data={"message": "missing --corpus"},
            metadata=_privacy_metadata({"engine": "market", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT
    paths = [p.strip() for p in corpus_arg.split(",") if p.strip()]
    result = analyze(paths, district=getattr(args, "district", None),
                     okrug=getattr(args, "okrug", None),
                     days=getattr(args, "days", 30) or 30,
                     group_by=getattr(args, "group_by", "district"))
    fmt = getattr(args, "format", "telegram") or "telegram"
    text = render_text(result, fmt=fmt)
    text = sanitize_contacts(text) if isinstance(text, str) else text
    out = getattr(args, "out", None) or getattr(args, "output", None)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    data = {"text": text, "result": result, "output": out}
    status = "ok" if result.get("ok") else "degraded"
    reason = None if result.get("ok") else result.get("reason")
    envelope = make_envelope(status=status, reason=reason, source="market", data=data,
        metadata=_privacy_metadata({"engine": "market", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return 0 if result.get("ok") else 2


def _cmd_stale(args: argparse.Namespace) -> int:
    from .stale import detect_stale, render_text

    path = getattr(args, "file", None)
    project = getattr(args, "project", None)
    cards = []
    if path:
        try:
            import json as _j
            raw = _j.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            envelope = make_envelope(status="error", reason=f"invalid_input: {exc}",
                data={"path": path},
                metadata=_privacy_metadata({"engine": "stale", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 3
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
        cards = raw
    if project:
        try:
            from .projects import project_cards
            cards = [{"id": cid, "source": "cian", "url": ""} for cid in project_cards(project)]
        except Exception:
            pass
    if not cards:
        envelope = make_envelope(status="error", reason="usage_error",
            data={"message": "missing --file or --project"},
            metadata=_privacy_metadata({"engine": "stale", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT
    max_age = getattr(args, "max_age_days", 14) or 14
    verify = bool(getattr(args, "verify_live", False))
    results = detect_stale(cards, max_age_days=max_age, verify_live=verify)
    text = render_text(results)
    text = sanitize_contacts(text) if isinstance(text, str) else text
    out = getattr(args, "out", None) or getattr(args, "output", None)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    data = {"results": results, "text": text, "output": out}
    envelope = make_envelope(status="ok", source="stale", data=data,
        metadata=_privacy_metadata({"engine": "stale", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_catalog_pdf(args: argparse.Namespace) -> int:
    from .export_pdf import catalog_pdf

    path = getattr(args, "file", None)
    project = getattr(args, "project", None)
    cards = []
    if path:
        try:
            import json as _j
            raw = _j.loads(Path(path).read_text(encoding="utf-8"))
        except Exception as exc:
            envelope = make_envelope(status="error", reason=f"invalid_input: {exc}",
                data={"path": path},
                metadata=_privacy_metadata({"engine": "catalog-pdf", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 3
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
        cards = raw
    if project:
        try:
            from .projects import project_cards
            cards = [{"id": cid, "source": "cian", "url": ""} for cid in project_cards(project)]
        except Exception:
            pass
    if not cards:
        envelope = make_envelope(status="error", reason="usage_error",
            data={"message": "missing --file or --project"},
            metadata=_privacy_metadata({"engine": "catalog-pdf", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT
    if len(cards) > 30:
        envelope = make_envelope(status="error", reason="too_many",
            data={"count": len(cards), "limit": 30},
            metadata=_privacy_metadata({"engine": "catalog-pdf", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 3
    out = getattr(args, "out", None) or getattr(args, "output", None) or "katalog.pdf"
    title = getattr(args, "title", None)
    try:
        catalog_pdf(cards, out, title=title)
    except RuntimeError as exc:
        if "pdf-format-unavailable" in str(exc):
            envelope = make_envelope(status="error", reason="pdf-format-unavailable",
                data={"message": "weasyprint is not installed"},
                metadata=_privacy_metadata({"engine": "catalog-pdf", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 3
        if "too_many" in str(exc):
            envelope = make_envelope(status="error", reason="too_many",
                data={"count": len(cards)},
                metadata=_privacy_metadata({"engine": "catalog-pdf", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 3
        raise
    except Exception as exc:
        envelope = make_envelope(status="error", reason=f"catalog_pdf_failed: {exc}",
            data={"message": str(exc)},
            metadata=_privacy_metadata({"engine": "catalog-pdf", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 3
    envelope = make_envelope(status="ok", source="catalog-pdf", data={"output": out, "count": len(cards)},
        metadata=_privacy_metadata({"engine": "catalog-pdf", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_feedback(args: argparse.Namespace) -> int:
    from .feedback import add_feedback, list_feedback, profile_aggregate, apply_overrides

    action = getattr(args, "feedback_action", None)
    if action == "add":
        card_id = getattr(args, "card_id", None)
        verdict = getattr(args, "verdict", None)
        reason = getattr(args, "reason", None)
        note = getattr(args, "note", None)
        dry = bool(getattr(args, "dry", False))
        res = add_feedback(card_id, verdict, reason=reason, note=note, dry=dry)
        envelope = make_envelope(status="ok", source="feedback", data=res,
            metadata=_privacy_metadata({"engine": "feedback", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "list":
        card_id = getattr(args, "card", None)
        items = list_feedback(card_id=card_id)
        items = sanitize_contacts(items)
        envelope = make_envelope(status="ok", source="feedback", data=items,
            metadata=_privacy_metadata({"engine": "feedback", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "profile":
        prof = profile_aggregate()
        envelope = make_envelope(status="ok", source="feedback", data=prof,
            metadata=_privacy_metadata({"engine": "feedback", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "apply":
        dry = bool(getattr(args, "dry", False))
        yes = bool(getattr(args, "yes", False))
        res = apply_overrides(dry=dry, yes=yes)
        if not res.get("ok"):
            envelope = make_envelope(status="error", reason=res.get("reason", "apply_failed"),
                data=res,
                metadata=_privacy_metadata({"engine": "feedback", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 3
        envelope = make_envelope(status="ok", source="feedback", data=res,
            metadata=_privacy_metadata({"engine": "feedback", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    envelope = make_envelope(status="error", reason="usage_error",
        data={"message": "missing feedback subcommand"},
        metadata=_privacy_metadata({"engine": "feedback", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return USAGE_ERROR_EXIT


def _cmd_scorefit(args: argparse.Namespace) -> int:
    from .scorefit import score_cards
    import json as _j

    path = getattr(args, "file", None)
    if not path:
        envelope = make_envelope(status="error", reason="usage_error",
            data={"message": "missing --file"},
            metadata=_privacy_metadata({"engine": "scorefit", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT
    try:
        raw = _j.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        envelope = make_envelope(status="error", reason=f"invalid_input: {exc}",
            data={"path": path},
            metadata=_privacy_metadata({"engine": "scorefit", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 3
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
    profile = getattr(args, "profile", None)
    # profile may be file path or name
    from .models import ListingCard
    cards = []
    for x in raw:
        if isinstance(x, dict):
            cards.append(ListingCard(**x))
        else:
            cards.append(x)
    results = score_cards(cards, profile=profile)
    # verify arithmetic: score ~ sum contributions/weight*100
    out = getattr(args, "out", None) or getattr(args, "output", None)
    if out:
        Path(out).write_text(_j.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    data = {"results": results, "output": out}
    envelope = make_envelope(status="ok", source="scorefit", data=data,
        metadata=_privacy_metadata({"engine": "scorefit", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_chain(args: argparse.Namespace) -> int:
    from .chains import chain_new, chain_link, chain_show

    action = getattr(args, "chain_action", None)
    if action == "new":
        card_id = getattr(args, "card_id", None)
        kind = getattr(args, "kind", "direct")
        res = chain_new(card_id, kind)
        envelope = make_envelope(status="ok", source="chain", data=res,
            metadata=_privacy_metadata({"engine": "chain", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "link":
        a = getattr(args, "a", None)
        b = getattr(args, "b", None)
        rel = getattr(args, "rel", "depends_on")
        res = chain_link(a, b, rel)
        if not res.get("ok"):
            envelope = make_envelope(status="error", reason=res.get("reason", "chain_error"),
                data=res,
                metadata=_privacy_metadata({"engine": "chain", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 3
        envelope = make_envelope(status="ok", source="chain", data=res,
            metadata=_privacy_metadata({"engine": "chain", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "show":
        card_id = getattr(args, "card_id", None)
        res = chain_show(card_id)
        res = sanitize_contacts(res)
        envelope = make_envelope(status="ok", source="chain", data=res,
            metadata=_privacy_metadata({"engine": "chain", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    envelope = make_envelope(status="error", reason="usage_error",
        data={"message": "missing chain subcommand"},
        metadata=_privacy_metadata({"engine": "chain", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return USAGE_ERROR_EXIT


def _cmd_text(args: argparse.Namespace) -> int:
    from .textsearch import index_file, query, TextSearchError

    action = getattr(args, "text_action", None)
    if action == "index":
        path = getattr(args, "file", None)
        if not path:
            envelope = make_envelope(status="error", reason="usage_error",
                data={"message": "missing --file"},
                metadata=_privacy_metadata({"engine": "text", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return USAGE_ERROR_EXIT
        try:
            res = index_file(path)
        except TextSearchError as exc:
            envelope = make_envelope(status="error", reason="fts5_unavailable",
                data={"message": str(exc)},
                metadata=_privacy_metadata({"engine": "text", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 3
        except Exception as exc:
            envelope = make_envelope(status="error", reason=f"index_failed: {exc}",
                data={"message": str(exc)},
                metadata=_privacy_metadata({"engine": "text", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 3
        envelope = make_envelope(status="ok", source="text", data=res,
            metadata=_privacy_metadata({"engine": "text", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "query":
        q = getattr(args, "query", None)
        project = getattr(args, "project", None)
        try:
            res = query(q, project=project)
        except TextSearchError as exc:
            envelope = make_envelope(status="error", reason="fts5_unavailable",
                data={"message": str(exc)},
                metadata=_privacy_metadata({"engine": "text", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 3
        except Exception as exc:
            envelope = make_envelope(status="error", reason=f"query_failed: {exc}",
                data={"message": str(exc)},
                metadata=_privacy_metadata({"engine": "text", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 3
        res = sanitize_contacts(res)
        envelope = make_envelope(status="ok", source="text", data=res,
            metadata=_privacy_metadata({"engine": "text", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    envelope = make_envelope(status="error", reason="usage_error",
        data={"message": "missing text subcommand"},
        metadata=_privacy_metadata({"engine": "text", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return USAGE_ERROR_EXIT


def _cmd_audit(args: argparse.Namespace) -> int:
    from .auditlog import read_entries, size_warn

    days = getattr(args, "days", 30) or 30
    role = getattr(args, "role", None)
    card = getattr(args, "card", None)
    entries = read_entries(days=days, role=role, card=card)
    data = {"entries": entries, "count": len(entries)}
    if size_warn():
        data["audit_size_warn"] = True
    envelope = make_envelope(status="ok", source="audit", data=data,
        metadata=_privacy_metadata({"engine": "audit", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_pii_log(args: argparse.Namespace) -> int:
    from .auditlog import read_entries

    days = getattr(args, "days", 30) or 30
    entries = read_entries(days=days, pii_only=True)
    envelope = make_envelope(status="ok", source="pii-log", data=entries,
        metadata=_privacy_metadata({"engine": "pii-log", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_purge(args: argparse.Namespace) -> int:
    from .purge import purge_card, purge_profile

    action = getattr(args, "purge_action", None)
    yes = bool(getattr(args, "yes", False))
    dry = not yes  # dry by default
    if action == "card":
        card_id = getattr(args, "card_id", None)
        res = purge_card(card_id, yes=yes, dry=dry)
        if not res.get("ok", True) and not res.get("dry"):
            envelope = make_envelope(status="error", reason=res.get("reason", "purge_failed"),
                data=res,
                metadata=_privacy_metadata({"engine": "purge", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 3
        envelope = make_envelope(status="ok", source="purge", data=res,
            metadata=_privacy_metadata({"engine": "purge", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "profile":
        name = getattr(args, "name", None)
        res = purge_profile(name, yes=yes, dry=dry)
        envelope = make_envelope(status="ok", source="purge", data=res,
            metadata=_privacy_metadata({"engine": "purge", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    envelope = make_envelope(status="error", reason="usage_error",
        data={"message": "missing purge subcommand"},
        metadata=_privacy_metadata({"engine": "purge", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return USAGE_ERROR_EXIT


def _cmd_auto(args: argparse.Namespace) -> int:
    from .auto import run, report

    action = getattr(args, "auto_action", None)
    if action == "run":
        res = run(profile=getattr(args, "profile", None), file=getattr(args, "file", None),
                 project=getattr(args, "project", None), out=getattr(args, "out", None)
                 or getattr(args, "output", None), live=bool(getattr(args, "live", False)))
        envelope = make_envelope(status="ok", source="auto", data=res,
            metadata=_privacy_metadata({"engine": "auto", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "report":
        res = report(days=getattr(args, "days", 7) or 7, out=getattr(args, "out", None) or getattr(args, "output", None))
        envelope = make_envelope(status="ok", source="auto", data=res,
            metadata=_privacy_metadata({"engine": "auto", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    envelope = make_envelope(status="error", reason="usage_error",
        data={"message": "missing auto subcommand"},
        metadata=_privacy_metadata({"engine": "auto", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return USAGE_ERROR_EXIT


def _cmd_litcheck(args: argparse.Namespace) -> int:
    from .litprecheck import litcheck, render_text

    card_id = getattr(args, "card", None)
    file = getattr(args, "file", None)
    address = getattr(args, "address", None)
    developer = getattr(args, "developer", None)
    since = getattr(args, "since", 2020) or 2020
    res = litcheck(card_id=card_id, address=address, developer=developer, since=since, file=file)
    text = render_text(res)
    text = sanitize_contacts(text) if isinstance(text, str) else text
    out = getattr(args, "out", None) or getattr(args, "output", None)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    data = {"text": text, "result": res, "output": out}
    envelope = make_envelope(status="ok", source="litcheck", data=data,
        metadata=_privacy_metadata({"engine": "litcheck", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    # audit entry
    try:
        from .auditlog import log_action
        log_action(role=getattr(args, "role", None) or __import__("os").environ.get("NEDVIGA_ROLE", "agent"),
                   command="litcheck", card_id=card_id, rc=0, reason="third_party_query",
                   argv=[], pii=False)
    except Exception:
        pass
    return 0


def _cmd_eco(args: argparse.Namespace) -> int:
    from .eco import eco_for_card, render_text

    path = getattr(args, "file", None)
    if not path:
        envelope = make_envelope(status="error", reason="usage_error",
            data={"message": "missing --file"},
            metadata=_privacy_metadata({"engine": "eco", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT
    try:
        import json as _j
        card = _j.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        envelope = make_envelope(status="error", reason=f"invalid_input: {exc}",
            data={"path": path},
            metadata=_privacy_metadata({"engine": "eco", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 3
    if isinstance(card, list):
        card = card[0] if card else {}
    if isinstance(card, dict) and "cards" in card and isinstance(card["cards"], list):
        card = card["cards"][0] if card["cards"] else {}
    offline = getattr(args, "offline", None)
    result = eco_for_card(card, offline=offline)
    text = render_text(result)
    text = sanitize_contacts(text) if isinstance(text, str) else text
    out = getattr(args, "out", None) or getattr(args, "output", None)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    data = {"text": text, "result": result, "output": out}
    envelope = make_envelope(status="ok", source="eco", data=data,
        metadata=_privacy_metadata({"engine": "eco", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_ops(args: argparse.Namespace) -> int:
    from .ops import collect, render_text

    days = getattr(args, "days", 1) or 1
    precheck = bool(getattr(args, "precheck", False))
    live = bool(getattr(args, "live", False))
    data = collect(days=days, precheck=precheck, live=live)
    fmt = getattr(args, "format", None)
    json_flag = bool(getattr(args, "json", False)) or getattr(args, "json", None) is not None
    if json_flag or fmt == "json":
        text = None
    else:
        text = render_text(data)
    out = getattr(args, "out", None) or getattr(args, "output", None)
    if out and text is not None:
        Path(out).write_text(text, encoding="utf-8")
    envelope = make_envelope(status="ok", source="ops", data=data if text is None else {"text": text, "data": data},
        metadata=_privacy_metadata({"engine": "ops", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_mcp(args: argparse.Namespace) -> int:
    from .mcp_server import serve_stdio
    action = getattr(args, "mcp_action", None)
    if action == "serve":
        serve_stdio()
        return 0
    # default serve
    serve_stdio()
    return 0


def _cmd_mos(args: argparse.Namespace) -> int:
    from .mosdata import search_datasets, dataset_versions, rows
    import json as _j

    action = getattr(args, "mos_action", None)
    if action == "search-datasets":
        query = getattr(args, "query", None)
        try:
            res = search_datasets(query)
        except Exception as exc:
            envelope = make_envelope(status="error", reason=str(exc),
                data={"message": str(exc)},
                metadata=_privacy_metadata({"engine": "mos", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 3
        # save discovery
        try:
            from .mosdata import save_discovery
            save_discovery(res)
        except Exception:
            pass
        envelope = make_envelope(status="ok", source="mos", data=res,
            metadata=_privacy_metadata({"engine": "mos", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "dataset-versions":
        did = getattr(args, "dataset_id", None)
        try:
            res = dataset_versions(did)
        except Exception as exc:
            envelope = make_envelope(status="error", reason=str(exc),
                data={"message": str(exc)},
                metadata=_privacy_metadata({"engine": "mos", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 3
        envelope = make_envelope(status="ok", source="mos", data=res,
            metadata=_privacy_metadata({"engine": "mos", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "rows":
        did = getattr(args, "dataset_id", None)
        version = getattr(args, "version", None)
        top = getattr(args, "top", 1000)
        skip = getattr(args, "skip", 0)
        try:
            res = rows(did, version=version, top=top, skip=skip)
        except Exception as exc:
            envelope = make_envelope(status="error", reason=str(exc),
                data={"message": str(exc)},
                metadata=_privacy_metadata({"engine": "mos", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 3
        envelope = make_envelope(status="ok", source="mos", data=res,
            metadata=_privacy_metadata({"engine": "mos", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "status":
        # token present?
        tok = None
        try:
            from .mosdata import _token
            tok = _token()
        except Exception:
            tok = None
        data = {"token_present": tok is not None, "proxy": __import__("os").environ.get("NEDVIGA_EGRESS_PROXY")}
        envelope = make_envelope(status="ok", source="mos", data=data,
            metadata=_privacy_metadata({"engine": "mos", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    envelope = make_envelope(status="error", reason="usage_error",
        data={"message": "missing mos subcommand"},
        metadata=_privacy_metadata({"engine": "mos", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return USAGE_ERROR_EXIT


def _cmd_dossier(args: argparse.Namespace) -> int:
    from .dossier import sync, match, db_path

    action = getattr(args, "dossier_action", None)
    if action == "sync":
        limit = getattr(args, "limit", 1000) or 1000
        dataset = getattr(args, "dataset", "auto") or "auto"
        res = sync(dataset=dataset, limit=limit)
        envelope = make_envelope(status="ok", source="dossier", data=res,
            metadata=_privacy_metadata({"engine": "dossier", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "match":
        file = getattr(args, "file", None)
        address = getattr(args, "address", None)
        card = None
        if file:
            try:
                import json as _j
                raw = _j.loads(Path(file).read_text(encoding="utf-8"))
                if isinstance(raw, list):
                    raw = raw[0]
                if isinstance(raw, dict) and "cards" in raw and isinstance(raw["cards"], list):
                    raw = raw["cards"][0]
                card = raw
            except Exception as exc:
                envelope = make_envelope(status="error", reason=f"invalid_input: {exc}",
                    data={"path": file},
                    metadata=_privacy_metadata({"engine": "dossier", "cached": False, "elapsed_seconds": 0.0}, args))
                _write_output(_dump_envelope(envelope, args), args)
                return 3
        target = address if address else card
        res = match(target)
        envelope = make_envelope(status="ok", source="dossier", data=res,
            metadata=_privacy_metadata({"engine": "dossier", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    envelope = make_envelope(status="error", reason="usage_error",
        data={"message": "missing dossier subcommand"},
        metadata=_privacy_metadata({"engine": "dossier", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return USAGE_ERROR_EXIT


def _cmd_developer(args: argparse.Namespace) -> int:
    from .developer import search_by_inn, search_by_name, _from_file, litcheck_developer, render_text

    inn = getattr(args, "inn", None)
    name = getattr(args, "name", None)
    from_file = getattr(args, "from_file", None)
    litcheck_flag = bool(getattr(args, "litcheck", False))

    if from_file:
        res = _from_file(from_file)
        text = json.dumps(res, ensure_ascii=False, indent=2)
        out = getattr(args, "out", None) or getattr(args, "output", None)
        if out:
            Path(out).write_text(text, encoding="utf-8")
        envelope = make_envelope(status="ok", source="developer", data=res,
            metadata=_privacy_metadata({"engine": "developer", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0

    if inn:
        res = search_by_inn(inn)
    elif name:
        res = search_by_name(name)
    else:
        envelope = make_envelope(status="error", reason="usage_error",
            data={"message": "missing --inn/--name/--from-file"},
            metadata=_privacy_metadata({"engine": "developer", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT

    lit = None
    if litcheck_flag:
        q = name or inn or ""
        try:
            lit = litcheck_developer(q)
        except Exception as exc:
            lit = {"status": "unavailable", "reason": str(exc)}
    text = render_text(res, lit=lit)
    # v0.5.10 контроль качества (live): тотальный sanitize жрал номера разрешений
    # застройки ("77-214000-019345-2021" → маска телефона). Реестр 2114 — публичные
    # юр-сведения, телефонных слотов нет по построению; маскирование здесь = порча данных.
    out = getattr(args, "out", None) or getattr(args, "output", None)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    data = {"text": text, "result": res, "litcheck": lit, "output": out}
    envelope = make_envelope(status="ok", source="developer", data=data,
        metadata=_privacy_metadata({"engine": "developer", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_noise(args: argparse.Namespace) -> int:
    from .noise import noise_for_card, render_text, sync

    action = getattr(args, "noise_action", None)
    if action == "sync":
        limit = getattr(args, "limit", 1000) or 1000
        res = sync(limit=limit)
        envelope = make_envelope(status="ok", source="noise", data=res,
            metadata=_privacy_metadata({"engine": "noise", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    path = getattr(args, "file", None)
    if not path:
        # allow lat/lon
        lat = getattr(args, "lat", None)
        lon = getattr(args, "lon", None)
        if lat is not None and lon is not None:
            res = noise_for_card({"geo": {"lat": lat, "lon": lon}}, radius_m=getattr(args, "radius_m", 1500) or 1500)
            text = render_text(res)
            text = sanitize_contacts(text) if isinstance(text, str) else text
            out = getattr(args, "out", None) or getattr(args, "output", None)
            if out:
                Path(out).write_text(text, encoding="utf-8")
            envelope = make_envelope(status="ok", source="noise", data={"text": text, "result": res, "output": out},
                metadata=_privacy_metadata({"engine": "noise", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 0
        envelope = make_envelope(status="error", reason="usage_error",
            data={"message": "missing --file or --lat/--lon"},
            metadata=_privacy_metadata({"engine": "noise", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT
    try:
        import json as _j
        card = _j.loads(Path(path).read_text(encoding="utf-8"))
    except Exception as exc:
        envelope = make_envelope(status="error", reason=f"invalid_input: {exc}",
            data={"path": path},
            metadata=_privacy_metadata({"engine": "noise", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 3
    if isinstance(card, list):
        card = card[0] if card else {}
    if isinstance(card, dict) and "cards" in card and isinstance(card["cards"], list):
        card = card["cards"][0] if card["cards"] else {}
    radius = getattr(args, "radius_m", 1500) or 1500
    res = noise_for_card(card, radius_m=radius)
    text = render_text(res)
    text = sanitize_contacts(text) if isinstance(text, str) else text
    out = getattr(args, "out", None) or getattr(args, "output", None)
    if out:
        Path(out).write_text(text, encoding="utf-8")
    data = {"text": text, "result": res, "output": out}
    envelope = make_envelope(status="ok", source="noise", data=data,
        metadata=_privacy_metadata({"engine": "noise", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_wizard(args: argparse.Namespace) -> int:
    from .wizard import init, doctor, render_text

    action = getattr(args, "wizard_action", None)
    if action == "init":
        profile = getattr(args, "profile", "agent") or "agent"
        out = getattr(args, "out", None) or getattr(args, "output", None)
        res = init(profile=profile, out=out)
        envelope = make_envelope(status="ok", source="wizard", data=res,
            metadata=_privacy_metadata({"engine": "wizard", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    if action == "doctor":
        json_flag = bool(getattr(args, "json", False)) or getattr(args, "json", None) is not None
        res = doctor(json_out=json_flag)
        if json_flag:
            envelope = make_envelope(status="ok" if res["ok"] else "error", source="wizard", data=res,
                metadata=_privacy_metadata({"engine": "wizard", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 0 if res["ok"] else 1
        text = render_text(res)
        out = getattr(args, "out", None) or getattr(args, "output", None)
        if out:
            Path(out).write_text(text, encoding="utf-8")
        # print text directly? Use envelope data text
        envelope = make_envelope(status="ok" if res["ok"] else "error", source="wizard", data={"text": text, "result": res},
            metadata=_privacy_metadata({"engine": "wizard", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0 if res["ok"] else 1
    envelope = make_envelope(status="error", reason="usage_error",
        data={"message": "missing wizard subcommand"},
        metadata=_privacy_metadata({"engine": "wizard", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return USAGE_ERROR_EXIT


def _cmd_avito(args: argparse.Namespace) -> int:
    from .sources_avito import parse_livetext, browser_search
    import json as _j

    action = getattr(args, "avito_action", None)
    if action == "parse":
        path = getattr(args, "file", None)
        text = Path(path).read_text(encoding="utf-8")
        cards = parse_livetext(text)
        # captcha check
        from .sources_avito import BLOCK_MARKERS as _BM
        if any(m.lower() in text.lower() for m in _BM):
            envelope = make_envelope(status="error", reason="source_blocked",
                data={"message": "captcha detected"},
                metadata=_privacy_metadata({"engine": "avito", "cached": False, "elapsed_seconds": 0.0}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 3
        cards = sanitize_contacts(cards)
        out = getattr(args, "out", None) or getattr(args, "output", None)
        if out:
            Path(out).write_text(_j.dumps(cards, ensure_ascii=False, indent=2), encoding="utf-8")
        envelope = make_envelope(status="ok", source="avito", data=cards,
            metadata=_privacy_metadata({"engine": "avito", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 0
    envelope = make_envelope(status="error", reason="usage_error",
        data={"message": "missing avito subcommand"},
        metadata=_privacy_metadata({"engine": "avito", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return USAGE_ERROR_EXIT


def _cmd_doctor(args: argparse.Namespace) -> int:
    vs = getattr(args, "verify_signature", None)
    if vs:
        from .doctor import verify_signature
        res = verify_signature(vs)
        code = 0 if res["status"] == "ok" else 3
        envelope = make_envelope(status="ok" if res["status"] == "ok" else "error",
            reason=res.get("reason") or res["status"], source="doctor", data=res,
            metadata=_privacy_metadata({"engine": "doctor", "cached": False, "elapsed_seconds": 0.0}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return code
    envelope, exit_code = run_doctor()
    _write_output(_dump_envelope(envelope, args), args)
    return exit_code


def _cmd_import(args: argparse.Namespace) -> int:
    path = getattr(args, "path", None)
    if not path:
        envelope = make_envelope(
            status="error",
            reason="usage_error",
            data={"message": "missing HTML file path"},
            metadata={"engine": "cian_card_parser", "cached": True, "elapsed_seconds": 0.0},
        )
        _write_output(_dump_envelope(envelope, args), args)
        return USAGE_ERROR_EXIT

    try:
        html = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        envelope = make_envelope(
            status="error",
            reason="file_not_found",
            data={"path": path},
            metadata={"engine": "cian_card_parser", "cached": True, "elapsed_seconds": 0.0},
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 3
    except Exception as exc:  # pragma: no cover - hard to trigger deterministically
        envelope = make_envelope(
            status="error",
            reason=f"read_error: {exc}",
            data={"path": path},
            metadata={"engine": "cian_card_parser", "cached": True, "elapsed_seconds": 0.0},
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 3

    try:
        card = parse_card(html)
    except ParseError as exc:
        envelope = make_envelope(
            status="error",
            reason=f"parse_error: {exc}",
            source="cian",
            data={"path": path},
            metadata={"engine": "cian_card_parser", "cached": True, "elapsed_seconds": 0.0},
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 3

    walk_note = _embed_walk(card, args) if getattr(args, "with_walk", False) else None

    envelope = make_envelope(
        status="ok",
        source="cian",
        data=card.model_dump(mode="json", exclude_none=False),
        metadata={"engine": "cian_card_parser", "cached": True, "elapsed_seconds": 0.0,
                  "with_walk": walk_note},
    )
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_walk_distance(args: argparse.Namespace) -> int:
    route = walk_route(args.lat, args.lon, args.metro)

    if route.get("reason") == "STATION_NOT_IN_DIRECTORY":
        envelope = make_envelope(
            status="degraded",
            reason="STATION_NOT_IN_DIRECTORY",
            source="geo_routing",
            data=route,
            metadata={"engine": "geo_routing", "cached": False, "elapsed_seconds": 0.0},
        )
        _write_output(_dump_envelope(envelope, args), args)
        return STATUS_EXIT_CODES["degraded"]

    data: dict = {"honest_walk_route": route}
    claimed = getattr(args, "claimed_time", None)
    if claimed is not None:
        data["honest_overclaim"] = honest_overclaim(
            route["walk_duration_minutes"], claimed
        )

    envelope = make_envelope(
        status="ok",
        source="geo_routing",
        data=data,
        metadata={"engine": "geo_routing", "cached": False, "elapsed_seconds": 0.0},
    )
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_domclick(args) -> int:
    from .sources_domclick import parse_domclick_text
    from .pii import sanitize_contacts
    import json as _j
    text = Path(args.file).read_text(encoding="utf-8")
    cards = parse_domclick_text(text)
    data = sanitize_contacts(cards)
    envelope = make_envelope(status="ok", source="domclick", data=data,
        metadata=_privacy_metadata({"engine": "domclick", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_rush(args) -> int:
    """v0.5.13 F-15t: транспортная доступность + текущие пробки (только RU-egress)."""
    from .rush import rush_report
    import json as _j
    card = {}
    if getattr(args, "file", None):
        try:
            card = _j.loads(Path(args.file).read_text(encoding="utf-8"))
        except Exception:
            card = {}
    if isinstance(card, list):
        card = card[0] if card else {}
    res = rush_report(card if isinstance(card, dict) else {})
    lines = [f"Транспортная доступность: {res['honest_note']}"]
    w = res.get("walk") or {}
    if w.get("status") == "ok":
        lines.append(f"Метро пешком: ~{w.get('walk_minutes')} мин ({w.get('distance_m')} м) [walk]")
    else:
        lines.append(f"Метро пешком: walk — {w.get('status')}")
    tr = res.get("traffic") or {}
    if tr.get("score") is not None:
        lines.append(f"Пробки сейчас: {tr['score']} баллов, замер {tr.get('measured_at_utc')} UTC")
    else:
        lines.append(f"Пробки: unavailable ({tr.get('status')})")
    # v0.5.14 (the task brief §2): почасовой web-прогноз с той же страницы.
    # Дисклеймер «web-прогноз Яндекса, не гарантируется» обязателен всякий
    # раз, когда прогноз показан; не распарсился — пустой список, не угадываем.
    forecast = tr.get("forecast_hours") or []
    hour = getattr(args, "hour", None)
    forecast_hour = None
    if hour is not None:
        forecast_hour = next((f for f in forecast if f.get("hour") == hour), None)
        if forecast_hour:
            lines.append(f"Пробки: прогноз на {hour}: {forecast_hour['balls']} баллов "
                         f"(web-прогноз Яндекса, не гарантируется)")
        else:
            avail = ", ".join(f"{f['hour']:02d}" for f in forecast) or "нет"
            lines.append(f"Пробки: web-прогноз на {hour} ч недоступен "
                         f"(web-прогноз Яндекса, не гарантируется; доступные часы: {avail})")
    elif forecast:
        lines.append("Пробки: почасовой прогноз (web-прогноз Яндекса, не гарантируется):")
        for f in forecast:
            lines.append(f"  {f['hour']:02d}:00 — {f['balls']} баллов")
    text = "\n".join(lines)
    data = {"text": text, "result": res, "walk_minutes": w.get("walk_minutes")}
    if hour is not None:
        data["forecast_hour"] = forecast_hour
    envelope = make_envelope(status="ok", source="rush", data=data,
        metadata=_privacy_metadata({"engine": "rush", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return 0


def _cmd_deck(args) -> int:
    """v0.5.13 F-33: презентация из карточек (--file cards.json | --project P)."""
    from .deck import deck_from_cards
    import json as _j
    cards: list = []
    if getattr(args, "file", None):
        try:
            raw = _j.loads(Path(args.file).read_text(encoding="utf-8"))
            if isinstance(raw, dict) and "cards" in raw:
                cards = raw["cards"]
            elif isinstance(raw, dict):
                cards = raw.get("data", {}).get("cards") or [raw]
            elif isinstance(raw, list):
                cards = raw
        except Exception as exc:
            envelope = make_envelope(status="error", reason=f"invalid_input: {type(exc).__name__}",
                metadata=_privacy_metadata({"engine": "deck"}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 2
    elif getattr(args, "project", None):
        from .projects import project_cards
        try:
            cards = list(project_cards(args.project) or [])
        except Exception as exc:
            envelope = make_envelope(status="error", reason=f"project_unavailable: {type(exc).__name__}",
                metadata=_privacy_metadata({"engine": "deck"}, args))
            _write_output(_dump_envelope(envelope, args), args)
            return 2
    else:
        envelope = make_envelope(status="error", reason="invalid_input: нужен --file или --project",
            metadata=_privacy_metadata({"engine": "deck"}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 2
    out = getattr(args, "out", None) or "deck.pptx"
    title = getattr(args, "title", None) or "Подборка недвижимости"
    try:
        res = deck_from_cards(cards, out, title=title)
    except Exception as exc:
        envelope = make_envelope(status="error", reason=f"deck_failed: {type(exc).__name__}",
            metadata=_privacy_metadata({"engine": "deck"}, args))
        _write_output(_dump_envelope(envelope, args), args)
        return 3
    envelope = make_envelope(status="ok", source="deck", data={"result": res,
        "text": f"PPTX: {res['out']}, слайдов {res['slides']}, карточек {res['cards']} (cap 15)"},
        metadata=_privacy_metadata({"engine": "deck", "cached": False, "elapsed_seconds": 0.0}, args))
    _write_output(_dump_envelope(envelope, args), args)
    return 0


_EXAMPLES = {
    "search": 'пример: nedviga-cli search --geo-districts ЮАО --price-max 20000000 --out cards.json',
    "get-card": 'пример: nedviga-cli get-card cian-333714893 --json cards.json --purpose "прозвон" --with-contacts',
    "card": 'пример: nedviga-cli card cards.json --format all --out ./out',
    "export": 'пример: nedviga-cli export --input cards.json --output katalog.html',
    "pipeline": 'пример: nedviga-cli pipeline set cian-1 --status shortlist; pipeline list',
    "watch": 'пример: nedviga-cli watch add --file cards.json; watch check --offline fresh.json',
    "digest": 'пример: nedviga-cli digest --days 7 --format telegram',
    "compare": 'пример: nedviga-cli compare --file cards.json --format telegram',
    "bargain": 'пример: nedviga-cli bargain --file target.json --corpus corpus.json --by-complex',
    "risk": 'пример: nedviga-cli risk --file card.json',
    "triage": 'пример: nedviga-cli triage --file card.json',
    "checklist": 'пример: nedviga-cli checklist new cian-1 --file cards.json; checklist handoff cian-1 --to colleague',
    "callsheet": 'пример: nedviga-cli callsheet --file cards.json',
    "project": 'пример: nedviga-cli project new "ЮАО" --query "{}"; project refresh P1 --file new.json',
    "dedup": 'пример: nedviga-cli dedup --file cards.json',
    "tour": 'пример: nedviga-cli tour --project P1 --all --format telegram',
    "poi": 'пример: nedviga-cli poi --file card.json --radius-min 15',
    "market": 'пример: nedviga-cli market --corpus f1.json,f2.json --group-by complex',
    "stale": 'пример: nedviga-cli stale --file cards.json --project P1',
    "catalog-pdf": 'пример: nedviga-cli catalog-pdf --file cards.json --out katalog.pdf',
    "auto": 'пример: nedviga-cli auto run --file corpus.json; auto report --days 7',
    "litcheck": 'пример: nedviga-cli litcheck --address "ул. Кантемировская, 20" [--developer "ПИК"]',
    "eco": 'пример: nedviga-cli eco --file card.json',
    "mos": 'пример: nedviga-cli mos status (env NEDVIGA_EGRESS_PROXY, NEDVIGA_MOS_TOKEN_FILE)',
    "dossier": 'пример: nedviga-cli dossier sync --dataset 3293; dossier match --address "улица Азовская, дом 4"',
    "developer": 'пример: nedviga-cli developer --inn 770123456789 --litcheck',
    "noise": 'пример: nedviga-cli noise sync; noise --lat 55.72 --lon 37.61 --radius-m 1500',
    "avito": 'пример: nedviga-cli avito parse --file livetext.txt; search --source avito --catalog URL --live',
    "source": 'пример: nedviga-cli source  (лицензия, репо, как получить исходники)',
    "domclick": 'пример: nedviga-cli domclick parse --file dc_text.txt; search --source domclick --catalog URL --live',
    "rush": 'пример: nedviga-cli rush --file card.json [--hour 18]  (балл пробок и почасовой web-прогноз только с NEDVIGA_EGRESS_PROXY)',
    "deck": 'пример: nedviga-cli deck --file cards.json --out подборока.pptx [--title "ЮАО"]',
    "sources": 'пример: nedviga-cli sources list',
    "text": 'пример: nedviga-cli text index --file cards.json; text query "узакон*"',
    "feedback": 'пример: nedviga-cli feedback add cian-1 --verdict liked --reason "район"; feedback profile',
    "chain": 'пример: nedviga-cli chain new cian-1 --kind alt_unfound; chain show cian-1',
    "scorefit": 'пример: nedviga-cli scorefit --file cards.json --profile P1',
    "wizard": 'пример: nedviga-cli wizard init --profile family --out ./kit; wizard doctor',
    "ops": 'пример: nedviga-cli ops; ops --precheck --live',    "import": 'пример: nedviga-cli import --file export.html --format cian-html',
    "walk-distance": 'пример: nedviga-cli walk-distance --from "м. Царицыно" --to card.json',
    "audit": 'пример: nedviga-cli audit --days 7 --role agent',
    "pii-log": 'пример: nedviga-cli pii-log --days 30',
    "purge": 'пример: nedviga-cli purge card cian-1  (dry); purge card cian-1 --yes',
    "mcp": 'пример: nedviga-cli mcp serve  (stdio JSON-RPC, контакты закрыты принципиально)',
    "doctor": 'пример: nedviga-cli doctor; doctor --verify-signature <файл.whl>',
}


def _annotate_examples(subparsers) -> None:
    """v0.5.11 контроль: каждой подкоманде — пример в help (epilog)."""
    name_map = getattr(subparsers, "_name_parser_map", {}) or {}
    for name, parser in name_map.items():
        ex = _EXAMPLES.get(name)
        if ex and "пример:" not in ((parser.description or "") + (parser.epilog or "")):
            parser.epilog = ((parser.epilog + "\n") if parser.epilog else "") + ex


_subparsers_ref = []


def _build_parser() -> _NedvigaArgumentParser:
    parser = _NedvigaArgumentParser(
        prog="nedviga-cli",
        description="Moscow secondary real estate CLI/SDK",
    )
    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {_package_version()}",
    )
    parser.add_argument(
        "--no-spotlight",
        action="store_true",
        help="Не оборачивать внешний текстовый контент карточек в spotlight-маркеры",
    )

    sub = parser.add_subparsers(dest="command", required=True)
    # search
    search = sub.add_parser("search", help="Search listings")
    search.add_argument("--no-spotlight", action="store_true",
                        help="Не оборачивать внешний текст карточек в spotlight-маркеры")
    search.add_argument("--source", default=None)
    search.add_argument("--deal-type", default=None)
    search.add_argument("--rooms", type=int, default=None)
    search.add_argument("--price-min", type=float, default=None)
    search.add_argument("--price-max", type=float, default=None)
    search.add_argument("--kitchen-min", type=float, default=None)
    search.add_argument("--floor-not-first", action="store_true")
    search.add_argument("--min-house-floors", type=int, default=None)
    search.add_argument("--page", type=int, default=1, help="Fetch a specific result page (default 1)")
    search.add_argument("--pages", type=int, default=None, help="Fetch pages 1..N sequentially")
    search.add_argument("--metro-walk-max", type=int, default=None, help="Server-side max walking time to metro, minutes")
    search.add_argument("--hydrate", action="store_true", help="Fetch full cards for each search result")
    search.add_argument("--no-auction", action="store_true", help="Exclude auction (torgi) listings")
    search.add_argument("--only-auction", action="store_true", help="Keep only auction (torgi) listings")
    search.add_argument("--workers", type=int, default=4, help="Parallel workers for --hydrate (default 4)")
    search.add_argument("--geo-districts", default=None)
    search.add_argument("--limit", type=int, default=None)
    # v0.4.0 (ТЗ реалтора): боевые фильтры риелтора
    search.add_argument(
        "--strict-mkad", action="store_true", dest="strict_mkad",
        help="Exclude addresses outside strict MKAD (NAO/TAO/ZelAOO and near towns)",
    )
    search.add_argument(
        "--only-flat", action="store_true", dest="only_flat",
        help="Exclude apartments (апартаменты)",
    )
    search.add_argument(
        "--no-apartments", action="store_true", dest="only_flat",
        help="Alias for --only-flat",
    )
    search.add_argument(
        "--no-shares", action="store_true", dest="no_shares",
        help="Exclude flat shares and rooms (доля в квартире)",
    )
    search.add_argument(
        "--no-gas", action="store_true", dest="no_gas",
        help="Alias for --min-house-floors 14 (no gas in 14+ floor buildings)",
    )
    search.add_argument(
        "--exclude-legal-risks", action="store_true", dest="exclude_legal_risks",
        help="Exclude listings with legal-risk stop phrases in description",
    )
    # v0.5.4 (the task brief) overrides
    search.add_argument(
        "--use-overrides", action="store_true", dest="use_overrides",
        help="Apply learned profile overrides",
    )
    # v0.5.3 (the task brief) relax hints
    search.add_argument(
        "--suggest-relax", action="store_true", dest="suggest_relax",
        help="Подсказать смягчение критериев при пустой выдаче",
    )
    # v0.5.0 (the task brief) projects
    search.add_argument(
        "--project", default=None, dest="project",
        help="Автоматически добавлять результаты в проект",
    )
    # v0.4.6 (the task brief) F-13/F-03
    search.add_argument(
        "--purpose", default=None, help="Purpose for PII access",
    )
    search.add_argument(
        "--with-contacts", action="store_true", dest="with_contacts",
        help="Не маскировать телефоны в выводе (по умолчанию маскируются; "
             "в metadata ставится contacts_open: true)",
    )
    search.add_argument(
        "--profile", default=None, dest="profile",
        help="Именованный пресет поиска (parents, lnfnt); явно переданные "
             "аргументы CLI переопределяют профиль",
    )
    search.add_argument(
        "--json",
        nargs="?",
        const="-",
        default=None,
        help="Write JSON result to FILE; default stdout when flag present",
    )
    search.add_argument("--catalog", default=None, help="Avito catalog URL")
    search.add_argument("--max", type=int, default=20, help="Max results")
    search.add_argument("--live", action="store_true", help="Live browser search")
    search.add_argument("--input", default=None, help="Offline fixture file")
    search.set_defaults(func=_cmd_search)

    # get-card
    get_card = sub.add_parser("get-card", help="Fetch a single listing card")
    get_card.add_argument("--no-spotlight", action="store_true",
                          help="Не оборачивать внешний текст карточки в spotlight-маркеры")
    get_card.add_argument("target", help="URL or listing ID")
    get_card.add_argument(
        "--with-walk",
        dest="with_walk",
        action="store_true",
        help="Compute honest walk route to claimed metro and embed it in the card",
    )
    get_card.add_argument(
        "--with-contacts", action="store_true", dest="with_contacts",
        help="Не маскировать телефоны в выводе get-card",
    )
    get_card.add_argument("--purpose", default=None, help="Purpose for PII access")
    get_card.add_argument(
        "--json",
        nargs="?",
        const="-",
        default=None,
        help="Write JSON result to FILE; default stdout when flag present",
    )
    get_card.set_defaults(func=_cmd_get_card)

    # card (F-11 family decision card)
    card_cmd = sub.add_parser("card", help="Generate family decision card")
    card_cmd.add_argument("target", help="Path to JSON card file or listing id")
    card_cmd.add_argument("--format", default="html", choices=["html", "pdf", "telegram", "all"])
    card_cmd.add_argument("--out", default=None, help="Output directory")
    card_cmd.add_argument("--output", default=None, help="Output directory (alias)")
    card_cmd.add_argument("--with-contacts", action="store_true", dest="with_contacts",
                         help="Открыть контакты продавца")
    card_cmd.add_argument("--purpose", default=None, help="Purpose for PII access")
    card_cmd.add_argument(
        "--json",
        nargs="?",
        const="-",
        default=None,
        help="Write JSON result to FILE; default stdout when flag present",
    )
    card_cmd.set_defaults(func=_cmd_card)

    # export (v0.3.4)
    export_cmd = sub.add_parser("export", help="Export cards to standalone HTML catalog")
    export_cmd.add_argument("--input", required=True, help="JSON file with cards (list or {cards: [...]})")
    export_cmd.add_argument("--format", default="html", choices=["html"])
    export_cmd.add_argument("--embed-photos", dest="embed_photos", action="store_true",
                            help="Embed compressed photos as base64 (offline catalog)")
    export_cmd.add_argument("--output", default="catalog.html", help="Output HTML file path")
    # v0.4.6 (the task brief) F-13
    export_cmd.add_argument(
        "--with-contacts", action="store_true", dest="with_contacts",
        help="Не маскировать телефоны в HTML-каталоге (по умолчанию маскируются; "
             "в metadata ставится contacts_open: true)",
    )
    export_cmd.add_argument("--purpose", default=None, help="Purpose for PII access")
    export_cmd.add_argument(
        "--json",
        nargs="?",
        const="-",
        default=None,
        help="Write JSON result to FILE; default stdout when flag present",
    )
    export_cmd.set_defaults(func=_cmd_export)

    # import
    import_cmd = sub.add_parser("import", help="Parse a saved HTML file offline")
    import_cmd.add_argument("--no-spotlight", action="store_true",
                            help="Не оборачивать внешний текст карточек в spotlight-маркеры")
    import_cmd.add_argument("path", help="Path to saved HTML file")
    import_cmd.add_argument(
        "--with-walk",
        dest="with_walk",
        action="store_true",
        help="Compute honest walk route to claimed metro and embed it in the card",
    )
    import_cmd.add_argument(
        "--json",
        nargs="?",
        const="-",
        default=None,
        help="Write JSON result to FILE; default stdout when flag present",
    )
    import_cmd.set_defaults(func=_cmd_import)

    # walk-distance
    walk = sub.add_parser("walk-distance", help="Honest walking distance to metro")
    walk.add_argument("--lat", type=float, required=True)
    walk.add_argument("--lon", type=float, required=True)
    walk.add_argument("--metro", required=True)
    walk.add_argument(
        "--claimed-time",
        type=int,
        default=None,
        help="Platform-claimed walking time in minutes (optional)",
    )
    walk.add_argument(
        "--json",
        nargs="?",
        const="-",
        default=None,
        help="Write JSON result to FILE; default stdout when flag present",
    )
    walk.set_defaults(func=_cmd_walk_distance)

    # pipeline (F-04)
    pipeline = sub.add_parser("pipeline", help="Object funnel pipeline")
    psub = pipeline.add_subparsers(dest="pipeline_action", required=True)
    pset = psub.add_parser("set", help="Set pipeline status")
    pset.add_argument("card_id", help="Card id")
    pset.add_argument("--status", required=True, help="New status")
    pset.add_argument("--note", default=None, help="Note")
    pset.add_argument("--from-file", dest="from_file", default=None, help="JSON file with cards")
    pset.set_defaults(func=_cmd_pipeline)
    plist = psub.add_parser("list", help="List pipeline items")
    plist.add_argument("--status", default=None, help="Filter by status")
    plist.set_defaults(func=_cmd_pipeline)
    pshow = psub.add_parser("show", help="Show pipeline history")
    pshow.add_argument("card_id", help="Card id")
    pshow.set_defaults(func=_cmd_pipeline)
    pipeline.set_defaults(func=_cmd_pipeline)

    # watch (F-08)
    watch = sub.add_parser("watch", help="Monitor listings")
    wsub = watch.add_subparsers(dest="watch_action", required=True)
    wadd = wsub.add_parser("add", help="Add snapshot")
    wadd.add_argument("card_id", nargs="?", default=None, help="Card id")
    wadd.add_argument("--file", default=None, help="JSON file with cards")
    wadd.add_argument("--price", type=float, default=None, help="Price snapshot")
    wadd.set_defaults(func=_cmd_watch)
    wlist = wsub.add_parser("list", help="List snapshots")
    wlist.set_defaults(func=_cmd_watch)
    wrm = wsub.add_parser("rm", help="Remove snapshot")
    wrm.add_argument("card_id", help="Card id")
    wrm.set_defaults(func=_cmd_watch)
    wcheck = wsub.add_parser("check", help="Check for changes")
    wcheck.add_argument("--offline", default=None, help="Offline fresh export file")
    wcheck.set_defaults(func=_cmd_watch)
    watch.set_defaults(func=_cmd_watch)

    # digest (F-14b)
    digest = sub.add_parser("digest", help="Family digest")
    digest.add_argument("--days", type=int, default=7, help="Period days")
    digest.add_argument("--format", default="telegram", choices=["telegram", "md"])
    digest.add_argument("--out", default=None, help="Output file")
    digest.add_argument("--output", default=None, help="Output file (alias)")
    digest.set_defaults(func=_cmd_digest)

    # compare (F-12)
    compare = sub.add_parser("compare", help="Compare listings")
    compare.add_argument("--file", required=True, help="JSON file with cards")
    compare.add_argument("--ids", default=None, help="Comma-separated ids")
    compare.add_argument("--format", default="md", choices=["md", "telegram", "html"])
    compare.add_argument("--by-fit", action="store_true", dest="by_fit", help="Sort by fit score")
    compare.add_argument("--out", default=None, help="Output file")
    compare.add_argument("--output", default=None, help="Output file (alias)")
    compare.set_defaults(func=_cmd_compare)

    # bargain (F-10b)
    bargain = sub.add_parser("bargain", help="Bargain analysis")
    bargain.add_argument("--file", required=True, help="Target card JSON")
    bargain.add_argument("--corpus", required=True, help="Corpus JSON file(s), comma-separated")
    bargain.add_argument("--district", default=None, help="District override")
    bargain.add_argument("--rooms", type=int, default=None, help="Rooms override")
    bargain.add_argument("--by-complex", action="store_true", dest="by_complex", help="Group by complex")
    bargain.add_argument("--out", default=None, help="Output file")
    bargain.add_argument("--output", default=None, help="Output file (alias)")
    bargain.set_defaults(func=_cmd_bargain)

    # risk (F-07b/F-19)
    risk = sub.add_parser("risk", help="Risk scoring")
    risk.add_argument("--file", required=True, help="Card JSON")
    risk.add_argument("--corpus", default=None, help="Corpus JSON for price signals")
    risk.add_argument("--district", default=None, help="District override")
    risk.add_argument("--rooms", type=int, default=None, help="Rooms override")
    risk.add_argument("--out", default=None, help="Output file")
    risk.add_argument("--output", default=None, help="Output file (alias)")
    risk.set_defaults(func=_cmd_risk)

    # triage (F-06b)
    triage = sub.add_parser("triage", help="Legal red flags triage")
    triage.add_argument("--file", required=True, help="Card JSON")
    triage.add_argument("--out", default=None, help="Output file")
    triage.add_argument("--output", default=None, help="Output file (alias)")
    triage.set_defaults(func=_cmd_triage)

    # checklist (F-22)
    checklist = sub.add_parser("checklist", help="Legal checklist")
    csub = checklist.add_subparsers(dest="checklist_action", required=True)
    cnew = csub.add_parser("new", help="New checklist")
    cnew.add_argument("card_id", help="Card id")
    cnew.add_argument("--file", required=True, help="Cards JSON")
    cnew.add_argument("--out", default=None, help="Output file")
    cnew.add_argument("--output", default=None, help="Output file (alias)")
    cnew.set_defaults(func=_cmd_checklist)
    chand = csub.add_parser("handoff", help="Handoff to colleague")
    chand.add_argument("card_id", help="Card id")
    chand.add_argument("--to", default="colleague", help="Recipient")
    chand.add_argument("--file", default=None, help="Cards JSON")
    chand.set_defaults(func=_cmd_checklist)
    checklist.set_defaults(func=_cmd_checklist)

    # callsheet (F-09c)
    callsheet = sub.add_parser("callsheet", help="Call sheet")
    callsheet.add_argument("--file", required=True, help="Cards JSON")
    callsheet.add_argument("--out", default=None, help="Output file")
    callsheet.add_argument("--output", default=None, help="Output file (alias)")
    callsheet.add_argument("--with-contacts", action="store_true", dest="with_contacts")
    callsheet.add_argument("--purpose", default=None, help="Purpose for PII access")
    callsheet.set_defaults(func=_cmd_callsheet)

    # project (F-06)
    project = sub.add_parser("project", help="Projects")
    psub = project.add_subparsers(dest="project_action", required=True)
    pnew = psub.add_parser("new", help="New project")
    pnew.add_argument("name", help="Project name")
    pnew.add_argument("--query", default=None, help="Query JSON")
    pnew.set_defaults(func=_cmd_project)
    plist = psub.add_parser("list", help="List projects")
    plist.set_defaults(func=_cmd_project)
    padd = psub.add_parser("add", help="Add card to project")
    padd.add_argument("project", help="Project id")
    padd.add_argument("card_id", help="Card id")
    padd.set_defaults(func=_cmd_project)
    popen = psub.add_parser("open", help="Open project")
    popen.add_argument("project", help="Project id")
    popen.add_argument("--out", default=None, help="Output file")
    popen.add_argument("--output", default=None, help="Output file (alias)")
    popen.set_defaults(func=_cmd_project)
    prefresh = psub.add_parser("refresh", help="Refresh project")
    prefresh.add_argument("project", help="Project id")
    prefresh.add_argument("--file", required=True, help="New search JSON")
    prefresh.set_defaults(func=_cmd_project)
    project.set_defaults(func=_cmd_project)

    # poi (F-14)
    poi = sub.add_parser("poi", help="POI accessibility")
    poi.add_argument("--file", required=True, help="Card JSON")
    poi.add_argument("--radius-min", type=int, default=15, dest="radius_min")
    poi.add_argument("--offline", default=None, help="Offline Overpass fixture")
    poi.add_argument("--out", default=None, help="Output file")
    poi.add_argument("--output", default=None, help="Output file (alias)")
    poi.set_defaults(func=_cmd_poi)

    # tour (F-09)
    tour = sub.add_parser("tour", help="Tour routing")
    tour.add_argument("--project", default=None, help="Project id")
    tour.add_argument("--file", default=None, help="Cards JSON")
    tour.add_argument("--date", default=None, help="Date")
    tour.add_argument("--slot-min", type=int, default=45, dest="slot_min")
    tour.add_argument("--start", default="10:00", help="Start time")
    tour.add_argument("--all", action="store_true", dest="all", help="Include all statuses")
    tour.add_argument("--format", default="telegram", choices=["telegram", "md"])
    tour.add_argument("--out", default=None, help="Output file")
    tour.add_argument("--output", default=None, help="Output file (alias)")
    tour.set_defaults(func=_cmd_tour)

    # sources (F-53)
    sources = sub.add_parser("sources", help="Source adapters")
    ssub = sources.add_subparsers(dest="sources_action", required=False)
    slist = ssub.add_parser("list", help="List sources")
    slist.set_defaults(func=_cmd_sources)
    sources.set_defaults(func=_cmd_sources, sources_action="list")

    # dedup (F-02)
    dedup = sub.add_parser("dedup", help="Deduplicate listings")
    dedup.add_argument("--file", required=True, help="Cards JSON")
    dedup.add_argument("--strict", action="store_true", help="Require >=2 signals")
    dedup.add_argument("--out", default=None, help="Output file")
    dedup.add_argument("--output", default=None, help="Output file (alias)")
    dedup.set_defaults(func=_cmd_dedup)

    # market (F-11)
    market = sub.add_parser("market", help="Market analytics")
    market.add_argument("--corpus", required=True, help="Corpus JSON file(s), comma-separated")
    market.add_argument("--district", default=None, help="District filter")
    market.add_argument("--okrug", default=None, help="Okrug filter")
    market.add_argument("--group-by", default="district", choices=["district", "complex"], dest="group_by")
    market.add_argument("--days", type=int, default=30, help="Period days")
    market.add_argument("--format", default="telegram", choices=["telegram", "md"])
    market.add_argument("--out", default=None, help="Output file")
    market.add_argument("--output", default=None, help="Output file (alias)")
    market.set_defaults(func=_cmd_market)

    # stale (F-58)
    stale = sub.add_parser("stale", help="Stale detection")
    stale.add_argument("--file", default=None, help="Cards JSON")
    stale.add_argument("--project", default=None, help="Project id")
    stale.add_argument("--max-age-days", type=int, default=14, dest="max_age_days")
    stale.add_argument("--verify-live", action="store_true", dest="verify_live")
    stale.add_argument("--out", default=None, help="Output file")
    stale.add_argument("--output", default=None, help="Output file (alias)")
    stale.set_defaults(func=_cmd_stale)

    # catalog-pdf (F-31)
    catalog_pdf = sub.add_parser("catalog-pdf", help="Catalog PDF")
    catalog_pdf.add_argument("--file", default=None, help="Cards JSON")
    catalog_pdf.add_argument("--project", default=None, help="Project id")
    catalog_pdf.add_argument("--out", default="katalog.pdf", help="Output PDF")
    catalog_pdf.add_argument("--output", default=None, help="Output PDF (alias)")
    catalog_pdf.add_argument("--title", default=None, help="Title")
    catalog_pdf.set_defaults(func=_cmd_catalog_pdf)

    # feedback (F-21)
    feedback = sub.add_parser("feedback", help="Feedback tracker")
    fsub = feedback.add_subparsers(dest="feedback_action", required=True)
    fadd = fsub.add_parser("add", help="Add feedback")
    fadd.add_argument("card_id", help="Card id")
    fadd.add_argument("--verdict", required=True, choices=["liked", "rejected", "maybe"])
    fadd.add_argument("--reason", default=None, help="Reason")
    fadd.add_argument("--note", default=None, help="Note")
    fadd.add_argument("--dry", action="store_true", help="Dry run")
    fadd.set_defaults(func=_cmd_feedback)
    flist = fsub.add_parser("list", help="List feedback")
    flist.add_argument("--card", default=None, help="Card id filter")
    flist.set_defaults(func=_cmd_feedback)
    fprof = fsub.add_parser("profile", help="Feedback profile")
    fprof.set_defaults(func=_cmd_feedback)
    fapply = fsub.add_parser("apply", help="Apply overrides")
    fapply.add_argument("--dry", action="store_true", help="Dry run")
    fapply.add_argument("--yes", action="store_true", help="Apply")
    fapply.set_defaults(func=_cmd_feedback)
    feedback.set_defaults(func=_cmd_feedback)

    # scorefit (F-G3)
    scorefit = sub.add_parser("scorefit", help="Score fit")
    scorefit.add_argument("--file", required=True, help="Cards JSON")
    scorefit.add_argument("--profile", default=None, help="Profile JSON or name")
    scorefit.add_argument("--out", default=None, help="Output file")
    scorefit.add_argument("--output", default=None, help="Output file (alias)")
    scorefit.set_defaults(func=_cmd_scorefit)

    # chain (F-J2)
    chain = sub.add_parser("chain", help="Deal chains")
    csub = chain.add_subparsers(dest="chain_action", required=True)
    cnew = csub.add_parser("new", help="New chain")
    cnew.add_argument("card_id", help="Card id")
    cnew.add_argument("--kind", default="direct", choices=["direct", "alt_found", "alt_unfound", "guardian_needed"])
    cnew.set_defaults(func=_cmd_chain)
    clink = csub.add_parser("link", help="Link cards")
    clink.add_argument("a", help="Card a")
    clink.add_argument("b", help="Card b")
    clink.add_argument("--rel", default="depends_on", choices=["depends_on", "blocks"])
    clink.set_defaults(func=_cmd_chain)
    cshow = csub.add_parser("show", help="Show chain")
    cshow.add_argument("card_id", help="Card id")
    cshow.set_defaults(func=_cmd_chain)
    chain.set_defaults(func=_cmd_chain)

    # text (F-05)
    text = sub.add_parser("text", help="Full-text search")
    tsub = text.add_subparsers(dest="text_action", required=True)
    tindex = tsub.add_parser("index", help="Index file")
    tindex.add_argument("--file", required=True, help="Cards JSON")
    tindex.add_argument("--project", default=None, help="Project id")
    tindex.set_defaults(func=_cmd_text)
    tquery = tsub.add_parser("query", help="Query")
    tquery.add_argument("query", help="FTS query")
    tquery.add_argument("--project", default=None, help="Project id")
    tquery.set_defaults(func=_cmd_text)
    text.set_defaults(func=_cmd_text)

    # audit (F-45)
    audit = sub.add_parser("audit", help="Audit log")
    audit.add_argument("--days", type=int, default=30)
    audit.add_argument("--role", default=None)
    audit.add_argument("--card", default=None)
    audit.set_defaults(func=_cmd_audit)

    # pii-log (F-38)
    pii_log = sub.add_parser("pii-log", help="PII access log")
    pii_log.add_argument("--days", type=int, default=30)
    pii_log.set_defaults(func=_cmd_pii_log)

    # purge (F-43)
    purge = sub.add_parser("purge", help="Purge data")
    psub = purge.add_subparsers(dest="purge_action", required=True)
    pcard = psub.add_parser("card", help="Purge card")
    pcard.add_argument("card_id", help="Card id")
    pcard.add_argument("--yes", action="store_true", help="Execute")
    pcard.set_defaults(func=_cmd_purge)
    pprof = psub.add_parser("profile", help="Purge profile")
    pprof.add_argument("name", help="Profile name")
    pprof.add_argument("--yes", action="store_true", help="Execute")
    pprof.set_defaults(func=_cmd_purge)
    purge.set_defaults(func=_cmd_purge)

    # auto (F-20)
    auto = sub.add_parser("auto", help="Auto selection")
    asub = auto.add_subparsers(dest="auto_action", required=True)
    arun = asub.add_parser("run", help="Run auto selection")
    arun.add_argument("--profile", default=None, help="Profile JSON or name")
    arun.add_argument("--file", default=None, help="Corpus JSON")
    arun.add_argument("--project", default=None, help="Project id")
    arun.add_argument("--live", action="store_true", help="Live search")
    arun.add_argument("--out", default=None, help="Output file")
    arun.add_argument("--output", default=None, help="Output file (alias)")
    arun.set_defaults(func=_cmd_auto)
    areport = asub.add_parser("report", help="Auto report")
    areport.add_argument("--days", type=int, default=7)
    areport.add_argument("--out", default=None, help="Output file")
    areport.add_argument("--output", default=None, help="Output file (alias)")
    areport.set_defaults(func=_cmd_auto)
    auto.set_defaults(func=_cmd_auto)

    # litcheck (F-22b)
    litcheck = sub.add_parser("litcheck", help="Litigation pre-check")
    litcheck.add_argument("--card", default=None, help="Card id")
    litcheck.add_argument("--file", default=None, help="Cards JSON")
    litcheck.add_argument("--address", default=None, help="Address")
    litcheck.add_argument("--developer", default=None, help="Developer")
    litcheck.add_argument("--since", type=int, default=2020, help="Since year")
    litcheck.add_argument("--out", default=None, help="Output file")
    litcheck.add_argument("--output", default=None, help="Output file (alias)")
    litcheck.set_defaults(func=_cmd_litcheck)

    # eco (F-16)
    eco = sub.add_parser("eco", help="Eco proxy")
    eco.add_argument("--file", required=True, help="Card JSON")
    eco.add_argument("--offline", default=None, help="Offline Overpass fixture")
    eco.add_argument("--out", default=None, help="Output file")
    eco.add_argument("--output", default=None, help="Output file (alias)")
    eco.set_defaults(func=_cmd_eco)

    # ops (F-44/46)
    ops = sub.add_parser("ops", help="Operator panel")
    ops.add_argument("--days", type=int, default=1)
    ops.add_argument("--format", default="telegram", choices=["telegram", "json"])
    ops.add_argument("--precheck", action="store_true")
    ops.add_argument("--live", action="store_true")
    ops.add_argument("--json", nargs="?", const="-", default=None)
    ops.add_argument("--out", default=None)
    ops.add_argument("--output", default=None)
    ops.set_defaults(func=_cmd_ops)

    # mcp (F-23)
    mcp = sub.add_parser("mcp", help="MCP server")
    msub = mcp.add_subparsers(dest="mcp_action", required=False)
    mserve = msub.add_parser("serve", help="Serve stdio")
    mserve.set_defaults(func=_cmd_mcp)
    mcp.set_defaults(func=_cmd_mcp, mcp_action="serve")

    # mos (F-04b)
    mos = sub.add_parser("mos", help="Mosdata client")
    msub = mos.add_subparsers(dest="mos_action", required=False)
    ms = msub.add_parser("search-datasets", help="Search datasets")
    ms.add_argument("--query", required=True)
    ms.set_defaults(func=_cmd_mos, mos_action="search-datasets")
    mv = msub.add_parser("dataset-versions", help="Dataset versions")
    mv.add_argument("dataset_id")
    mv.set_defaults(func=_cmd_mos, mos_action="dataset-versions")
    mr = msub.add_parser("rows", help="Rows")
    mr.add_argument("dataset_id")
    mr.add_argument("--version", default=None)
    mr.add_argument("--top", type=int, default=1000)
    mr.add_argument("--skip", type=int, default=0)
    mr.set_defaults(func=_cmd_mos, mos_action="rows")
    mst = msub.add_parser("status", help="Status")
    mst.set_defaults(func=_cmd_mos, mos_action="status")
    mos.set_defaults(func=_cmd_mos, mos_action="status")

    # dossier (F-04b)
    dossier = sub.add_parser("dossier", help="Building dossier")
    dsub = dossier.add_subparsers(dest="dossier_action", required=True)
    dsync = dsub.add_parser("sync", help="Sync registry")
    dsync.add_argument("--limit", type=int, default=1000)
    dsync.add_argument("--dataset", default="auto")
    dsync.set_defaults(func=_cmd_dossier)
    dmatch = dsub.add_parser("match", help="Match card")
    dmatch.add_argument("--file", default=None, help="Card JSON")
    dmatch.add_argument("--address", default=None, help="Address")
    dmatch.set_defaults(func=_cmd_dossier)
    dossier.set_defaults(func=_cmd_dossier)

    # developer (F-17)
    developer = sub.add_parser("developer", help="Developer dossier")
    developer.add_argument("--name", default=None, help="Developer name")
    developer.add_argument("--inn", default=None, help="INN")
    developer.add_argument("--from-file", dest="from_file", default=None, help="Card JSON")
    developer.add_argument("--litcheck", action="store_true", help="Run litigation pre-check")
    developer.add_argument("--out", default=None, help="Output file")
    developer.add_argument("--output", default=None, help="Output file (alias)")
    developer.set_defaults(func=_cmd_developer)

    # noise (F-16)
    noise = sub.add_parser("noise", help="Noise monitoring")
    nsub = noise.add_subparsers(dest="noise_action", required=False)
    nsync = nsub.add_parser("sync", help="Sync noise data")
    nsync.add_argument("--limit", type=int, default=1000)
    nsync.set_defaults(func=_cmd_noise, noise_action="sync")
    noise.add_argument("--file", default=None, help="Card JSON")
    noise.add_argument("--lat", type=float, default=None)
    noise.add_argument("--lon", type=float, default=None)
    noise.add_argument("--radius-m", type=int, default=1500, dest="radius_m")
    noise.add_argument("--out", default=None, help="Output file")
    noise.add_argument("--output", default=None, help="Output file (alias)")
    noise.set_defaults(func=_cmd_noise)

    domclick = sub.add_parser("domclick", help="Domclick listings")
    dcsub = domclick.add_subparsers(dest="domclick_action", required=False)
    dcp = dcsub.add_parser("parse", help="Parse saved Domclick innerText")
    dcp.add_argument("--file", required=True)
    dcp.set_defaults(func=_cmd_domclick)

    source = sub.add_parser("source", help="AGPL §13: license + source repository info")
    source.set_defaults(func=_cmd_source)

    rush = sub.add_parser("rush", help="Transport accessibility + current traffic")
    rush.add_argument("--file", default=None, help="Card JSON")
    rush.add_argument("--hour", type=int, default=None,
                      help="Почасовой web-прогноз: час 0-23 (только с NEDVIGA_EGRESS_PROXY)")
    rush.set_defaults(func=_cmd_rush)

    deck = sub.add_parser("deck", help="PPTX deck from cards")
    deck.add_argument("--file", default=None)
    deck.add_argument("--project", default=None)
    deck.add_argument("--out", default=None)
    deck.add_argument("--title", default=None)
    deck.set_defaults(func=_cmd_deck)

    # wizard (F-61)
    wizard = sub.add_parser("wizard", help="First-run wizard")
    wsub = wizard.add_subparsers(dest="wizard_action", required=True)
    winit = wsub.add_parser("init", help="Initialize (example: wizard init --profile agent --out ./out)")
    winit.add_argument("--profile", default="agent", choices=["agent", "family"])
    winit.add_argument("--out", default=None)
    winit.add_argument("--output", default=None)
    winit.set_defaults(func=_cmd_wizard)
    wdoc = wsub.add_parser("doctor", help="Diagnostics (example: wizard doctor --json)")
    wdoc.add_argument("--json", nargs="?", const="-", default=None)
    wdoc.add_argument("--out", default=None)
    wdoc.add_argument("--output", default=None)
    wdoc.set_defaults(func=_cmd_wizard)
    wizard.set_defaults(func=_cmd_wizard)

    # avito (F-15)
    avito = sub.add_parser("avito", help="Avito adapter")
    asub = avito.add_subparsers(dest="avito_action", required=True)
    aparse = asub.add_parser("parse", help="Parse livetext")
    aparse.add_argument("--file", required=True, help="Livetext file")
    aparse.add_argument("--out", default=None, help="Output file")
    aparse.add_argument("--output", default=None, help="Output file (alias)")
    aparse.set_defaults(func=_cmd_avito)
    avito.set_defaults(func=_cmd_avito)

    # doctor
    doctor = sub.add_parser("doctor", help="System diagnostics")
    doctor.add_argument("--verify-signature", default=None, dest="verify_signature")
    doctor.add_argument(
        "--json",
        nargs="?",
        const="-",
        default=None,
        help="Write JSON result to FILE; default stdout when flag present",
    )
    doctor.set_defaults(func=_cmd_doctor)

    _annotate_examples(sub)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    from .roles import current_role, validate_role, check_permission, role_allows_contacts

    role = current_role()
    args.role = role

    ok, reason = validate_role()
    if not ok:
        envelope = make_envelope(
            status="error", reason=reason or "unknown_role",
            data={"role": role},
            metadata={"engine": "roles", "cached": False, "elapsed_seconds": 0.0, "role": role},
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 3

    allowed, reason = check_permission(args)
    if not allowed:
        envelope = make_envelope(
            status="error", reason=reason or "role_forbidden",
            data={"role": role, "command": getattr(args, "command", None)},
            metadata={"engine": "roles", "cached": False, "elapsed_seconds": 0.0, "role": role},
        )
        _write_output(_dump_envelope(envelope, args), args)
        return 3

    # purpose required for --with-contacts (agent only)
    if getattr(args, "with_contacts", False) and role == "agent":
        if not getattr(args, "purpose", None):
            envelope = make_envelope(
                status="error", reason="pii_purpose_required",
                data={"message": "--purpose is required with --with-contacts"},
                metadata={"engine": "roles", "cached": False, "elapsed_seconds": 0.0, "role": role},
            )
            _write_output(_dump_envelope(envelope, args), args)
            return 3

    # role-aware contacts: non-agent cannot open contacts
    if getattr(args, "with_contacts", False) and not role_allows_contacts(role):
        args.with_contacts = False
        args._contacts_requested = True

    rc = args.func(args)

    # audit log (write commands + with-contacts), no recursion for audit/pii-log
    try:
        from .roles import is_write
        from .auditlog import log_action
        cmd = getattr(args, "command", None)
        should_log = is_write(args) or bool(getattr(args, "with_contacts", False))
        if should_log and cmd not in {"audit", "pii-log"}:
            card_id = (getattr(args, "card_id", None) or getattr(args, "target", None)
                       or getattr(args, "a", None))
            log_action(
                role=role,
                command=cmd,
                card_id=card_id,
                rc=rc,
                reason=None,
                argv=[str(x) for x in (argv or [])],
                pii=bool(getattr(args, "with_contacts", False)),
                purpose=getattr(args, "purpose", None),
            )
    except Exception:
        pass

    return rc


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
