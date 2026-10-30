import io
import math

import pandas as pd
import pytest

from conftest import AISLES, DOCK, location
from warehouse_optimizer.data.demo_generator import generate_demo_dataset
from warehouse_optimizer.layout.warehouse_model import build_geometry
from warehouse_optimizer.pipeline import run_pipeline
from warehouse_optimizer.reporting.exports import to_csv_bytes, to_excel_bytes
from warehouse_optimizer.reporting.report_builder import REPORT_TITLES, build_reports, report_bundle_metadata
from warehouse_optimizer.routing.warehouse_graph import GraphDistanceModel, location_dock_distances
from warehouse_optimizer.settings import load_settings
from warehouse_optimizer.simulation.comparison import OperationParams, compare_placements, improvement_pct


def test_improvement_formula_and_zero_distance():
    assert improvement_pct(200, 150) == pytest.approx(25.0)
    assert improvement_pct(100, 120) == pytest.approx(-20.0)  # negative improvement is kept
    assert math.isnan(improvement_pct(0, 0))


@pytest.fixture
def model_and_dock():
    rows = [location(f"{a}-{y}", a, xc - 1, y) for a, xc in (("A1", 2.0), ("A2", 8.0)) for y in (2, 5, 8)]
    locs = pd.DataFrame(rows)
    for col in ("x", "y"):
        locs[col] = locs[col].astype(float)
    model = GraphDistanceModel(build_geometry(locs, pd.DataFrame(AISLES), DOCK), locs)
    return model, location_dock_distances(model, locs["location_id"])


def _lines(orders):
    rows = []
    for oid, skus in orders.items():
        for s in skus:
            rows.append({"order_id": oid, "order_date": pd.Timestamp("2026-09-01"), "sku": s, "quantity": 1,
                         "movement_type": "outbound"})
    return pd.DataFrame(rows)


def test_same_orders_compared_and_negative_improvement_visible(model_and_dock):
    model, dock = model_and_dock
    lines = _lines({"O1": ["P1"], "O2": ["P1", "P2"]})
    current = {"P1": ["A1-2"], "P2": ["A1-5"]}
    worse = {"P1": ["A2-8"], "P2": ["A1-5"]}
    res = compare_placements(lines, current, worse, model, dock, OperationParams())
    assert list(res.per_order["order_id"]) == ["O1", "O2"]
    s = res.summary
    assert s["orders_compared"] == 2
    assert s["improvement_pct"] < 0
    assert s["orders_worse"] == 2
    assert res.per_order.set_index("order_id").at["O1", "distance_current_m"] == pytest.approx(12.0)
    assert res.per_order.set_index("order_id").at["O1", "distance_proposed_m"] == pytest.approx(36.0)


def test_identical_placement_gives_zero_difference(model_and_dock):
    model, dock = model_and_dock
    placement = {"P1": ["A1-2"], "P2": ["A2-5"]}
    res = compare_placements(_lines({"O1": ["P1", "P2"]}), placement, placement, model, dock, OperationParams())
    assert res.summary["difference_m"] == 0
    assert res.summary["improvement_pct"] == 0


def test_time_units_and_cost(model_and_dock):
    model, dock = model_and_dock
    params = OperationParams(walking_speed_m_s=1.2, pick_time_s_per_stop=10, daily_orders=100, operating_days=250,
                             hourly_labor_cost=200)
    lines = _lines({"O1": ["P1"]})
    res = compare_placements(lines, {"P1": ["A2-8"]}, {"P1": ["A1-2"]}, model, dock, params)
    s = res.summary
    # current 36 m, proposed 12 m, 1 stop each
    assert s["time_current_h"] == pytest.approx((36 / 1.2 + 10) / 3600)
    assert s["time_proposed_h"] == pytest.approx((12 / 1.2 + 10) / 3600)
    assert s["projected_hours_saved"] == pytest.approx((24 / 1.2) / 3600 * 100 * 250)
    assert s["projected_labor_cost_saved"] == pytest.approx(s["projected_hours_saved"] * 200)


def test_missing_parameters_are_not_invented(model_and_dock):
    model, dock = model_and_dock
    res = compare_placements(_lines({"O1": ["P1"]}), {"P1": ["A2-8"]}, {"P1": ["A1-2"]}, model, dock,
                             OperationParams())
    s = res.summary
    assert math.isnan(s["projected_hours_saved"]) and math.isnan(s["projected_labor_cost_saved"])
    assert s["time_includes_pick_time"] is False
    assert any("toplama süresi" in n for n in res.notes)


def test_lines_without_location_are_skipped_in_both_scenarios(model_and_dock):
    model, dock = model_and_dock
    res = compare_placements(_lines({"O1": ["P1", "PX"]}), {"P1": ["A1-2"]}, {"P1": ["A1-2"]}, model, dock,
                             OperationParams())
    assert res.per_order.iloc[0]["lines"] == 1
    assert any("toplama lokasyonu yok" in n for n in res.notes)


def test_demo_dataset_meets_size_requirements():
    ds = generate_demo_dataset()
    assert ds.is_synthetic
    assert ds.tables["products"]["sku"].nunique() >= 50
    assert len(ds.tables["locations"]) >= 100
    assert ds.tables["order_lines"]["order_id"].nunique() >= 200
    assert ds.tables["locations"]["aisle_id"].nunique() > 1
    a = generate_demo_dataset()
    pd.testing.assert_frame_equal(ds.tables["order_lines"], a.tables["order_lines"])


def test_end_to_end_demo_and_exports():
    res = run_pipeline(generate_demo_dataset(), load_settings())
    assert res.ok and res.is_synthetic
    assert set(res.abc.class_counts()) == {"A", "B", "C"}
    for method in ("hybrid", "class_based"):
        s = res.comparisons[method].summary
        assert s["orders_compared"] > 0
        assert s["stops_current"] == s["stops_proposed"]  # same orders, same stops
        assert s["improvement_pct"] == pytest.approx(
            (s["total_current_m"] - s["total_proposed_m"]) / s["total_current_m"] * 100)

    reports = build_reports(res)
    assert set(reports) == set(REPORT_TITLES)
    meta = report_bundle_metadata(res)
    assert meta["Sentetik veri"] == "Evet" and "Analiz dönemi" in meta

    csv = to_csv_bytes(reports["move_plan"], meta).decode("utf-8-sig")
    assert csv.startswith("# Veri kaynağı:")
    body = pd.read_csv(io.StringIO(csv), comment="#")
    assert len(body) == len(reports["move_plan"]) and "Hedef lokasyon" in body.columns

    xlsx = to_excel_bytes({REPORT_TITLES[k]: v for k, v in reports.items()}, meta)
    book = pd.read_excel(io.BytesIO(xlsx), sheet_name=None)
    assert "Rapor bilgisi" in book
    assert len(book[REPORT_TITLES["move_plan"][:31]]) == len(reports["move_plan"])


def test_pipeline_reports_missing_tables():
    ds = generate_demo_dataset()
    del ds.tables["inventory"]
    res = run_pipeline(ds, load_settings())
    assert not res.ok and "inventory" in res.errors[0]
    assert "data_quality" in build_reports(res)


def test_manhattan_mode_end_to_end():
    s = load_settings()
    s["geometry"]["distance_mode"] = "manhattan"
    res = run_pipeline(generate_demo_dataset(), s)
    assert res.distance_is_estimate
    assert any("TAHMİNİ" in a or "Tahmini" in a or "Manhattan" in a for a in
               build_reports(res)["assumptions"]["Madde"])
