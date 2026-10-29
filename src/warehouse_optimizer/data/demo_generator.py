"""Deterministic synthetic demo dataset.

THE DATA PRODUCED HERE IS SYNTHETIC. It exists so that the whole workflow
(validation, ABC, constraints, slotting, routing, before/after simulation)
can be exercised without real warehouse data. Nothing derived from it should
be presented as a measured result.

Layout (metres):
    * 8 parallel aisles running along Y, front cross-aisle at y=1, back at y=19.5
    * A01-A06: two-level shelving, A07: floor pallet positions, A08: cold room shelving
    * one dock (shipping point) in front of the warehouse
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from .loaders import Dataset

DEMO_SEED = 42
N_AISLES = 8
BAYS_PER_SIDE = 10
AISLE_SPACING = 6.0
FIRST_AISLE_X = 4.0
RACK_OFFSET = 1.5
BAY_PITCH = 1.4
FIRST_BAY_Y = 3.0
FRONT_Y = 1.0
BACK_Y = 19.5
DOCK_XY = (10.0, -1.0)
END_DATE = pd.Timestamp("2026-09-30")

FAMILIES = ["Temizlik", "Gıda", "Kozmetik", "Kırtasiye", "Elektronik", "Ev Gereçleri"]


def _aisle_id(i: int) -> str:
    return f"A{i + 1:02d}"


def _build_locations(rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    rows = []
    aisles = []
    for a in range(N_AISLES):
        aisle = _aisle_id(a)
        x_center = FIRST_AISLE_X + a * AISLE_SPACING
        aisles.append({"aisle_id": aisle, "x_center": x_center, "y_start": FRONT_Y, "y_end": BACK_Y})
        if a == 6:
            kind, levels, storage = "pallet", [0.0], "standard"
        elif a == 7:
            kind, levels, storage = "shelf", [0.0], "cold"
        else:
            kind, levels, storage = "shelf", [0.0, 1.2], "standard"
        for side, sx in (("L", -1), ("R", 1)):
            for bay in range(BAYS_PER_SIDE):
                for level_idx, z in enumerate(levels):
                    if kind == "pallet":
                        cap = dict(max_length_m=1.3, max_width_m=1.1, max_height_m=1.8, max_weight_kg=1000.0)
                    elif level_idx == 0:
                        cap = dict(max_length_m=1.2, max_width_m=0.8, max_height_m=0.9, max_weight_kg=250.0)
                    else:
                        cap = dict(max_length_m=1.2, max_width_m=0.8, max_height_m=0.6, max_weight_kg=120.0)
                    cap["max_volume_m3"] = round(cap["max_length_m"] * cap["max_width_m"] * cap["max_height_m"], 4)
                    rows.append({
                        "location_id": f"{aisle}-{side}{bay + 1:02d}-{level_idx + 1}",
                        "zone": "COLD" if storage == "cold" else ("PALLET" if kind == "pallet" else "MAIN"),
                        "aisle_id": aisle,
                        "x": x_center + sx * RACK_OFFSET,
                        "y": FIRST_BAY_Y + bay * BAY_PITCH,
                        "z": z,
                        "location_type": kind,
                        **cap,
                        "is_pickable": True,
                        "is_available": True,
                        "is_fixed": False,
                        "storage_class": storage,
                    })
    locations = pd.DataFrame(rows)
    unavailable = rng.choice(len(locations), size=int(len(locations) * 0.04), replace=False)
    locations.loc[unavailable, "is_available"] = False
    return locations, pd.DataFrame(aisles)


def _build_products(rng: np.random.Generator, n_skus: int) -> pd.DataFrame:
    rows = []
    for i in range(n_skus):
        sku = f"SKU-{i + 1:04d}"
        if i < 6:
            handling, storage = "pallet", "standard"
            dims = (1.2, 1.0, rng.uniform(1.0, 1.6))
            weight = rng.uniform(150, 600)
        elif i < 12:
            handling, storage = "manual", "cold"
            dims = tuple(rng.uniform(0.15, 0.45, 3))
            weight = rng.uniform(0.5, 8)
        else:
            handling, storage = "manual", "standard"
            dims = tuple(rng.uniform(0.08, 0.55, 3))
            weight = rng.uniform(0.2, 22)
        rows.append({
            "sku": sku,
            "product_name": f"Demo Ürün {i + 1}",
            "length_m": round(float(dims[0]), 3),
            "width_m": round(float(dims[1]), 3),
            "height_m": round(float(dims[2]), 3),
            "weight_kg": round(float(weight), 2),
            "stackable": bool(handling == "pallet" or rng.random() > 0.15),
            "product_family": FAMILIES[int(rng.integers(0, len(FAMILIES)))],
            "storage_requirements": storage,
            "handling_type": handling,
        })
    return pd.DataFrame(rows)


def _place_inventory(rng: np.random.Generator, products: pd.DataFrame, locations: pd.DataFrame) -> pd.DataFrame:
    from ..optimization.constraints import constraint_matrices, max_units_fitting

    usable = locations[locations["is_available"]].copy()
    free = set(usable["location_id"])
    order = rng.permutation(len(products))
    rows = []
    multi_location = set(products["sku"].iloc[order[:4]])  # a few SKUs held in two locations
    for idx in order:
        prod = products.iloc[[idx]]
        candidates = usable[usable["location_id"].isin(free)]
        # Feasibility with quantity 1, then choose a quantity that fits the chosen location.
        mats = constraint_matrices(prod, np.array([1.0]), candidates)
        ok = np.ones(len(candidates), dtype=bool)
        for m in mats.values():
            ok &= ~m[0]
        pool = candidates[ok]
        if pool.empty:
            continue
        n_locs = 2 if prod["sku"].iloc[0] in multi_location and len(pool) > 1 else 1
        chosen = pool.iloc[rng.choice(len(pool), size=n_locs, replace=False)]
        for _, loc in chosen.iterrows():
            max_units = max_units_fitting(prod.iloc[0], loc)
            qty = int(rng.integers(max(1, int(max_units * 0.3)), max(2, int(max_units * 0.8)) + 1))
            qty = max(1, min(qty, max_units))
            rows.append({"sku": prod["sku"].iloc[0], "location_id": loc["location_id"], "current_quantity": qty})
            free.discard(loc["location_id"])
    return pd.DataFrame(rows)


def _build_orders(rng: np.random.Generator, products: pd.DataFrame, n_orders: int) -> pd.DataFrame:
    n = len(products)
    # Zipf-like popularity over a random permutation, independent of the current placement.
    ranks = rng.permutation(n) + 1
    weights = 1.0 / ranks ** 1.1
    weights[np.argsort(ranks)[-5:]] = 0.0  # five SKUs without any movement
    weights = weights / weights.sum()
    start = END_DATE - pd.Timedelta(days=119)
    rows = []
    for o in range(n_orders):
        order_id = f"SO-{10001 + o}"
        date = start + pd.Timedelta(days=int(rng.integers(0, 120)))
        n_lines = int(min(1 + rng.geometric(0.45), 8))
        skus = rng.choice(products["sku"].to_numpy(), size=n_lines, replace=False, p=weights)
        for sku in skus:
            rows.append({"order_id": order_id, "order_date": date.date().isoformat(), "sku": sku,
                         "quantity": int(rng.integers(1, 11)), "movement_type": "outbound"})
    orders = pd.DataFrame(rows)
    # A handful of returns / cancellations that must NOT count as outbound picks.
    sample = orders.sample(n=15, random_state=int(rng.integers(0, 1_000_000)))
    extra = sample.copy()
    extra["movement_type"] = ["return"] * 10 + ["cancel"] * 5
    return pd.concat([orders, extra], ignore_index=True)


def generate_demo_dataset(seed: int = DEMO_SEED, n_skus: int = 80, n_orders: int = 400) -> Dataset:
    rng = np.random.default_rng(seed)
    locations, aisles = _build_locations(rng)
    products = _build_products(rng, n_skus)
    inventory = _place_inventory(rng, products, locations)
    # Fixed locations: a few occupied pick faces that must not change.
    occupied = inventory["location_id"].drop_duplicates().sort_values().to_numpy()
    fixed = rng.choice(occupied, size=4, replace=False)
    locations.loc[locations["location_id"].isin(fixed), "is_fixed"] = True
    orders = _build_orders(rng, products, n_orders)

    def as_text(df: pd.DataFrame) -> pd.DataFrame:
        out = df.copy()
        for col in out.columns:
            if out[col].dtype == bool:
                out[col] = out[col].map({True: "true", False: "false"})
        return out.astype(str)

    return Dataset(
        tables={
            "products": as_text(products),
            "order_lines": as_text(orders),
            "locations": as_text(locations),
            "inventory": as_text(inventory),
            "aisles": as_text(aisles),
        },
        is_synthetic=True,
        source_label=f"Sentetik demo verisi (seed={seed})",
        dock_xy=DOCK_XY,
        notes=["Bu veri seti sentetiktir; gerçek bir depoyu temsil etmez."],
    )
