"""SKU movement metrics over an analysis period.

Only `outbound` movements are counted. Returns and cancellations are kept out
of pick metrics (they are reported separately by validation).
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

METRIC_LABELS = {
    "order_lines": "Sipariş satırı sayısı",
    "quantity": "Toplam çıkış miktarı",
    "active_days": "Hareketli sipariş günü sayısı",
}


@dataclass
class AnalysisPeriod:
    start: pd.Timestamp | None
    end: pd.Timestamp | None
    requested_days: int
    available_days: int
    note: str = ""

    @property
    def days(self) -> int:
        if self.start is None or self.end is None:
            return 0
        return int((self.end - self.start).days) + 1

    def label(self) -> str:
        if self.start is None:
            return "Dönem yok (veri yok)"
        return f"{self.start.date()} – {self.end.date()} ({self.days} gün)"


def outbound_lines(order_lines: pd.DataFrame) -> pd.DataFrame:
    if order_lines is None or order_lines.empty:
        return pd.DataFrame(columns=["order_id", "order_date", "sku", "quantity", "movement_type"])
    return order_lines[order_lines["movement_type"] == "outbound"].copy()


def resolve_period(order_lines: pd.DataFrame, period_days: int = 90) -> AnalysisPeriod:
    """Period ending at the latest outbound date and going back `period_days` days."""
    out = outbound_lines(order_lines)
    if out.empty:
        return AnalysisPeriod(None, None, period_days, 0, "Çıkış hareketi bulunamadı.")
    end = out["order_date"].max().normalize()
    first = out["order_date"].min().normalize()
    available = int((end - first).days) + 1
    start = end - pd.Timedelta(days=period_days - 1)
    note = ""
    if first > start:
        start = first
        note = (f"Veri yalnızca {available} günü kapsıyor; istenen {period_days} günlük dönem "
                f"tamamlanamadı.")
    return AnalysisPeriod(start, end, period_days, available, note)


def lines_in_period(order_lines: pd.DataFrame, period: AnalysisPeriod) -> pd.DataFrame:
    out = outbound_lines(order_lines)
    if period.start is None or out.empty:
        return out.iloc[0:0]
    dates = out["order_date"].dt.normalize()
    return out[(dates >= period.start) & (dates <= period.end)].copy()


def sku_movement(order_lines: pd.DataFrame, products: pd.DataFrame, period: AnalysisPeriod) -> pd.DataFrame:
    """Per-SKU metrics. SKUs in the product master without movement get zeros."""
    lines = lines_in_period(order_lines, period)
    if lines.empty:
        stats = pd.DataFrame(columns=["sku", "quantity", "order_lines", "active_days", "orders"])
    else:
        lines = lines.assign(day=lines["order_date"].dt.normalize())
        stats = lines.groupby("sku").agg(
            quantity=("quantity", "sum"),
            order_lines=("order_id", "size"),
            orders=("order_id", "nunique"),
            active_days=("day", "nunique"),
        ).reset_index()
    base = products[["sku"]].drop_duplicates()
    result = base.merge(stats, on="sku", how="left")
    for col in ("quantity", "order_lines", "active_days", "orders"):
        result[col] = result[col].fillna(0)
    result[["order_lines", "active_days", "orders"]] = result[["order_lines", "active_days", "orders"]].astype(int)
    days = max(period.days, 1)
    result["lines_per_day"] = result["order_lines"] / days
    return result


def daily_activity(order_lines: pd.DataFrame, period: AnalysisPeriod) -> pd.DataFrame:
    lines = lines_in_period(order_lines, period)
    if lines.empty:
        return pd.DataFrame(columns=["date", "orders", "order_lines", "quantity"])
    lines = lines.assign(date=lines["order_date"].dt.normalize())
    return lines.groupby("date").agg(orders=("order_id", "nunique"), order_lines=("sku", "size"),
                                     quantity=("quantity", "sum")).reset_index()
