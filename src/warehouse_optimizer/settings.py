"""Settings loading (YAML defaults + user overrides)."""
from __future__ import annotations

import copy
from pathlib import Path

import yaml

DEFAULT_SETTINGS_PATH = Path(__file__).resolve().parents[2] / "config" / "default_settings.yaml"

_FALLBACK = {
    "units": {"dimension": "m", "weight": "kg"},
    "analysis": {"metric": "order_lines", "period_days": 90, "a_share": 0.80, "b_share": 0.15},
    "geometry": {"distance_mode": "graph", "dock_x": None, "dock_y": None},
    "slotting": {
        "method": "hybrid", "max_moves": 30,
        "class_based": {"class_weight_a": 3.0, "class_weight_b": 2.0, "class_weight_c": 1.0, "min_gain": 1.0},
        "hybrid": {"w_travel": 1.0, "w_height": 0.5, "w_family": 0.0, "w_fit": 2.0, "move_cost_m": 30.0},
        "handling_compatibility": {"manual": ["shelf", "bin", "flow_rack", "pallet", "floor"],
                                   "pallet": ["pallet", "floor"], "forklift": ["pallet", "floor"]},
    },
    "operations": {"walking_speed_m_s": 1.0, "pick_time_s_per_stop": 0, "daily_orders": None,
                   "operating_days": None, "hourly_labor_cost": None, "use_two_opt": True, "max_orders": 3000},
}


def _merge(base: dict, override: dict) -> dict:
    out = copy.deepcopy(base)
    for key, value in (override or {}).items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _merge(out[key], value)
        else:
            out[key] = value
    return out


def load_settings(path: Path | str | None = None) -> dict:
    path = Path(path) if path else DEFAULT_SETTINGS_PATH
    data = {}
    if path.exists():
        with open(path, encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
    return _merge(_FALLBACK, data)


def merge_settings(base: dict, override: dict) -> dict:
    return _merge(base, override)
