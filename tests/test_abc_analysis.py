import math

import pandas as pd
import pytest

from warehouse_optimizer.analytics.abc_analysis import classify_abc
from warehouse_optimizer.analytics.movement_analysis import resolve_period, sku_movement


def movement(values: dict) -> pd.DataFrame:
    return pd.DataFrame({"sku": list(values), "order_lines": list(values.values()),
                         "quantity": list(values.values()), "active_days": list(values.values())})


def test_cumulative_share_and_classes():
    # shares: 50, 30, 10, 5, 3, 2 (%)
    res = classify_abc(movement({"S1": 50, "S2": 30, "S3": 10, "S4": 5, "S5": 3, "S6": 2}))
    t = res.table.set_index("sku")
    assert t["cumulative_share"].round(4).tolist() == [0.5, 0.8, 0.9, 0.95, 0.98, 1.0]
    # Previous cumulative < 0.80 -> A ; < 0.95 -> B ; else C
    assert t["abc_class"].tolist() == ["A", "A", "B", "B", "C", "C"]
    assert res.class_counts() == {"A": 2, "B": 2, "C": 2}
    assert res.class_share()["A"] == pytest.approx(0.8)


def test_single_dominant_sku_is_a():
    res = classify_abc(movement({"S1": 95, "S2": 4, "S3": 1}))
    # S1 crosses 80 % on its own and stays A; S2 starts exactly at 95 % -> C.
    assert res.table["abc_class"].tolist() == ["A", "C", "C"]
    res = classify_abc(movement({"S1": 90, "S2": 6, "S3": 4}))
    assert res.table["abc_class"].tolist() == ["A", "B", "C"]


def test_ties_are_deterministic_by_sku():
    res = classify_abc(movement({"Z": 10, "A": 10, "M": 10}))
    assert res.table["sku"].tolist() == ["A", "M", "Z"]
    again = classify_abc(movement({"M": 10, "Z": 10, "A": 10}))
    pd.testing.assert_frame_equal(res.table, again.table)


def test_zero_movement_is_c_and_empty_is_undefined():
    res = classify_abc(movement({"S1": 10, "S2": 0}))
    assert res.table.set_index("sku").at["S2", "abc_class"] == "C"
    empty = classify_abc(movement({"S1": 0, "S2": 0}))
    assert not empty.defined
    assert empty.table["cumulative_share"].isna().all()
    none = classify_abc(movement({}))
    assert not none.defined and none.table.empty
    assert all(math.isnan(v) for v in none.class_share().values())


def test_custom_thresholds_and_validation():
    res = classify_abc(movement({"S1": 50, "S2": 30, "S3": 20}), a_share=0.5, b_share=0.3)
    assert res.table["abc_class"].tolist() == ["A", "B", "C"]
    with pytest.raises(ValueError):
        classify_abc(movement({"S1": 1}), a_share=0.9, b_share=0.2)
    with pytest.raises(ValueError):
        classify_abc(movement({"S1": 1}), metric="value")


def _lines():
    return pd.DataFrame({
        "order_id": ["O1", "O1", "O2", "O3", "O4"],
        "order_date": pd.to_datetime(["2026-01-01", "2026-01-01", "2026-03-01", "2026-03-31", "2026-03-31"]),
        "sku": ["A", "B", "A", "A", "B"],
        "quantity": [10, 1, 5, 5, 100],
        "movement_type": ["outbound", "outbound", "outbound", "outbound", "return"],
    })


def test_period_and_metrics_exclude_returns():
    lines = _lines()
    period = resolve_period(lines, 90)
    assert period.end == pd.Timestamp("2026-03-31")
    assert period.days == 90
    products = pd.DataFrame({"sku": ["A", "B", "C"]})
    mv = sku_movement(lines, products, period).set_index("sku")
    assert mv.at["A", "order_lines"] == 3 and mv.at["A", "quantity"] == 20
    assert mv.at["B", "order_lines"] == 1  # the return is not counted
    assert mv.at["C", "order_lines"] == 0
    short = resolve_period(lines, 30)
    assert short.start == pd.Timestamp("2026-03-02")
    mv30 = sku_movement(lines, products, short).set_index("sku")
    assert mv30.at["A", "order_lines"] == 1 and mv30.at["A", "active_days"] == 1


def test_period_note_when_data_is_shorter_than_requested():
    period = resolve_period(_lines(), 365)
    assert period.start == pd.Timestamp("2026-01-01")
    assert "tamamlanamadı" in period.note


def test_metric_choice_changes_ranking():
    lines = _lines()
    period = resolve_period(lines, 90)
    mv = sku_movement(lines, pd.DataFrame({"sku": ["A", "B"]}), period)
    by_lines = classify_abc(mv, "order_lines").table["sku"].tolist()
    by_qty = classify_abc(mv, "quantity").table["sku"].tolist()
    assert by_lines[0] == "A" and by_qty[0] == "A"
    assert classify_abc(mv, "active_days").table.set_index("sku").at["A", "metric_value"] == 3
