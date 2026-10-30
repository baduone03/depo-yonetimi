"""Physical and operational placement constraints.

A SKU is always placed as a whole (its full current quantity moves to the
target location). The checks are deliberately conservative: when a value
needed for a check is unknown, the placement is treated as infeasible.

Checks (code -> meaning):
    capacity_unknown   location capacity / dimension data missing
    unavailable        location not available
    dimension          a single unit does not fit (horizontal rotation allowed,
                       no tipping: unit height must fit max_height_m)
    weight             quantity * unit weight > max_weight_kg
    volume             quantity * unit volume > max_volume_m3
    packing            quantity does not fit geometrically (units per layer *
                       layers; non-stackable products get a single layer)
    storage_class      storage_requirements != location storage_class
    handling           handling_type not compatible with location_type
"""
from __future__ import annotations

import numpy as np
import pandas as pd

EPS = 1e-9

CONSTRAINT_LABELS = {
    "capacity_unknown": "Lokasyon kapasitesi bilinmiyor",
    "unavailable": "Lokasyon kullanılamaz",
    "dimension": "Ürün boyutu lokasyona sığmıyor",
    "weight": "Ağırlık kapasitesi aşılıyor",
    "volume": "Hacim kapasitesi aşılıyor",
    "packing": "Miktar geometrik olarak sığmıyor (istif/katman)",
    "storage_class": "Depolama koşulu uyumsuz",
    "handling": "Elleçleme tipi lokasyon tipiyle uyumsuz",
}

DEFAULT_HANDLING_COMPATIBILITY = {
    "manual": ["shelf", "bin", "flow_rack", "pallet", "floor"],
    "pallet": ["pallet", "floor"],
    "forklift": ["pallet", "floor"],
}

_CAPACITY_COLS = ["max_weight_kg", "max_volume_m3", "max_length_m", "max_width_m", "max_height_m"]


def _col(df: pd.DataFrame, name: str, default) -> np.ndarray:
    if name in df.columns:
        return df[name].to_numpy()
    return np.full(len(df), default)


def constraint_matrices(products: pd.DataFrame, quantities: np.ndarray, locations: pd.DataFrame,
                        handling_compatibility: dict | None = None) -> dict[str, np.ndarray]:
    """Return {code: bool matrix (S x L)} where True means the constraint is VIOLATED.

    `products` rows are aligned with `quantities`; both define the S axis.
    """
    compat = DEFAULT_HANDLING_COMPATIBILITY if handling_compatibility is None else handling_compatibility
    q = np.asarray(quantities, dtype=float)[:, None]
    p_len = products["length_m"].to_numpy(float)[:, None]
    p_wid = products["width_m"].to_numpy(float)[:, None]
    p_hgt = products["height_m"].to_numpy(float)[:, None]
    p_wgt = products["weight_kg"].to_numpy(float)[:, None]
    p_vol = (products["length_m"] * products["width_m"] * products["height_m"]).to_numpy(float)[:, None]
    p_stack = _col(products, "stackable", True).astype(bool)[:, None]

    l_len = locations["max_length_m"].to_numpy(float)[None, :]
    l_wid = locations["max_width_m"].to_numpy(float)[None, :]
    l_hgt = locations["max_height_m"].to_numpy(float)[None, :]
    l_wgt = locations["max_weight_kg"].to_numpy(float)[None, :]
    l_vol = locations["max_volume_m3"].to_numpy(float)[None, :]

    shape = (len(products), len(locations))
    unknown = np.broadcast_to(locations[_CAPACITY_COLS].isna().any(axis=1).to_numpy()[None, :], shape)
    unavailable = np.broadcast_to(~_col(locations, "is_available", True).astype(bool)[None, :], shape)

    with np.errstate(invalid="ignore", divide="ignore"):
        fit_straight = (p_len <= l_len + EPS) & (p_wid <= l_wid + EPS)
        fit_rotated = (p_wid <= l_len + EPS) & (p_len <= l_wid + EPS)
        dimension = ~((fit_straight | fit_rotated) & (p_hgt <= l_hgt + EPS))
        weight = q * p_wgt > l_wgt + EPS
        volume = q * p_vol > l_vol + EPS
        per_layer = np.maximum(np.floor((l_len + EPS) / p_len) * np.floor((l_wid + EPS) / p_wid),
                               np.floor((l_len + EPS) / p_wid) * np.floor((l_wid + EPS) / p_len))
        layers = np.where(p_stack, np.floor((l_hgt + EPS) / p_hgt), 1.0)
        packing = q > np.nan_to_num(per_layer * layers, nan=0.0) + EPS

    # NaN comparisons evaluate to False above; unknown capacity is handled by `unknown`.
    dimension = dimension & ~unknown
    weight = weight & ~unknown
    volume = volume & ~unknown
    packing = packing & ~unknown

    req = _col(products, "storage_requirements", "standard").astype(str)
    req = np.where(req == "", "standard", req)
    cls = _col(locations, "storage_class", "standard").astype(str)
    cls = np.where(cls == "", "standard", cls)
    storage = req[:, None] != cls[None, :]

    handling_types = _col(products, "handling_type", "").astype(str)
    loc_types = _col(locations, "location_type", "").astype(str)
    handling = np.zeros(shape, dtype=bool)
    for i, h in enumerate(handling_types):
        if h == "":
            continue
        allowed = set(compat.get(h, []))  # unknown handling type -> nothing allowed (safe default)
        handling[i, :] = ~np.isin(loc_types, list(allowed))

    return {
        "capacity_unknown": np.array(unknown),
        "unavailable": np.array(unavailable),
        "dimension": dimension,
        "weight": weight,
        "volume": volume,
        "packing": packing,
        "storage_class": storage,
        "handling": handling,
    }


