"""Regression tests for the nedviga-cli JSON contract and pydantic schemas."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

import nedviga
import pytest
from pydantic import ValidationError

from nedviga.doctor import run_doctor
from nedviga.models import ApiOutcomeEnvelope, ListingCard
from nedviga.outcomes import make_envelope


ROOT = Path(__file__).resolve().parent.parent


def run_cli(args: list[str]) -> subprocess.CompletedProcess[str]:
    """Run the CLI in a subprocess with PYTHONPATH set to the project root."""
    env = {**os.environ, "PYTHONPATH": str(ROOT)}
    return subprocess.run(
        [sys.executable, "-m", "nedviga", *args],
        cwd=ROOT,
        capture_output=True,
        text=True,
        env=env,
    )


def parse_stdout_json(proc: subprocess.CompletedProcess[str]) -> dict:
    """Assert that stdout is exactly one JSON object and parse it."""
    assert proc.returncode is not None
    assert proc.stdout.strip(), "stdout is empty"
    lines = [line for line in proc.stdout.strip().splitlines() if line.strip()]
    assert len(lines) >= 1
    # The contract allows pretty-printed multi-line JSON; take the first {.
    first_brace = proc.stdout.index("{")
    last_brace = proc.stdout.rindex("}")
    return json.loads(proc.stdout[first_brace : last_brace + 1])


class TestCliVersion:
    def test_version_metadata_matches(self):
        match = re.search(r'(?m)^version = "([^"]+)"', (ROOT / "pyproject.toml").read_text())
        assert match is not None
        assert nedviga.__version__ == match.group(1)

    def test_cli_version_flag_matches_package(self):
        proc = run_cli(["--version"])
        assert proc.returncode == 0
        assert proc.stdout.strip() == f"nedviga-cli {nedviga.__version__}"


class TestCliContract:
    def test_import_missing_file_returns_error(self):
        proc = run_cli(["import", "fixtures/dummy.html", "--json"])
        payload = parse_stdout_json(proc)
        assert proc.returncode == 3
        assert payload["status"] == "error"
        assert payload["reason"] == "file_not_found"

    def test_walk_distance_unknown_station_returns_degraded(self):
        proc = run_cli(
            [
                "walk-distance",
                "--lat",
                "55.6385",
                "--lon",
                "37.6025",
                "--metro",
                "НесуществующаяСтанция",
                "--json",
            ]
        )
        payload = parse_stdout_json(proc)
        assert proc.returncode == 2
        assert payload["status"] == "degraded"
        assert payload["reason"] == "STATION_NOT_IN_DIRECTORY"

    def test_doctor_returns_json_and_exit_zero(self):
        proc = run_cli(["doctor", "--json"])
        payload = parse_stdout_json(proc)
        assert proc.returncode == 0, f"stderr: {proc.stderr}"
        assert payload["status"] == "ok"
        assert payload["ok"] is True
        assert payload["source"] == "doctor"
        data = payload["data"]
        assert data["python_ok"] is True
        assert data["dependencies_ok"] is True
        assert data["cache_ok"] is True
        assert data["browser"]["status"] == "available"
        assert data["browser"]["available"] is True

    def test_usage_error_returns_exit_code_four(self):
        proc = run_cli(["nonexistent-command"])
        payload = parse_stdout_json(proc)
        assert proc.returncode == 4
        assert payload["status"] == "error"
        assert payload["reason"] == "usage_error"


class TestPydanticSchemas:
    def test_api_outcome_envelope_ok(self):
        env = make_envelope(
            status="ok",
            source="cian",
            data={"foo": "bar"},
            metadata={"engine": "skel"},
        )
        assert env.ok is True
        assert env.status == "ok"
        dumped = env.model_dump(mode="json")
        assert dumped["ok"] is True
        assert dumped["status"] == "ok"

    def test_api_outcome_envelope_invalid_status_raises(self):
        with pytest.raises(ValidationError):
            ApiOutcomeEnvelope(
                ok=True,
                status="invalid_status",  # type: ignore[arg-type]
            )

    def test_listing_card_minimal(self):
        card = ListingCard(id="cian-1", source="cian", url="https://cian.ru/1/")
        assert card.id == "cian-1"
        assert card.pricing.price_total_rub is None
        dumped = card.model_dump(mode="json")
        assert dumped["id"] == "cian-1"

    def test_listing_card_full(self):
        card = ListingCard(
            id="cian-310123456",
            source="cian",
            url="https://www.cian.ru/sale/flat/310123456/",
            status="active",
            title="2-комн. квартира, 54,2 м², 6/12 этаж",
            pricing={
                "price_total_rub": 16_900_000,
                "price_per_m2_rub": 311_808.12,
                "price_history": [
                    {"date": "2026-08-15", "price": 17_500_000},
                    {"date": "2026-09-02", "price": 16_900_000},
                ],
            },
            parameters={
                "rooms": 2,
                "rooms_type": "isolated",
                "area_total_m2": 54.2,
                "area_living_m2": 32.0,
                "area_kitchen_m2": 8.5,
                "floor": 6,
                "floors_total": 12,
                "ceiling_height_m": 2.64,
                "balcony": "1 лоджия",
                "bathroom": "раздельный",
                "renovation": "cosmetic",
                "window_view": "yard",
            },
            building={
                "address_raw": "Москва, ЮАО, р-н Чертаново Северное, Сумской проезд, 6к2",
                "house_series": "II-49",
                "year_built": 1971,
                "building_type": "panel",
                "floor_material": "reinforced_concrete",
                "renovation_program": False,
                "elevators_passenger": 1,
                "elevators_cargo": 0,
                "gas": True,
            },
            geo={
                "lat": 55.638512,
                "lon": 37.602534,
                "district": "ЮАО",
                "area_name": "Чертаново Северное",
                "cian_claimed_metro": {
                    "station": "Чертановская",
                    "claimed_time_minutes": 10,
                    "transport_type": "walk",
                },
                "honest_walk_route": {
                    "target_station": "Чертановская",
                    "target_vestibule": "Вестибюль 1 (южный)",
                    "walk_distance_meters": 1150,
                    "walk_duration_minutes": 14,
                    "routing_provider": "local_osrm_foot",
                    "route_verified": True,
                },
            },
            description_text="Светлая уютная квартира с изолированными комнатами...",
            seller={
                "seller_type": "realtor",
                "name": "Инком-Недвижимость",
                "agent_phone_masked": "+7 999 ***-**-**",
            },
            images=[
                {"url": "https://example.com/plan.jpg", "category": "plan"},
                {"url": "https://example.com/interior.jpg", "category": "interior"},
            ],
        )
        dumped = card.model_dump(mode="json")
        assert dumped["geo"]["honest_walk_route"]["walk_distance_meters"] == 1150
        assert dumped["pricing"]["price_per_m2_rub"] == 311808.12

    def test_doctor_run_returns_ok(self):
        envelope, code = run_doctor()
        assert code == 0
        assert envelope.status == "ok"
        assert envelope.data["browser"]["status"] == "available"
        assert envelope.data["browser"]["available"] is True
        assert envelope.data["cache_ok"] is True
