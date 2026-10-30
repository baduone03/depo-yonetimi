"""End-to-end analysis pipeline, independent of the UI.

dataset + settings -> validation -> movement/ABC -> geometry/distances ->
slotting (both methods) -> before/after simulation (both methods).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .analytics.abc_analysis import ABCResult, classify_abc
from .analytics.movement_analysis import AnalysisPeriod, lines_in_period, resolve_period, sku_movement
from .data.loaders import Dataset
from .data.validators import ValidationReport, validate_dataset
from .layout.warehouse_model import WarehouseGeometry, build_geometry
from .optimization.scoring import ClassBasedWeights, HybridWeights
from .optimization.slotting_engine import (METHOD_LABELS, SlottingConfig, SlottingResult, run_slotting,
                                           verify_moves)
from .routing.warehouse_graph import GraphDistanceModel, ManhattanDistanceModel, location_dock_distances
from .simulation.comparison import ComparisonResult, OperationParams, compare_placements, resolve_pick_location

METHODS = ("class_based", "hybrid")


@dataclass
class PipelineResult:
    settings: dict
    dataset: Dataset
    validation: ValidationReport
    errors: list[str] = field(default_factory=list)
    period: AnalysisPeriod | None = None
    movement: pd.DataFrame | None = None
    abc: ABCResult | None = None
    geometry: WarehouseGeometry | None = None
    model: object | None = None
    locations: pd.DataFrame | None = None  # typed locations + dock_distance_m
    slotting: dict[str, SlottingResult] = field(default_factory=dict)
    move_plans: dict[str, pd.DataFrame] = field(default_factory=dict)
    comparisons: dict[str, ComparisonResult] = field(default_factory=dict)
    selected_method: str = "hybrid"
    period_lines: pd.DataFrame | None = None

    @property
    def ok(self) -> bool:
        return not self.errors

    @property
    def is_synthetic(self) -> bool:
        return self.dataset.is_synthetic

    @property
    def distance_is_estimate(self) -> bool:
        return bool(self.model is not None and self.model.is_estimate)

    def sku_table(self, method: str | None = None) -> pd.DataFrame:
        """ABC table enriched with current / proposed location and distances."""
        method = method or self.selected_method
        table = self.abc.table.copy()
        products = self.validation.tables["products"].set_index("sku")
        table["product_name"] = table["sku"].map(products["product_name"])
        table["product_family"] = table["sku"].map(products["product_family"])
        dock = self.locations.set_index("location_id")["dock_distance_m"]
        slot = self.slotting.get(method)
        cur = resolve_pick_location(slot.placement_current, dock) if slot else {}
        new = resolve_pick_location(slot.placement_proposed, dock) if slot else {}
        table["current_location"] = table["sku"].map(cur)
        table["current_dock_distance_m"] = table["current_location"].map(dock)
        table["proposed_location"] = table["sku"].map(new)
        table["proposed_dock_distance_m"] = table["proposed_location"].map(dock)
        moved = set(slot.moves["sku"]) if slot is not None and not slot.moves.empty else set()
        table["relocation_proposed"] = table["sku"].isin(moved)
        return table


def build_slotting_config(settings: dict, method: str) -> SlottingConfig:
    s = settings["slotting"]
    return SlottingConfig(
        method=method,
        max_moves=int(s["max_moves"]),
        class_based=ClassBasedWeights(**s["class_based"]),
        hybrid=HybridWeights(**s["hybrid"]),
        handling_compatibility=s.get("handling_compatibility"),
    )


def build_operation_params(settings: dict) -> OperationParams:
    o = settings["operations"]
    return OperationParams(
        walking_speed_m_s=float(o["walking_speed_m_s"]),
        pick_time_s_per_stop=float(o["pick_time_s_per_stop"]) if o.get("pick_time_s_per_stop") else None,
        daily_orders=float(o["daily_orders"]) if o.get("daily_orders") else None,
        operating_days=int(o["operating_days"]) if o.get("operating_days") else None,
        hourly_labor_cost=float(o["hourly_labor_cost"]) if o.get("hourly_labor_cost") else None,
        use_two_opt=bool(o.get("use_two_opt", True)),
        max_orders=int(o.get("max_orders", 3000)),
    )


def build_move_plan(result: PipelineResult, method: str) -> pd.DataFrame:
    slot = result.slotting[method]
    tables = result.validation.tables
    verified = verify_moves(slot.moves, tables["products"], result.locations, tables["inventory"],
                            result.settings["slotting"].get("handling_compatibility"))
    if verified.empty:
        return verified
    abc = result.abc.table.set_index("sku")
    products = tables["products"].set_index("sku")
    dock = result.locations.set_index("location_id")["dock_distance_m"]
    plan = verified.copy()
    plan["product_name"] = plan["sku"].map(products["product_name"])
    plan["abc_class"] = plan["sku"].map(abc["abc_class"])
    plan["order_lines"] = plan["sku"].map(abc["order_lines"]).fillna(0).astype(int)
    plan["current_dock_distance_m"] = plan["from_location"].map(dock)
    plan["proposed_dock_distance_m"] = plan["to_location"].map(dock)
    # Proxy contribution: each order line as a separate round trip from the dock.
    plan["estimated_travel_saving_m"] = (plan["order_lines"] * 2 *
                                         (plan["current_dock_distance_m"] - plan["proposed_dock_distance_m"]))
    plan = plan.sort_values(["group_score_gain", "sequence"], ascending=[False, True], kind="mergesort")
    return plan.reset_index(drop=True)


def run_pipeline(dataset: Dataset, settings: dict) -> PipelineResult:
    units = settings["units"]
    validation = validate_dataset(dataset, units["dimension"], units["weight"])
    result = PipelineResult(settings=settings, dataset=dataset, validation=validation,
                            selected_method=settings["slotting"].get("method", "hybrid"))
    missing = validation.missing_tables()
    if missing:
        result.errors.append("Eksik veya kullanılamayan tablolar: " + ", ".join(missing))
        return result
    tables = validation.tables

    # --- movement & ABC ----------------------------------------------------
    a = settings["analysis"]
    result.period = resolve_period(tables["order_lines"], int(a["period_days"]))
    result.movement = sku_movement(tables["order_lines"], tables["products"], result.period)
    result.abc = classify_abc(result.movement, a["metric"], float(a["a_share"]), float(a["b_share"]))
    result.period_lines = lines_in_period(tables["order_lines"], result.period)

    # --- geometry & distances ------------------------------------------------
    g = settings["geometry"]
    if g.get("dock_x") is not None and g.get("dock_y") is not None:
        dock_xy, dock_source = (float(g["dock_x"]), float(g["dock_y"])), "settings"
    elif dataset.dock_xy is not None:
        dock_xy, dock_source = dataset.dock_xy, "file"
    else:
        dock_xy, dock_source = None, "default"
    locations = tables["locations"]
    result.geometry = build_geometry(locations, tables.get("aisles"), dock_xy, dock_source)
    if g.get("distance_mode", "graph") == "manhattan":
        result.model = ManhattanDistanceModel(locations, result.geometry.dock_xy)
    else:
        result.model = GraphDistanceModel(result.geometry, locations)
    dock_distance = location_dock_distances(result.model, locations["location_id"])
    result.locations = locations.assign(dock_distance_m=locations["location_id"].map(dock_distance).to_numpy())

    # --- slotting + simulation for both methods -------------------------------
    params = build_operation_params(settings)
    for method in METHODS:
        slot = run_slotting(tables["products"], result.locations, tables["inventory"], result.abc.table,
                            build_slotting_config(settings, method))
        result.slotting[method] = slot
        result.move_plans[method] = build_move_plan(result, method)
        result.comparisons[method] = compare_placements(result.period_lines, slot.placement_current,
                                                        slot.placement_proposed, result.model, dock_distance, params)
    return result


def method_comparison_table(result: PipelineResult) -> pd.DataFrame:
    rows = []
    for method in METHODS:
        slot = result.slotting.get(method)
        comp = result.comparisons.get(method)
        if slot is None or comp is None:
            continue
        s = comp.summary
        plan = result.move_plans.get(method)
        violations = 0 if plan is None or plan.empty else int((plan["constraint_check"] != "Geçti").sum())
        rows.append({
            "Yöntem": METHOD_LABELS[method],
            "Taşıma sayısı": slot.move_count,
            "Taşınan SKU": slot.moved_sku_count,
            "Karşılaştırılan sipariş": s.get("orders_compared", 0),
            "Mevcut toplam mesafe (m)": s.get("total_current_m", math.nan),
            "Önerilen toplam mesafe (m)": s.get("total_proposed_m", math.nan),
            "Mesafe farkı (m)": s.get("difference_m", math.nan),
            "İyileşme (%)": s.get("improvement_pct", math.nan),
            "İyileşen sipariş": s.get("orders_improved", 0),
            "Kötüleşen sipariş": s.get("orders_worse", 0),
            "Kısıt ihlali": violations,
        })
    return pd.DataFrame(rows)


def assumptions_and_limitations(result: PipelineResult) -> list[str]:
    items = [
        "Sonuçlar bir depo modeli üzerinde yapılan SİMÜLASYONDUR; ölçülmüş operasyon verisi değildir.",
        "Rota: tek toplayıcı, her sipariş ayrı tur, başlangıç ve bitiş sevkiyat noktası; en yakın komşu + 2-opt "
        "sezgiseli (kanıtlanmış optimum değildir).",
        "Yürüme mesafesine raf içi yanal uzanma ve dikey seviye (z) dahil değildir.",
        "Yerleşim önerisi sezgisel bir puanlama ile üretilir; küresel optimum garanti edilmez.",
        "Stok bölme politikası: birden fazla toplama lokasyonundaki SKU'lar taşınmaz; taşınan SKU tüm miktarıyla taşınır.",
        "Taşıma işçiliği, yeniden stoklama, operasyon kesintisi ve kapasite değişiklikleri maliyete dahil değildir.",
        "İade ve iptal hareketleri çıkış metriklerine ve rotalara dahil edilmez.",
        "Uygulama hiçbir stok hareketi yapmaz ve harici bir WMS'e veri göndermez.",
    ]
    if result.is_synthetic:
        items.insert(0, "VERİ SENTETİKTİR: sonuçlar gerçek bir depo performansını göstermez.")
    if result.distance_is_estimate:
        items.insert(0, "Mesafeler TAHMİNİ Manhattan mesafesidir; koridor ağı kullanılmamıştır.")
    if result.geometry is not None:
        items.extend(result.geometry.notes)
    if result.model is not None:
        items.extend(result.model.notes)
    if result.period is not None and result.period.note:
        items.append(result.period.note)
    return items


def report_metadata(result: PipelineResult, method: str | None = None) -> dict:
    from .analytics.movement_analysis import METRIC_LABELS

    a = result.settings["analysis"]
    method = method or result.selected_method
    meta = {
        "Veri kaynağı": result.dataset.source_label or "Kullanıcı verisi",
        "Sentetik veri": "Evet" if result.is_synthetic else "Hayır",
        "Analiz dönemi": result.period.label() if result.period else "—",
        "ABC metriği": METRIC_LABELS.get(a["metric"], a["metric"]),
        "ABC eşikleri": f"A ≤ %{a['a_share'] * 100:.0f}, B sonraki %{a['b_share'] * 100:.0f}, C kalan",
        "Mesafe modeli": result.model.label if result.model else "—",
        "Yerleşim yöntemi": METHOD_LABELS.get(method, method),
        "Maksimum taşıma": result.settings["slotting"]["max_moves"],
        "Yürüme hızı (m/s)": result.settings["operations"]["walking_speed_m_s"],
        "Toplama süresi (sn/durak)": result.settings["operations"]["pick_time_s_per_stop"] or "girilmedi",
        "Hesaplama yöntemi": "Aynı siparişler, aynı rota modeli; en yakın komşu + 2-opt; "
                             "iyileşme % = (mevcut − önerilen) / mevcut × 100",
    }
    return meta


def placement_frame(placement: dict[str, list[str]], products: pd.DataFrame, abc: pd.DataFrame,
                    dock_distance: pd.Series) -> pd.DataFrame:
    rows = []
    abc_idx = abc.set_index("sku")
    names = products.set_index("sku")["product_name"]
    for sku in sorted(placement):
        for loc in placement[sku]:
            rows.append({"sku": sku, "product_name": names.get(sku, ""),
                         "abc_class": abc_idx["abc_class"].get(sku, ""),
                         "location_id": loc, "dock_distance_m": dock_distance.get(loc, np.nan)})
    return pd.DataFrame(rows, columns=["sku", "product_name", "abc_class", "location_id", "dock_distance_m"])
