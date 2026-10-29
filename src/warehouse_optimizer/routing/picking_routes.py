"""Single-picker tour construction: start -> stops -> end.

* Stops are unique locations; locations sharing one access point are walked
  to once (distance) but still counted as separate pick stops.
* Construction: nearest neighbour from the start point (ties broken by point
  id), optionally improved with 2-opt on the open path with fixed endpoints.
  This is a heuristic: the result is a good tour, not a proven optimum.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field


@dataclass
class RouteResult:
    distance_m: float
    n_stops: int
    sequence: list = field(default_factory=list)  # points incl. start and end
    stop_locations: list = field(default_factory=list)
    unreachable: list = field(default_factory=list)

    @property
    def valid(self) -> bool:
        return not self.unreachable and not math.isnan(self.distance_m) and not math.isinf(self.distance_m)


def _path_length(model, path: list) -> float:
    return sum(model.dist(a, b) for a, b in zip(path, path[1:]))


def _nearest_neighbour(model, start, points: list) -> list:
    remaining = sorted(points, key=str)
    tour = [start]
    current = start
    while remaining:
        best = min(remaining, key=lambda p: (model.dist(current, p), str(p)))
        tour.append(best)
        remaining.remove(best)
        current = best
    return tour


def _two_opt(model, path: list, max_rounds: int = 50) -> list:
    """2-opt on an open path whose first and last elements are fixed."""
    best = list(path)
    n = len(best)
    if n < 5:  # start + 3 stops + end is the smallest case that can improve
        return best
    for _ in range(max_rounds):
        improved = False
        for i in range(1, n - 2):
            for k in range(i + 1, n - 1):
                a, b, c, d = best[i - 1], best[i], best[k], best[k + 1]
                delta = model.dist(a, c) + model.dist(b, d) - model.dist(a, b) - model.dist(c, d)
                if delta < -1e-9:
                    best[i:k + 1] = reversed(best[i:k + 1])
                    improved = True
        if not improved:
            break
    return best


def route_locations(model, location_ids, use_two_opt: bool = True) -> RouteResult:
    stops = list(dict.fromkeys(location_ids))  # unique, order-preserving
    if not stops:
        return RouteResult(0.0, 0, [model.start, model.end], [], [])
    unreachable = [loc for loc in stops if model.point_of(loc) is None]
    if unreachable:
        return RouteResult(math.nan, len(stops), [], stops, unreachable)
    points = list(dict.fromkeys(model.point_of(loc) for loc in stops))
    path = _nearest_neighbour(model, model.start, points) + [model.end]
    if use_two_opt:
        path = _two_opt(model, path)
    distance = _path_length(model, path)
    if math.isinf(distance):
        return RouteResult(math.nan, len(stops), path, stops, [loc for loc in stops])
    return RouteResult(distance, len(stops), path, stops, [])


def route_path_xy(model, result: RouteResult) -> list[tuple[float, float]]:
    coords: list[tuple[float, float]] = []
    for a, b in zip(result.sequence, result.sequence[1:]):
        segment = model.path_xy(a, b)
        coords.extend(segment if not coords else segment[1:])
    return coords
