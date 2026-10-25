"""Offline tests for the honest geo-routing module (M2).

All OSRM calls are mocked; no real network traffic is performed.
"""

from __future__ import annotations

import json
import math
from unittest.mock import patch

import pytest
import requests

from nedviga.cli import main
from nedviga.geo_routing import (
    URBAN_HAVERSINE_FACTOR,
    WALK_SPEED_M_PER_MIN,
    _duration_minutes,
    _haversine,
    honest_overclaim,
    walk_route,
)


class TestHaversine:
    """Sanity checks for the great-circle fallback."""

    def test_haversine_known_distance(self):
        # One degree of latitude is roughly 111 km.
        distance = _haversine(55.0, 37.0, 56.0, 37.0)
        assert 110_000 < distance < 112_000

    def test_haversine_is_symmetric(self):
        a = _haversine(55.6405, 37.6067, 55.7753, 37.6555)
        b = _haversine(55.7753, 37.6555, 55.6405, 37.6067)
        assert math.isclose(a, b, rel_tol=1e-9)


class TestWalkingSpeed:
    """4.8 km/h == 80 m/min, duration rounded up."""

    def test_duration_at_80_m_per_min(self):
        assert _duration_minutes(80.0) == 1
        assert _duration_minutes(160.0) == 2
        assert _duration_minutes(400.0) == 5

    def test_duration_rounds_up(self):
        # 81 m must take 2 minutes at the fixed speed.
        assert _duration_minutes(81.0) == 2

    def test_four_point_eight_kmh(self):
        # 4.8 km/h = 4800 m / 60 min = 80 m/min.
        assert 4800 / 60 == WALK_SPEED_M_PER_MIN


class TestOverclaimVerdict:
    def test_overclaim_flag_true_when_more_than_three_minutes(self):
        assert honest_overclaim(14, 10) == {"overclaim_minutes": 4, "flag": True}

    def test_overclaim_flag_false_at_exactly_three_minutes(self):
        assert honest_overclaim(13, 10) == {"overclaim_minutes": 3, "flag": False}

    def test_overclaim_flag_false_when_within_two_minutes(self):
        assert honest_overclaim(11, 10) == {"overclaim_minutes": 1, "flag": False}

    def test_overclaim_zero_when_honest_not_larger(self):
        assert honest_overclaim(9, 10) == {"overclaim_minutes": 0, "flag": False}


class TestStationDirectory:
    def test_unknown_station_returns_degraded_reason(self):
        result = walk_route(55.0, 37.0, "Станция-НЛО")
        assert result["status"] == "degraded"
        assert result["reason"] == "STATION_NOT_IN_DIRECTORY"
        assert result["route_verified"] is False
        assert result["walk_distance_meters"] is None

    def test_known_station_is_ok(self):
        with patch("nedviga.graph.load_graph", side_effect=Exception("no graph in test")), \
            patch("nedviga.metro_vestibules._load_generated", return_value=None), \
             patch("nedviga.net_guard.guarded_get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "code": "Ok",
                "routes": [{"distance": 1000.0}],
            }
            mock_get.return_value.raise_for_status = lambda: None

            result = walk_route(55.8200, 37.6410, "ВДНХ")

        assert result["status"] == "ok"
        assert result["target_station"] == "ВДНХ"
        assert result["walk_distance_meters"] == 1000
        assert result["walk_duration_minutes"] == math.ceil(1000 / 80)
        assert result["routing_provider"] == "osrm_foot"
        assert result["route_verified"] is True


class TestOsrmFallback:
    def test_network_failure_uses_haversine_with_urban_factor(self):
        with patch(
            "nedviga.graph.load_graph", side_effect=Exception("no graph in test")), \
            patch(
            "nedviga.net_guard.guarded_get",
            side_effect=requests.exceptions.ConnectionError("boom"),
        ):
            result = walk_route(55.6405, 37.6025, "Чертановская")

        assert result["status"] == "ok"
        assert result["routing_provider"] == "haversine_fallback"
        assert result["route_verified"] is False
        assert result["fallback_reason"] == "osrm_unavailable"

        # The returned distance must be the haversine distance scaled by the
        # urban winding factor, and duration must follow 4.8 km/h.
        # v0.2.0: вестибюль берётся из сгенерированного OSM-справочника, поэтому
        # expected считаем динамически от ближайшего входа.
        from nedviga.metro_vestibules import get_vestibules
        vests = get_vestibules("Чертановская")
        raw_distance = min(
            _haversine(55.6405, 37.6025, vlat, vlon) for _, vlat, vlon in vests
        )
        expected_distance = raw_distance * URBAN_HAVERSINE_FACTOR
        assert result["walk_distance_meters"] == int(round(expected_distance))
        assert result["walk_duration_minutes"] == math.ceil(expected_distance / 80)

    def test_foot_profile_not_supported_falls_back_to_driving(self):
        def side_effect(url, **kwargs):
            response = type("Response", (), {})()
            if "/foot/" in url:
                response.status_code = 404
                response.json = lambda: {"code": "NotFound", "message": "No such profile"}

                def raise_for_status():
                    raise requests.exceptions.HTTPError("404")

                response.raise_for_status = raise_for_status
                return response
            response.status_code = 200
            response.json = lambda: {"code": "Ok", "routes": [{"distance": 900.0}]}
            response.raise_for_status = lambda: None
            return response

        with patch("nedviga.graph.load_graph", side_effect=Exception("no graph in test")), \
            patch("nedviga.metro_vestibules._load_generated", return_value=None), \
             patch("nedviga.net_guard.guarded_get", side_effect=side_effect):
            result = walk_route(55.7610, 37.5810, "Баррикадная")

        assert result["status"] == "ok"
        assert result["routing_provider"] == "osrm_driving_fallback"
        assert result["route_verified"] is False
        assert result["walk_distance_meters"] == 900
        assert result["fallback_reason"] == "osrm_unavailable"