def feasibility_matrix(products: pd.DataFrame, quantities: np.ndarray, locations: pd.DataFrame,
                       handling_compatibility: dict | None = None) -> np.ndarray:
    matrices = constraint_matrices(products, quantities, locations, handling_compatibility)
    violated = np.zeros((len(products), len(locations)), dtype=bool)
    for m in matrices.values():
        violated |= m
    return ~violated


def check_placement(product: pd.Series, location: pd.Series, quantity: float,
                    handling_compatibility: dict | None = None) -> list[str]:
    """Return the violated constraint codes for one SKU / location / quantity."""
    p = product.to_frame().T
    loc = location.to_frame().T
    for col in _CAPACITY_COLS:
        loc[col] = pd.to_numeric(loc[col], errors="coerce")
    for col in ("length_m", "width_m", "height_m", "weight_kg"):
        p[col] = pd.to_numeric(p[col], errors="coerce")
    matrices = constraint_matrices(p, np.array([quantity]), loc, handling_compatibility)
    return [code for code, m in matrices.items() if bool(m[0, 0])]


def check_current_placement(products: pd.DataFrame, locations: pd.DataFrame, inventory: pd.DataFrame,
                            handling_compatibility: dict | None = None) -> list[dict]:
    """Check every inventory record against the physical constraints of its location.

    `capacity_unknown` is not reported here (it is a data-quality warning already).
    """
    if inventory.empty:
        return []
    merged = (inventory
              .merge(products.drop(columns=["_row"], errors="ignore"), on="sku", how="inner")
              .merge(locations.drop(columns=["_row"], errors="ignore"), on="location_id", how="inner",
                     suffixes=("", "_loc")))
    if merged.empty:
        return []
    prod_cols = [c for c in products.columns if c in merged.columns]
    loc_cols = [c for c in locations.columns if c in merged.columns]
    results = []
    p_frame = merged[prod_cols].reset_index(drop=True)
    l_frame = merged[loc_cols].reset_index(drop=True)
    qty = merged["current_quantity"].to_numpy(float)
    # Evaluate the diagonal only (row i of inventory against its own location).
    for i in range(len(merged)):
        mats = constraint_matrices(p_frame.iloc[[i]], qty[[i]], l_frame.iloc[[i]], handling_compatibility)
        for code, m in mats.items():
            if code == "capacity_unknown" or not bool(m[0, 0]):
                continue
            results.append({
                "row": merged["_row"].iloc[i] if "_row" in merged else None,
                "field": code,
                "sku": merged["sku"].iloc[i],
                "location_id": merged["location_id"].iloc[i],
                "message": CONSTRAINT_LABELS[code],
            })
    return results


def max_units_fitting(product: pd.Series, location: pd.Series) -> int:
    """Largest quantity of `product` that satisfies the physical checks of `location` (0 if none)."""
    length, width, height = float(product["length_m"]), float(product["width_m"]), float(product["height_m"])
    max_l, max_w, max_h = float(location["max_length_m"]), float(location["max_width_m"]), float(location["max_height_m"])
    if any(np.isnan(v) for v in (max_l, max_w, max_h, float(location["max_weight_kg"]),
                                 float(location["max_volume_m3"]))):
        return 0
    if height > max_h + EPS:
        return 0
    per_layer = max(np.floor((max_l + EPS) / length) * np.floor((max_w + EPS) / width),
                    np.floor((max_l + EPS) / width) * np.floor((max_w + EPS) / length))
    layers = np.floor((max_h + EPS) / height) if bool(product.get("stackable", True)) else 1.0
    by_weight = np.floor((float(location["max_weight_kg"]) + EPS) / float(product["weight_kg"]))
    by_volume = np.floor((float(location["max_volume_m3"]) + EPS) / (length * width * height))
    return int(max(0, min(per_layer * layers, by_weight, by_volume)))
