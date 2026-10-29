import copy

import pandas as pd
import pytest

from conftest import make_dataset, product, small_locations
from warehouse_optimizer.pipeline import run_pipeline
from warehouse_optimizer.settings import load_settings


def settings(**slotting):
    s = load_settings()
    s["slotting"].update(slotting)
    return s


def _dataset(locations=None, products=None, inventory=None, orders=None):
    products = products or [product("P1"), product("P2"), product("P3")]
    orders = orders or ([{"order_id": f"O{i}", "order_date": f"2026-09-{i + 1:02d}", "sku": "P1", "quantity": 1}
                         for i in range(10)]
                        + [{"order_id": "O20", "order_date": "2026-09-20", "sku": "P2", "quantity": 1},
                           {"order_id": "O21", "order_date": "2026-09-21", "sku": "P3", "quantity": 1}])
    inventory = inventory or [{"sku": "P1", "location_id": "A2-8", "current_quantity": 5},
                              {"sku": "P2", "location_id": "A2-5", "current_quantity": 5},
                              {"sku": "P3", "location_id": "A1-2", "current_quantity": 5}]
    return make_dataset(products, orders, locations or small_locations(), inventory)


def test_hybrid_moves_popular_sku_to_closest_slot_via_eviction(small_dataset):
    res = run_pipeline(small_dataset, settings())
    moves = res.slotting["hybrid"].moves
    assert list(moves["sku"]) == ["P3", "P1"]  # P3 is evicted first, then P1 takes its place
    assert list(moves["move_type"]) == ["evict", "move"]
    assert res.slotting["hybrid"].placement_proposed["P1"] == ["A1-2"]
    plan = res.move_plans["hybrid"]
    assert (plan["constraint_check"] == "Geçti").all()


def test_move_sequence_is_executable(small_dataset):
    res = run_pipeline(small_dataset, settings())
    inventory = res.validation.tables["inventory"]
    occupied = set(inventory["location_id"])
    for _, m in res.slotting["hybrid"].moves.sort_values("sequence").iterrows():
        assert m["to_location"] not in occupied
        occupied.discard(m["from_location"])
        occupied.add(m["to_location"])


def test_fixed_location_is_protected():
    locs = small_locations(**{"A1-2": {"is_fixed": "true"}})
    res = run_pipeline(_dataset(locations=locs), settings())
    slot = res.slotting["hybrid"]
    assert "P3" in set(slot.not_movable["sku"])
    assert "A1-2" not in set(slot.moves["to_location"]) and "A1-2" not in set(slot.moves["from_location"])
    assert slot.placement_proposed["P3"] == ["A1-2"]


def test_unavailable_locations_are_never_targets():
    locs = small_locations(**{"A1-5": {"is_available": "false"}, "A1-8": {"is_pickable": "false"}})
    res = run_pipeline(_dataset(locations=locs), settings())
    for method in ("hybrid", "class_based"):
        targets = set(res.slotting[method].moves["to_location"])
        assert not targets & {"A1-5", "A1-8"}


def test_no_feasible_location_is_reported_and_no_violating_assignment():
    # P1 is too heavy for every location except its current one.
    locs = small_locations(**{"A2-8": {"max_weight_kg": 1000}})
    products = [product("P1", weight=100.0), product("P2"), product("P3")]
    res = run_pipeline(_dataset(locations=locs, products=products), settings())
    slot = res.slotting["hybrid"]
    assert "P1" in set(slot.unassignable["sku"])
    assert "Ağırlık" in slot.unassignable.set_index("sku").at["P1", "reason"]
    assert "P1" not in set(slot.moves["sku"])


def test_size_mismatch_blocks_target():
    locs = small_locations(**{"A1-2": {"max_height_m": 0.1}, "A1-5": {"max_height_m": 0.1}})
    res = run_pipeline(_dataset(locations=locs), settings())
    plan = res.move_plans["hybrid"]
    assert not set(plan[plan["sku"] == "P1"]["to_location"]) & {"A1-2", "A1-5"}
    assert (plan["constraint_check"] == "Geçti").all()


