import numpy as np
import pandas as pd

from warehouse_optimizer.optimization.constraints import (check_placement, feasibility_matrix,
                                                          max_units_fitting)


def prod(**kw):
    base = {"sku": "P", "length_m": 0.5, "width_m": 0.4, "height_m": 0.3, "weight_kg": 5.0, "stackable": True,
            "storage_requirements": "standard", "handling_type": "manual"}
    base.update(kw)
    return pd.Series(base)


def loc(**kw):
    base = {"location_id": "L", "max_length_m": 1.0, "max_width_m": 0.6, "max_height_m": 0.7,
            "max_weight_kg": 100.0, "max_volume_m3": 0.42, "is_available": True, "storage_class": "standard",
            "location_type": "shelf"}
    base.update(kw)
    return pd.Series(base)


def test_fits_with_horizontal_rotation():
    assert check_placement(prod(length_m=0.5, width_m=0.9), loc(), 1) == []  # rotated 0.9 x 0.5 fits 1.0 x 0.6


def test_dimension_mismatch():
    assert "dimension" in check_placement(prod(length_m=1.1, width_m=0.7), loc(), 1)
    assert "dimension" in check_placement(prod(height_m=0.8), loc(), 1)  # no tipping


def test_weight_and_volume_capacity():
    assert "weight" in check_placement(prod(weight_kg=30), loc(), 4)  # 120 kg > 100 kg
    assert "weight" not in check_placement(prod(weight_kg=25), loc(), 4)
    assert "volume" in check_placement(prod(), loc(max_volume_m3=0.1), 2)  # 0.12 m3 > 0.1


def test_packing_respects_stackability():
    # per layer: floor(1.0/0.5)*floor(0.6/0.4)=2 ; layers floor(0.7/0.3)=2 -> 4 units
    assert check_placement(prod(), loc(max_volume_m3=10), 4) == []
    assert "packing" in check_placement(prod(), loc(max_volume_m3=10), 5)
    assert "packing" in check_placement(prod(stackable=False), loc(max_volume_m3=10), 3)
    assert max_units_fitting(prod(), loc(max_volume_m3=10)) == 4
    assert max_units_fitting(prod(stackable=False), loc(max_volume_m3=10)) == 2


def test_storage_class_and_handling():
    assert "storage_class" in check_placement(prod(storage_requirements="cold"), loc(), 1)
    assert check_placement(prod(storage_requirements="cold"), loc(storage_class="cold"), 1) == []
    assert "handling" in check_placement(prod(handling_type="pallet"), loc(), 1)
    assert "handling" in check_placement(prod(handling_type="crane"), loc(), 1)  # unknown -> safe default
    assert "handling" not in check_placement(prod(handling_type=""), loc(), 1)


def test_unknown_capacity_and_unavailable_are_infeasible():
    assert "capacity_unknown" in check_placement(prod(), loc(max_weight_kg=np.nan), 1)
    assert "unavailable" in check_placement(prod(), loc(is_available=False), 1)


def test_insufficient_capacity_matrix():
    products = pd.DataFrame([prod(sku="small").to_dict(), prod(sku="heavy", weight_kg=200).to_dict()])
    locations = pd.DataFrame([loc(location_id="L1").to_dict(), loc(location_id="L2", max_weight_kg=500).to_dict()])
    feas = feasibility_matrix(products, np.array([1.0, 1.0]), locations)
    assert feas.tolist() == [[True, True], [False, True]]
