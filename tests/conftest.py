import sys
from pathlib import Path

import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from warehouse_optimizer.data.loaders import Dataset  # noqa: E402
from warehouse_optimizer.data.validators import validate_dataset  # noqa: E402


def text_frame(rows: list[dict]) -> pd.DataFrame:
    df = pd.DataFrame(rows)
    return df.astype(str).replace({"nan": "", "None": ""})


def product(sku, length=0.3, width=0.2, height=0.2, weight=2.0, **kw):
    row = {"sku": sku, "product_name": f"Ürün {sku}", "length_m": length, "width_m": width, "height_m": height,
           "weight_kg": weight, "stackable": "true", "product_family": "F", "storage_requirements": "standard",
           "handling_type": "manual"}
    row.update(kw)
    return row


def location(loc_id, aisle, x, y, **kw):
    row = {"location_id": loc_id, "zone": "Z", "aisle_id": aisle, "x": x, "y": y, "z": 0.0, "location_type": "shelf",
           "max_weight_kg": 200.0, "max_volume_m3": 0.8, "max_length_m": 1.2, "max_width_m": 0.8,
           "max_height_m": 0.9, "is_pickable": "true", "is_available": "true", "is_fixed": "false",
           "storage_class": "standard"}
    row.update(kw)
    return row


AISLES = [{"aisle_id": "A1", "x_center": 2.0, "y_start": 0.0, "y_end": 10.0},
          {"aisle_id": "A2", "x_center": 8.0, "y_start": 0.0, "y_end": 10.0}]
DOCK = (0.0, -2.0)


def small_locations(**overrides):
    """Two aisles (x=2, x=8), three bays each (y=2,5,8), racks on the left side (x-1)."""
    rows = []
    for aisle, xc in (("A1", 2.0), ("A2", 8.0)):
        for y in (2.0, 5.0, 8.0):
            loc_id = f"{aisle}-{int(y)}"
            rows.append(location(loc_id, aisle, xc - 1.0, y, **overrides.get(loc_id, {})))
    return rows


def make_dataset(products, orders, locations, inventory, aisles=AISLES, dock=DOCK) -> Dataset:
    tables = {"products": text_frame(products), "order_lines": text_frame(orders),
              "locations": text_frame(locations), "inventory": text_frame(inventory)}
    if aisles is not None:
        tables["aisles"] = text_frame(aisles)
    return Dataset(tables=tables, dock_xy=dock, source_label="test")


@pytest.fixture
def small_dataset():
    products = [product("P1"), product("P2"), product("P3")]
    # P1 is popular but sits far away (A2-8); P3 is unpopular and sits close (A1-2).
    orders = []
    for i in range(10):
        orders.append({"order_id": f"O{i}", "order_date": f"2026-09-{i + 1:02d}", "sku": "P1", "quantity": 1})
    orders.append({"order_id": "O20", "order_date": "2026-09-20", "sku": "P2", "quantity": 1})
    orders.append({"order_id": "O21", "order_date": "2026-09-21", "sku": "P3", "quantity": 1})
    inventory = [{"sku": "P1", "location_id": "A2-8", "current_quantity": 5},
                 {"sku": "P2", "location_id": "A2-5", "current_quantity": 5},
                 {"sku": "P3", "location_id": "A1-2", "current_quantity": 5}]
    return make_dataset(products, orders, small_locations(), inventory)


@pytest.fixture
def validated(small_dataset):
    return validate_dataset(small_dataset)