def test_max_moves_is_respected_and_zero_disables():
    res = run_pipeline(_dataset(), settings(max_moves=1))
    assert res.slotting["hybrid"].move_count == 1  # the eviction pair needs 2 moves -> a direct move is used
    assert res.slotting["hybrid"].placement_proposed["P1"] == ["A1-5"]
    res0 = run_pipeline(_dataset(), settings(max_moves=0))
    assert res0.slotting["hybrid"].move_count == 0
    assert res0.comparisons["hybrid"].summary["difference_m"] == 0


def test_move_threshold_prevents_small_moves():
    s = settings()
    s["slotting"]["hybrid"]["move_cost_m"] = 10_000
    res = run_pipeline(_dataset(), s)
    assert res.slotting["hybrid"].move_count == 0


def test_multi_location_sku_is_not_moved():
    inventory = [{"sku": "P1", "location_id": "A2-8", "current_quantity": 5},
                 {"sku": "P1", "location_id": "A2-2", "current_quantity": 5},
                 {"sku": "P2", "location_id": "A2-5", "current_quantity": 5},
                 {"sku": "P3", "location_id": "A1-2", "current_quantity": 5}]
    res = run_pipeline(_dataset(inventory=inventory), settings())
    slot = res.slotting["hybrid"]
    assert slot.not_movable.set_index("sku").at["P1", "reason_code"] == "multi_location"
    assert "P1" not in set(slot.moves["sku"])


def test_storage_requirements_respected():
    locs = small_locations(**{"A2-2": {"storage_class": "cold"}})
    products = [product("P1"), product("P2"), product("P3", storage_requirements="cold")]
    inventory = [{"sku": "P1", "location_id": "A2-8", "current_quantity": 5},
                 {"sku": "P2", "location_id": "A2-5", "current_quantity": 5},
                 {"sku": "P3", "location_id": "A2-2", "current_quantity": 5}]
    res = run_pipeline(_dataset(locations=locs, products=products, inventory=inventory), settings())
    for method in ("hybrid", "class_based"):
        moves = res.slotting[method].moves
        assert "A2-2" not in set(moves[moves["sku"] != "P3"]["to_location"])
        assert set(moves[moves["sku"] == "P3"]["to_location"]) <= {"A2-2"}


def test_class_based_places_a_items_in_a_zone(small_dataset):
    res = run_pipeline(small_dataset, settings())
    table = res.sku_table("class_based").set_index("sku")
    assert table.at["P1", "abc_class"] == "A"
    assert table.at["P1", "proposed_dock_distance_m"] < table.at["P1", "current_dock_distance_m"]


@pytest.mark.parametrize("method", ["hybrid", "class_based"])
def test_deterministic_results(method):
    from warehouse_optimizer.data.demo_generator import generate_demo_dataset

    s = load_settings()
    a = run_pipeline(generate_demo_dataset(), copy.deepcopy(s))
    b = run_pipeline(generate_demo_dataset(), copy.deepcopy(s))
    pd.testing.assert_frame_equal(a.slotting[method].moves, b.slotting[method].moves)
    assert a.comparisons[method].summary["total_proposed_m"] == b.comparisons[method].summary["total_proposed_m"]


def test_demo_plan_has_no_constraint_violations():
    from warehouse_optimizer.data.demo_generator import generate_demo_dataset

    res = run_pipeline(generate_demo_dataset(), load_settings())
    for method in ("hybrid", "class_based"):
        plan = res.move_plans[method]
        assert not plan.empty
        assert (plan["constraint_check"] == "Geçti").all()
        assert plan["sku"].is_unique
        assert res.slotting[method].move_count <= res.settings["slotting"]["max_moves"]
