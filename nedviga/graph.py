"""Локальный пешеходный граф Москвы: загрузка, снап, A*.

Граф поставляется артефактом (pickle, см. tools/build_graph.py) и кладётся
в nedviga/graph_moscow.pkg или по пути из NEDVIGA_GRAPH_PATH.
"""
from __future__ import annotations

import heapq
import math
import pickle
from pathlib import Path

# Приоритет путей поиска граф-файла
DEFAULT_GRAPH_PATHS = [
    Path(__file__).parent / "graph_moscow.pkg",
    Path(__file__).parent.parent / "graph_moscow.pkg",
]

_walking_speed_m_per_min = 80.0  # 4.8 km/h, согласовано с SPEC


class GraphNotAvailable(Exception):
    """Граф не найден/не загружен."""


class _Graph:
    __slots__ = ("nodes", "edges", "adj", "version", "built_at", "_grid_cache")

    def __init__(self, nodes: dict, edges: dict, version: int, built_at: str):
        self.nodes = nodes              # {id: (lat, lon)}
        self.edges = edges              # {id: [(id, meters), ...]}
        self.version = version
        self.built_at = built_at
        self.adj = edges                # alias
        self._grid_cache = None

    def nearest_node(self, lat: float, lon: float, max_m: float = 400.0) -> int | None:
        """Ближайший узел графа. Линейный поиск приемлем: узлов ~200-400k,
        но для скорости — сетка-индекс."""
        # Простой грид-индекс
        cell = 0.005  # ~500 м
        best, best_d = None, max_m
        la0, la1 = math.floor((lat - max_m/111000) / cell), math.ceil((lat + max_m/111000) / cell)
        lo0, lo1 = math.floor((lon - max_m/111000) / (cell * 0.6)), math.ceil((lon + max_m/111000) / (cell * 0.6))
        grid = self._grid()
        for ga in range(la0, la1 + 1):
            for go in range(lo0, lo1 + 1):
                for nid in grid.get((ga, go), ()):  # noqa
                    nla, nlo = self.nodes[nid]
                    d = _haversine(lat, lon, nla, nlo)
                    if d < best_d:
                        best, best_d = nid, d
        return best

    def _grid(self) -> dict:
        if self._grid_cache is None:
            g: dict[tuple[int, int], list[int]] = {}
            cell = 0.005
            for nid, (la, lo) in self.nodes.items():
                g.setdefault((math.floor(la / cell), math.floor(lo / (cell * 0.6))), []).append(nid)
            self._grid_cache = g
        return self._grid_cache


_graph: _Graph | None = None


def _haversine(lat1, lon1, lat2, lon2):
    r = 6_371_000.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def load_graph(explicit: Path | None = None) -> _Graph:
    """Загрузить граф (однократно). Path: explicit > NEDVIGA_GRAPH_PATH > дефолты."""
    global _graph
    if _graph is not None:
        return _graph
    import os

    candidates = []
    if explicit:
        candidates.append(explicit)
    env = os.environ.get("NEDVIGA_GRAPH_PATH")
    if env:
        candidates.append(Path(env))
    candidates.extend(DEFAULT_GRAPH_PATHS)
    import hashlib
    for c in candidates:
        if c.exists():
            # v0.4.5 (review R14/R9): pickle = RCE при подмене файла.
            # Грузим только с валидным sidecar .sha256; осознанный обход — явным env.
            sidecar = Path(str(c) + ".sha256")
            allow_unsigned = os.environ.get("NEDVIGA_GRAPH_ALLOW_UNSIGNED") == "1"
            if sidecar.exists():
                want = sidecar.read_text(encoding="ascii").split()[0].lower()
                got = hashlib.sha256(c.read_bytes()).hexdigest()
                if want != got:
                    raise GraphNotAvailable(f"graph-артефакт повреждён: sha256 {got[:12]} != {want[:12]} (подмена?)")
            elif not allow_unsigned:
                raise GraphNotAvailable(
                    f"{c} без sidecar .sha256 — pickle без верификации запрещён "
                    f"(сгенерируй: sha256sum pkg > pkg.sha256, или осознанно NEDVIGA_GRAPH_ALLOW_UNSIGNED=1)")
            with open(c, "rb") as f:
                data = pickle.load(f)
            _graph = _Graph(data["nodes"], data["edges"], data.get("version", 1), data.get("built_at", ""))
            return _graph
    raise GraphNotAvailable("graph_moscow.pkg не найден (NEDVIGA_GRAPH_PATH или рядом с пакетом)")


def route(lat: float, lon: float, mlat: float, mlon: float) -> tuple[float, str] | None:
    """Пешее расстояние между двумя координатами по графу. (meters, provider) или None."""
    g = load_graph()
    s = g.nearest_node(lat, lon)
    t = g.nearest_node(mlat, mlon)
    if s is None or t is None:
        return None
    if s == t:
        return 0.0, "graph_local"
    # A* по haversine-эвристике
    dist: dict[int, float] = {s: 0.0}
    pq = [(0.0, s)]
    seen: set[int] = set()
    while pq:
        _, u = heapq.heappop(pq)
        if u in seen:
            continue
        seen.add(u)
        if u == t:
            meters = dist[t]
            # + снап-хвосты до реальных точек
            nla, nlo = g.nodes[s]
            mla, mlo = g.nodes[t]
            meters += _haversine(lat, lon, nla, nlo) + _haversine(mla, mlo, mlat, mlo)
            return round(meters, 1), "graph_local"
        for v, m in g.adj.get(u, ()):
            if v in seen:
                continue
            nd = dist[u] + m
            if v not in dist or nd < dist[v]:
                dist[v] = nd
                # эвристика: прямая до цели
                hla, hlo = g.nodes[v]
                h = _haversine(hla, hlo, mlat, mlon)
                heapq.heappush(pq, (nd + h, v))
    return None