class TestNearestVestibule:
    def test_selects_nearest_vestibule(self):
        # Use a station with two vestibules.  The origin is very close to one
        # of them, so the haversine fallback is enough to prove selection.
        # v0.2.0: справочник OSM отдаёт безымянные входы — мокаем справочник,
        # чтобы тест работал с ручным MVP-справочником (именованные вестибюли).
        with patch(
            "nedviga.graph.load_graph", side_effect=Exception("no graph in test")), \
            patch(
            "nedviga.metro_vestibules._load_generated", return_value=None), \
            patch(
            "nedviga.net_guard.guarded_get",
            side_effect=requests.exceptions.Timeout("offline"),
        ):
            # Origin next to the north vestibule of Чертановская.
            result = walk_route(55.6413, 37.6074, "Чертановская")

        assert result["target_vestibule"] == "Вестибюль 2 (северный)"
        assert result["walk_distance_meters"] > 0
        assert result["walk_duration_minutes"] > 0

    def test_osrm_success_uses_shortest_route_distance(self):
        # Павелецкая has two vestibules.  Make the south one much closer.
        # v0.2.0: справочник OSM отдаёт безымянные входы — мокаем и справочник,
        # чтобы тест проверял именно логику выбора ближайшего вестибюля.
        def side_effect(url, **kwargs):
            response = type("Response", (), {})()
            response.status_code = 200
            response.raise_for_status = lambda: None
            if "37.6364,55.7304" in url:
                response.json = lambda: {"code": "Ok", "routes": [{"distance": 300.0}]}
            else:
                response.json = lambda: {"code": "Ok", "routes": [{"distance": 1200.0}]}
            return response

        with patch("nedviga.graph.load_graph", side_effect=Exception("no graph in test")), \
             patch("nedviga.metro_vestibules._load_generated", return_value=None), \
             patch("nedviga.net_guard.guarded_get", side_effect=side_effect):
            result = walk_route(55.7305, 37.6365, "Павелецкая")

        assert result["target_vestibule"] == "Вестибюль у Павелецкого вокзала (Замоскворецкая линия)"
        assert result["walk_distance_meters"] == 300
        assert result["walk_duration_minutes"] == math.ceil(300 / 80)


class TestWalkDistanceCli:
    """In-process CLI tests with mocked OSRM (no real network)."""

    def test_cli_walk_distance_ok(self, capsys):
        with patch("nedviga.graph.load_graph", side_effect=Exception("no graph in test")), \
            patch("nedviga.metro_vestibules._load_generated", return_value=None), \
             patch("nedviga.net_guard.guarded_get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "code": "Ok",
                "routes": [{"distance": 800.0}],
            }
            mock_get.return_value.raise_for_status = lambda: None
            code = main(
                [
                    "walk-distance",
                    "--lat",
                    "55.8200",
                    "--lon",
                    "37.6410",
                    "--metro",
                    "ВДНХ",
                    "--json",
                ]
            )

        captured = capsys.readouterr()
        assert code == 0, captured.err
        payload = json.loads(captured.out)
        assert payload["status"] == "ok"
        route = payload["data"]["honest_walk_route"]
        assert route["target_station"] == "ВДНХ"
        assert route["walk_distance_meters"] == 800
        assert route["walk_duration_minutes"] == 10

    def test_cli_walk_distance_with_claim(self, capsys):
        # graph_local перехватывает запрос до OSRM — отключаем для legacy-теста
        with patch("nedviga.graph.load_graph", side_effect=Exception("no graph in test")), \
            patch("nedviga.metro_vestibules._load_generated", return_value=None), \
            patch("nedviga.routing_cache.get", return_value=None), \
             patch("nedviga.net_guard.guarded_get") as mock_get:
            mock_get.return_value.status_code = 200
            mock_get.return_value.json.return_value = {
                "code": "Ok",
                "routes": [{"distance": 800.0}],
            }
            mock_get.return_value.raise_for_status = lambda: None
            code = main(
                [
                    "walk-distance",
                    "--lat",
                    "55.8200",
                    "--lon",
                    "37.6410",
                    "--metro",
                    "ВДНХ",
                    "--claimed-time",
                    "6",
                    "--json",
                ]
            )

        captured = capsys.readouterr()
        assert code == 0
        payload = json.loads(captured.out)
        assert payload["data"]["honest_overclaim"] == {
            "overclaim_minutes": 4,
            "flag": True,
        }
