import math

import pandas as pd
import pytest

from conftest import AISLES, DOCK, location
from warehouse_optimizer.layout.warehouse_model import build_geometry
from warehouse_optimizer.routing.picking_routes import route_locations, route_path_xy
from warehouse_optimizer.routing.warehouse_graph import (GraphDistanceModel, ManhattanDistanceModel,
                                                         location_dock_distances)


@pytest.fixture
def locations():
    rows = [location(f"{a}-{y}", a, xc - 1, y) for a, xc in (("A1", 2.0), ("A2", 8.0)) for y in (2, 5, 8)]
    rows.append(location("A9-1", "A9", 30.0, 3.0))  # aisle missing from geometry -> unreachable
    df = pd.DataFrame(rows)
    for col in ("x", "y", "z"):
        df[col] = df[col].astype(float)
    return df


@pytest.fixture
def model(locations):
    geometry = build_geometry(locations, pd.DataFrame(AISLES), DOCK)
    return GraphDistanceModel(geometry, locations)


def test_shortest_path_distances(model):
    d = location_dock_distances(model, ["A1-2", "A1-8", "A2-5", "A2-8"])
    # dock (0,-2) -> front cross-aisle (0,0): 2 ; along front to aisle x ; up the aisle to y
    assert d["A1-2"] == pytest.approx(2 + 2 + 2)
    assert d["A1-8"] == pytest.approx(2 + 2 + 8)
    assert d["A2-5"] == pytest.approx(2 + 8 + 5)
    # between deep locations of neighbouring aisles the back cross-aisle (y=10) is shorter
    p, q = model.point_of("A1-8"), model.point_of("A2-8")
    assert model.dist(p, q) == pytest.approx(2 + 6 + 2)


def test_unreachable_location(model):
    assert model.point_of("A9-1") is None
    assert math.isnan(location_dock_distances(model, ["A9-1"])["A9-1"])
    r = route_locations(model, ["A1-2", "A9-1"])
    assert not r.valid and r.unreachable == ["A9-1"]
    assert any("ulaşılamaz" in n for n in model.notes)


def test_zero_stops_and_single_stop(model):
    empty = route_locations(model, [])
    assert empty.valid and empty.distance_m == 0 and empty.n_stops == 0
    single = route_locations(model, ["A1-2"])
    assert single.distance_m == pytest.approx(12.0)  # out and back


def test_multi_stop_route_and_dedup(model):
    r = route_locations(model, ["A2-8", "A1-8", "A1-8"])
    assert r.n_stops == 2
    # dock -> A1-8 (12) -> back aisle to A2-8 (10) -> A2-8 to dock (18) = 40
    assert r.distance_m == pytest.approx(40.0)
    coords = route_path_xy(model, r)
    assert coords[0] == coords[-1] == DOCK


def test_two_opt_never_worse_than_nearest_neighbour(model):
    stops = ["A2-2", "A1-8", "A2-8", "A1-5", "A2-5"]
    nn = route_locations(model, stops, use_two_opt=False)
    opt = route_locations(model, stops, use_two_opt=True)
    assert opt.distance_m <= nn.distance_m + 1e-9


def test_manhattan_is_flagged_as_estimate(locations):
    m = ManhattanDistanceModel(locations, DOCK)
    assert m.is_estimate and "TAHMİNİ" in m.label
    assert location_dock_distances(m, ["A1-2"])["A1-2"] == pytest.approx(1 + 4)


def test_derived_geometry_is_flagged(locations):
    geometry = build_geometry(locations[locations["aisle_id"] != "A9"], None, None)
    assert geometry.source == "derived" and geometry.dock_source == "default"
    assert geometry.is_approximate
    assert len(geometry.notes) == 2
