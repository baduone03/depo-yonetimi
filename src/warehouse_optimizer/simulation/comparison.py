"""Before / after simulation on the same orders.

For each order the pick tour is computed twice with the same routing model,
start/end point and parameters: once with the current placement and once
with the proposed placement. Results are SIMULATED distances on a model of
the warehouse, not measurements.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..routing.picking_routes import route_locations


@dataclass
class OperationParams:
    walking_speed_m_s: float = 1.0
    pick_time_s_per_stop: float | None = None  # None / 0 -> unknown, only walking time is computed
    daily_orders: float | None = None  # None -> derived from the analysed period
    operating_days: int | None = None  # None -> no period projection
    hourly_labor_cost: float | None = None  # None -> no cost estimate
    use_two_opt: bool = True
    max_orders: int = 3000


@dataclass
class ComparisonResult:
    per_order: pd.DataFrame
    summary: dict
    excluded: pd.DataFrame
    notes: list[str] = field(default_factory=list)


def improvement_pct(current: float, proposed: float) -> float:
    """((current - proposed) / current) * 100; NaN (undefined) when current is 0 or not finite."""
    if current is None or not np.isfinite(current) or current == 0:
        return math.nan
    return (current - proposed) / current * 100.0


def resolve_pick_location(placement: dict[str, list[str]], dock_distance: pd.Series) -> dict[str, str]:
    """SKU -> the pick location used for routing (closest to the dock if several, ties by id)."""
    chosen = {}
    for sku, locs in placement.items():
        if not locs:
            continue
        chosen[sku] = min(locs, key=lambda l: (dock_distance.get(l, math.inf)
                                               if not pd.isna(dock_distance.get(l, math.nan)) else math.inf, l))
    return chosen


def compare_placements(lines: pd.DataFrame, placement_current: dict[str, list[str]],
                       placement_proposed: dict[str, list[str]], model, dock_distance: pd.Series,
                       params: OperationParams) -> ComparisonResult:
    notes: list[str] = []
    excluded_rows: list[dict] = []
    cur_map = resolve_pick_location(placement_current, dock_distance)
    new_map = resolve_pick_location(placement_proposed, dock_distance)

    if lines.empty:
        summary = _summary(pd.DataFrame(), params, 0, 0)
        summary.pop("_notes")
        return ComparisonResult(pd.DataFrame(), summary, pd.DataFrame(columns=["order_id", "reason"]),
                                ["Analiz döneminde çıkış siparişi yok."])

    order_dates = lines.groupby("order_id")["order_date"].min().sort_values(kind="mergesort")
    order_ids = order_dates.index.to_list()
    if len(order_ids) > params.max_orders:
        order_ids = sorted(order_dates.iloc[-params.max_orders:].index)
        notes.append(f"Performans için en güncel {params.max_orders} sipariş simüle edildi "
                     f"(toplam {len(order_dates)}).")
    lines = lines[lines["order_id"].isin(set(order_ids))]

    no_location = ~lines["sku"].isin(cur_map.keys())
    if no_location.any():
        notes.append(f"{int(no_location.sum())} sipariş satırının SKU'su için toplama lokasyonu yok; bu satırlar "
                     "her iki senaryoda da rotaya katılmadı.")

    rows = []
    for order_id, group in lines[~no_location].groupby("order_id", sort=True):
        skus = sorted(group["sku"].unique())
        cur = route_locations(model, [cur_map[s] for s in skus], params.use_two_opt)
        new = route_locations(model, [new_map.get(s, cur_map[s]) for s in skus], params.use_two_opt)
        if not cur.valid or not new.valid:
            excluded_rows.append({"order_id": order_id,
                                  "reason": "Ulaşılamayan lokasyon: " + ", ".join(sorted(set(cur.unreachable +
                                                                                              new.unreachable)))})
            continue
        rows.append({
            "order_id": order_id,
            "order_date": group["order_date"].min(),
            "lines": len(skus),
            "stops_current": cur.n_stops,
            "stops_proposed": new.n_stops,
            "distance_current_m": cur.distance_m,
            "distance_proposed_m": new.distance_m,
        })
    per_order = pd.DataFrame(rows, columns=["order_id", "order_date", "lines", "stops_current", "stops_proposed",
                                            "distance_current_m", "distance_proposed_m"])
    if not per_order.empty:
        per_order["difference_m"] = per_order["distance_current_m"] - per_order["distance_proposed_m"]
        per_order["change_pct"] = [improvement_pct(c, p) for c, p in
                                   zip(per_order["distance_current_m"], per_order["distance_proposed_m"])]
    excluded = pd.DataFrame(excluded_rows, columns=["order_id", "reason"])
    if not excluded.empty:
        notes.append(f"{len(excluded)} sipariş ulaşılamayan lokasyon nedeniyle karşılaştırma dışı bırakıldı.")

    period_days = max(int((lines["order_date"].max() - lines["order_date"].min()).days) + 1, 1)
    summary = _summary(per_order, params, period_days, len(order_dates))
    return ComparisonResult(per_order, summary, excluded, notes + summary.pop("_notes"))


def _summary(per_order: pd.DataFrame, params: OperationParams, period_days: int, total_orders: int) -> dict:
    notes: list[str] = []
    n = len(per_order)
    s: dict = {"orders_compared": n, "_notes": notes}
    if n == 0:
        for key in ("total_current_m", "total_proposed_m", "mean_current_m", "mean_proposed_m", "median_current_m",
                    "median_proposed_m", "difference_m", "improvement_pct", "stops_current", "stops_proposed",
                    "time_current_h", "time_proposed_h", "time_difference_h"):
            s[key] = math.nan
        return s
    cur, new = per_order["distance_current_m"], per_order["distance_proposed_m"]
    s.update({
        "total_current_m": float(cur.sum()),
        "total_proposed_m": float(new.sum()),
        "mean_current_m": float(cur.mean()),
        "mean_proposed_m": float(new.mean()),
        "median_current_m": float(cur.median()),
        "median_proposed_m": float(new.median()),
        "difference_m": float(cur.sum() - new.sum()),
        "improvement_pct": improvement_pct(float(cur.sum()), float(new.sum())),
        "stops_current": int(per_order["stops_current"].sum()),
        "stops_proposed": int(per_order["stops_proposed"].sum()),
        "orders_improved": int((per_order["difference_m"] > 1e-9).sum()),
        "orders_worse": int((per_order["difference_m"] < -1e-9).sum()),
    })
    speed = params.walking_speed_m_s
    pick = params.pick_time_s_per_stop if params.pick_time_s_per_stop else 0.0
    if not params.pick_time_s_per_stop:
        notes.append("Lokasyon başına toplama süresi girilmedi; süreler yalnızca yürüme süresidir.")
    s["time_includes_pick_time"] = bool(params.pick_time_s_per_stop)
    s["time_current_h"] = (s["total_current_m"] / speed + s["stops_current"] * pick) / 3600.0
    s["time_proposed_h"] = (s["total_proposed_m"] / speed + s["stops_proposed"] * pick) / 3600.0
    s["time_difference_h"] = s["time_current_h"] - s["time_proposed_h"]

    # Projection to an operating horizon (estimate).
    daily = params.daily_orders
    if daily is None and period_days > 0:
        daily = total_orders / period_days
        s["daily_orders_source"] = "veriden türetildi"
    else:
        s["daily_orders_source"] = "kullanıcı girdisi"
    s["daily_orders"] = daily
    saving_per_order_h = s["time_difference_h"] / n
    s["time_saving_per_order_s"] = saving_per_order_h * 3600.0
    if params.operating_days:
        s["projected_hours_saved"] = saving_per_order_h * daily * params.operating_days
        s["projected_distance_saved_km"] = (s["difference_m"] / n) * daily * params.operating_days / 1000.0
    else:
        s["projected_hours_saved"] = math.nan
        s["projected_distance_saved_km"] = math.nan
        notes.append("Operasyon günü sayısı girilmedi; dönemsel projeksiyon hesaplanmadı.")
    if params.hourly_labor_cost and params.operating_days:
        s["projected_labor_cost_saved"] = s["projected_hours_saved"] * params.hourly_labor_cost
    else:
        s["projected_labor_cost_saved"] = math.nan
        if not params.hourly_labor_cost:
            notes.append("Saatlik işçilik maliyeti girilmedi; maliyet tahmini hesaplanmadı.")
    return s
