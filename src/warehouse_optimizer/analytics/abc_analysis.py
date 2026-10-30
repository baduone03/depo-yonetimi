"""ABC classification by cumulative contribution of a chosen movement metric.

Classification rule (deterministic):
    * SKUs are sorted by metric (descending), ties broken by SKU code (ascending).
    * `cumulative_share` is the running share including the SKU itself.
    * A SKU gets class A if the cumulative share *before* it is below the A
      threshold, B if it is below A+B, otherwise C. Thus the SKU that crosses
      the 80 % boundary is still A, and the top SKU is always A.
    * SKUs with zero movement are always C.
    * If total movement is zero, classification is undefined: shares are NaN
      and every SKU is C (flagged by `defined=False`).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .movement_analysis import METRIC_LABELS


@dataclass
class ABCResult:
    table: pd.DataFrame
    metric: str
    thresholds: tuple[float, float]
    defined: bool

    def class_counts(self) -> dict[str, int]:
        counts = self.table["abc_class"].value_counts()
        return {c: int(counts.get(c, 0)) for c in ("A", "B", "C")}

    def class_share(self) -> dict[str, float]:
        if not self.defined:
            return {c: float("nan") for c in ("A", "B", "C")}
        total = self.table["metric_value"].sum()
        sums = self.table.groupby("abc_class")["metric_value"].sum()
        return {c: float(sums.get(c, 0.0) / total) for c in ("A", "B", "C")}


def classify_abc(movement: pd.DataFrame, metric: str = "order_lines",
                 a_share: float = 0.80, b_share: float = 0.15) -> ABCResult:
    if metric not in METRIC_LABELS:
        raise ValueError(f"Bilinmeyen metrik: {metric}")
    if not (0 < a_share < 1 and 0 <= b_share < 1 and a_share + b_share <= 1):
        raise ValueError("ABC eşikleri geçersiz: 0 < A < 1, B ≥ 0 ve A + B ≤ 1 olmalı")

    df = movement.copy()
    df["metric_value"] = df[metric].astype(float) if not df.empty else pd.Series(dtype=float)
    df = df.sort_values(["metric_value", "sku"], ascending=[False, True], kind="mergesort").reset_index(drop=True)
    total = float(df["metric_value"].sum()) if not df.empty else 0.0
    df["rank"] = np.arange(1, len(df) + 1)

    if total <= 0:
        df["share"] = np.nan
        df["cumulative_share"] = np.nan
        df["abc_class"] = "C"
        return ABCResult(df, metric, (a_share, b_share), defined=False)

    df["share"] = df["metric_value"] / total
    df["cumulative_share"] = df["share"].cumsum()
    previous = df["cumulative_share"] - df["share"]
    # Rounding guard so that e.g. 0.7999999999 is treated as 0.80.
    previous = previous.round(12)
    a_limit, b_limit = round(a_share, 12), round(a_share + b_share, 12)
    classes = np.where(previous < a_limit, "A", np.where(previous < b_limit, "B", "C"))
    classes = np.where(df["metric_value"] <= 0, "C", classes)
    df["abc_class"] = classes
    return ABCResult(df, metric, (a_share, b_share), defined=True)
