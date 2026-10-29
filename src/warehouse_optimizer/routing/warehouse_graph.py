"""Distance models.

GraphDistanceModel
    Walkable corridor network built with NetworkX. Nodes are the dock, the
    dock's access point on the front cross-aisle, aisle front/back ends and
    one access point per distinct (aisle, y) of a location. Edge weights are
    metres. Distances are shortest paths (Dijkstra).

ManhattanDistanceModel
    |dx| + |dy| between location coordinates. This is an ESTIMATE that ignores
    racks and aisles; it must never be presented as walking distance.

Both models expose the same small interface used by the routing code:
    point_of(location_id) -> hashable | None   (None = unreachable)
    start, end                                 (start/end point of a pick tour)
    dist(p, q) -> float                        (inf if no path)
    path_xy(p, q) -> list[(x, y)]              (for drawing)
"""
from __future__ import annotations

import math

import networkx as nx
import pandas as pd

from ..layout.warehouse_model import WarehouseGeometry

DOCK = "DOCK"
DOCK_ACCESS = "DOCK_ACCESS"


class GraphDistanceModel:
    mode = "graph"
    is_estimate = False
    label = "Koridor ağı üzerinde en kısa yol (metre)"

    def __init__(self, geometry: WarehouseGeometry, locations: pd.DataFrame):
        self.geometry = geometry
        self.graph = nx.Graph()
        self._location_point: dict[str, str | None] = {}
        self.notes: list[str] = []
        self._cache: dict[str, dict[str, float]] = {}
        self._build(locations)
        self.start = DOCK
        self.end = DOCK

    # -- construction ---------------------------------------------------
    def _add_node(self, node: str, x: float, y: float) -> None:
        self.graph.add_node(node, pos=(float(x), float(y)))

    def _add_edge(self, a: str, b: str) -> None:
        (xa, ya), (xb, yb) = self.graph.nodes[a]["pos"], self.graph.nodes[b]["pos"]
        self.graph.add_edge(a, b, weight=abs(xa - xb) + abs(ya - yb))

    def _build(self, locations: pd.DataFrame) -> None:
        aisles = self.geometry.aisles.set_index("aisle_id")
        front_chain: list[tuple[float, str]] = []
        back_chain: list[tuple[float, str]] = []
        clamped = 0

        for aisle_id, row in aisles.iterrows():
            x, y0, y1 = float(row["x_center"]), float(row["y_start"]), float(row["y_end"])
            front, back = f"F|{aisle_id}", f"B|{aisle_id}"
            self._add_node(front, x, y0)
            self._add_node(back, x, y1)
            front_chain.append((x, front))
            back_chain.append((x, back))

            locs = locations[locations["aisle_id"] == aisle_id]
            ys = {}
            for loc_id, y in zip(locs["location_id"], locs["y"]):
                y_access = min(max(float(y), y0), y1)
                if y_access != float(y):
                    clamped += 1
                key = round(y_access, 3)
                node = f"P|{aisle_id}|{key:.3f}"
                ys[key] = node
                self._location_point[loc_id] = node
            chain = [(y0, front)] + sorted((k, n) for k, n in ys.items()) + [(y1, back)]
            for _, node in chain[1:-1]:
                self._add_node(node, x, float(node.rsplit("|", 1)[1]))
            for (_, a), (_, b) in zip(chain, chain[1:]):
                if a != b:
                    self._add_edge(a, b)

        dock_x, dock_y = self.geometry.dock_xy
        self._add_node(DOCK, dock_x, dock_y)
        if front_chain:
            nearest = min(front_chain, key=lambda item: (abs(item[0] - dock_x), item[1]))
            access_y = self.graph.nodes[nearest[1]]["pos"][1]
            self._add_node(DOCK_ACCESS, dock_x, access_y)
            front_chain.append((dock_x, DOCK_ACCESS))
            self._add_edge(DOCK, DOCK_ACCESS)
        for chain in (front_chain, back_chain):
            chain.sort(key=lambda item: (item[0], item[1]))
            for (_, a), (_, b) in zip(chain, chain[1:]):
                self._add_edge(a, b)

        for loc_id in locations["location_id"]:
            if loc_id not in self._location_point:
                self._location_point[loc_id] = None
        unreachable = [l for l, p in self._location_point.items() if p is None]
        if unreachable:
            self.notes.append(f"{len(unreachable)} lokasyonun koridoru geometride yok; bu lokasyonlara ulaşılamaz.")
        if clamped:
            self.notes.append(f"{clamped} lokasyonun Y koordinatı koridor uçlarının dışında; erişim noktası koridor "
                              "ucuna sabitlendi.")

    # -- interface --------------------------------------------------------
    def point_of(self, location_id: str):
        point = self._location_point.get(location_id)
        if point is None:
            return None
        if not self._reachable_from_dock(point):
            return None
        return point

    def _lengths_from(self, node: str) -> dict[str, float]:
        if node not in self._cache:
            self._cache[node] = nx.single_source_dijkstra_path_length(self.graph, node, weight="weight")
        return self._cache[node]

    def _reachable_from_dock(self, node: str) -> bool:
        return node in self._lengths_from(DOCK)

    def dist(self, p, q) -> float:
        if p == q:
            return 0.0
        return float(self._lengths_from(p).get(q, math.inf))

    def path_xy(self, p, q) -> list[tuple[float, float]]:
        nodes = nx.shortest_path(self.graph, p, q, weight="weight")
        return [self.graph.nodes[n]["pos"] for n in nodes]

    def xy(self, point) -> tuple[float, float]:
        return self.graph.nodes[point]["pos"]

    def edges_xy(self) -> list[tuple[tuple[float, float], tuple[float, float]]]:
        return [(self.graph.nodes[a]["pos"], self.graph.nodes[b]["pos"]) for a, b in self.graph.edges]


class ManhattanDistanceModel:
    mode = "manhattan"
    is_estimate = True
    label = "TAHMİNİ Manhattan mesafesi (koridor ağı yok; gerçek yürüme mesafesi değildir)"

    def __init__(self, locations: pd.DataFrame, dock_xy: tuple[float, float]):
        self._xy = {loc: (float(x), float(y)) for loc, x, y in zip(locations["location_id"], locations["x"], locations["y"])}
        self._xy[DOCK] = (float(dock_xy[0]), float(dock_xy[1]))
        self.start = DOCK
        self.end = DOCK
        self.notes = ["Mesafeler koordinatlar arası Manhattan mesafesi olarak tahmin edilmiştir."]

    def point_of(self, location_id: str):
        return location_id if location_id in self._xy else None

    def dist(self, p, q) -> float:
        (xa, ya), (xb, yb) = self._xy[p], self._xy[q]
        return abs(xa - xb) + abs(ya - yb)

    def path_xy(self, p, q) -> list[tuple[float, float]]:
        (xa, ya), (xb, yb) = self._xy[p], self._xy[q]
        return [(xa, ya), (xb, ya), (xb, yb)]

    def xy(self, point) -> tuple[float, float]:
        return self._xy[point]


def location_dock_distances(model, location_ids) -> pd.Series:
    """One-way distance from each location's access point to the dock (NaN = unreachable)."""
    values = {}
    for loc in location_ids:
        point = model.point_of(loc)
        values[loc] = math.nan if point is None else model.dist(model.start, point)
    return pd.Series(values, name="dock_distance_m", dtype=float)
