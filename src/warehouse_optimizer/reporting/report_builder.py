"""Assemble every downloadable report from a PipelineResult."""
from __future__ import annotations

import pandas as pd

from ..pipeline import (PipelineResult, assumptions_and_limitations, method_comparison_table, placement_frame,
                        report_metadata)
from .exports import kpi_frame, localize

REPORT_TITLES = {
    "abc": "ABC analizi",
    "movement": "Ürün hareket analizi",
    "data_quality": "Veri kalite raporu",
    "current_placement": "Mevcut yerleşim",
    "proposed_placement": "Önerilen yerleşim",
    "move_plan": "Taşıma planı",
    "route_comparison": "Sipariş bazında rota karşılaştırması",
    "kpi": "Önce-Sonra KPI raporu",
    "method_comparison": "Yöntem karşılaştırması",
    "constraints": "Kısıt ihlalleri ve atanamayan ürünler",
    "assumptions": "Varsayımlar ve sınırlamalar",
}


def build_reports(result: PipelineResult, method: str | None = None) -> dict[str, pd.DataFrame]:
    method = method or result.selected_method
    reports: dict[str, pd.DataFrame] = {}
    reports["data_quality"] = localize(result.validation.issues)
    if not result.ok:
        reports["assumptions"] = pd.DataFrame({"Madde": assumptions_and_limitations(result)})
        return reports

    sku_table = result.sku_table(method)
    reports["abc"] = localize(sku_table[["rank", "sku", "product_name", "metric_value", "share", "cumulative_share",
                                         "abc_class", "current_location", "current_dock_distance_m",
                                         "proposed_location", "proposed_dock_distance_m"]])
    reports["movement"] = localize(sku_table[["sku", "product_name", "product_family", "quantity", "order_lines",
                                              "orders", "active_days", "lines_per_day", "abc_class"]])
    dock = result.locations.set_index("location_id")["dock_distance_m"]
    slot = result.slotting[method]
    products = result.validation.tables["products"]
    reports["current_placement"] = localize(placement_frame(slot.placement_current, products, result.abc.table, dock))
    reports["proposed_placement"] = localize(placement_frame(slot.placement_proposed, products, result.abc.table,
                                                             dock))
    plan = result.move_plans[method]
    plan_cols = ["sequence", "sku", "product_name", "abc_class", "from_location", "to_location", "move_type",
                 "order_lines", "current_dock_distance_m", "proposed_dock_distance_m", "estimated_travel_saving_m",
                 "reason", "constraint_check"]
    reports["move_plan"] = localize(plan[plan_cols] if not plan.empty else pd.DataFrame(columns=plan_cols))
    comparison = result.comparisons[method]
    reports["route_comparison"] = localize(comparison.per_order)
    reports["kpi"] = kpi_frame(comparison.summary)
    reports["method_comparison"] = method_comparison_table(result)

    constraint_rows = []
    for _, r in slot.unassignable.iterrows():
        constraint_rows.append({"Tür": "Atanamayan ürün", "SKU": r["sku"], "Lokasyon": "", "Açıklama": r["reason"]})
    for _, r in slot.not_movable.iterrows():
        constraint_rows.append({"Tür": "Taşınamaz ürün", "SKU": r["sku"], "Lokasyon": r["current_locations"],
                                "Açıklama": r["reason"]})
    issues = result.validation.issues
    for _, r in issues[issues["message"].str.startswith("Mevcut yerleşim kısıt ihlali")].iterrows():
        constraint_rows.append({"Tür": "Mevcut yerleşim ihlali", "SKU": r["value"].split(" @ ")[0],
                                "Lokasyon": r["value"].split(" @ ")[-1], "Açıklama": r["message"]})
    if not plan.empty:
        for _, r in plan[plan["constraint_check"] != "Geçti"].iterrows():
            constraint_rows.append({"Tür": "Öneri ihlali", "SKU": r["sku"], "Lokasyon": r["to_location"],
                                    "Açıklama": r["constraint_check"]})
    for _, r in comparison.excluded.iterrows():
        constraint_rows.append({"Tür": "Rota dışı sipariş", "SKU": "", "Lokasyon": "",
                                "Açıklama": f"{r['order_id']}: {r['reason']}"})
    reports["constraints"] = pd.DataFrame(constraint_rows, columns=["Tür", "SKU", "Lokasyon", "Açıklama"])
    reports["assumptions"] = pd.DataFrame({"Madde": assumptions_and_limitations(result) + comparison.notes +
                                           slot.notes})
    return reports


def report_bundle_metadata(result: PipelineResult, method: str | None = None) -> dict:
    if not result.ok:
        return {"Durum": "Analiz tamamlanamadı", "Hatalar": "; ".join(result.errors)}
    return report_metadata(result, method)
