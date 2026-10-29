"""Warehouse geometry: aisles, cross-aisles and the dock (shipping point).

Geometry model (parallel-aisle warehouse):
    * Each aisle is a straight walkable corridor along the Y axis at
      `x_center`, from `y_start` (front end) to `y_end` (back end).
    * A front cross-aisle connects all front ends, a back cross-aisle connects
      all back ends (walking between neighbouring ends is rectilinear).
    * A location is picked from its access point: (aisle x_center, location y).
      The lateral reach from the aisle centre into the rack and the vertical
      level (z) are not counted as walking distance.

Geometry sources, in order of preference:
    "file"     aisles table uploaded by the user
    "derived"  aisle centre = mean x of its locations, ends = min/max y ± margin
               (an approximation; flagged in the UI)
"""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd

CROSS_AISLE_MARGIN_M = 1.5


@dataclass
class WarehouseGeometry:
    aisles: pd.DataFrame  # aisle_id, x_center, y_start, y_end
    dock_xy: tuple[float, float]
    source: str  # "file" | "derived"
    dock_source: str  # "file" | "settings" | "default"
    notes: list[str] = field(default_factory=list)

    @property
    def bounds(self) -> tuple[float, float, float, float]:
        xs = list(self.aisles["x_center"]) + [self.dock_xy[0]]
        ys = list(self.aisles["y_start"]) + list(self.aisles["y_end"]) + [self.dock_xy[1]]
        return min(xs), max(xs), min(ys), max(ys)

    @property
    def is_approximate(self) -> bool:
        return self.source != "file" or self.dock_source == "default"


def derive_aisles(locations: pd.DataFrame, margin: float = CROSS_AISLE_MARGIN_M) -> pd.DataFrame:
    grouped = locations.groupby("aisle_id").agg(x_center=("x", "mean"), y_min=("y", "min"), y_max=("y", "max"))
    aisles = pd.DataFrame({
        "aisle_id": grouped.index,
        "x_center": grouped["x_center"].to_numpy(),
        "y_start": (grouped["y_min"] - margin).to_numpy(),
        "y_end": (grouped["y_max"] + margin).to_numpy(),
    })
    return aisles.sort_values("x_center").reset_index(drop=True)


def build_geometry(locations: pd.DataFrame, aisles: pd.DataFrame | None = None,
                   dock_xy: tuple[float, float] | None = None, dock_source: str = "settings") -> WarehouseGeometry:
    notes: list[str] = []
    if aisles is not None and not aisles.empty:
        geo_aisles = aisles[["aisle_id", "x_center", "y_start", "y_end"]].copy()
        source = "file"
        missing = sorted(set(locations["aisle_id"]) - set(geo_aisles["aisle_id"]))
        if missing:
            notes.append(f"Koridor tablosunda olmayan {len(missing)} koridor var (ör. {', '.join(missing[:5])}); "
                         "bu koridorlardaki lokasyonlara ulaşılamaz.")
    else:
        geo_aisles = derive_aisles(locations)
        source = "derived"
        notes.append("Koridor geometrisi lokasyon koordinatlarından türetildi (koridor orta hattı = lokasyonların "
                     "ortalama X değeri). Gerçek depo planı değildir; yaklaşık bir modeldir.")
    swapped = geo_aisles["y_start"] > geo_aisles["y_end"]
    if swapped.any():
        geo_aisles.loc[swapped, ["y_start", "y_end"]] = geo_aisles.loc[swapped, ["y_end", "y_start"]].to_numpy()
        notes.append(f"{int(swapped.sum())} koridorda y_start > y_end idi; uçlar yer değiştirilerek kullanıldı.")
    if dock_xy is None:
        dock_xy = (float(geo_aisles["x_center"].min()), float(geo_aisles["y_start"].min()) - 2.0)
        dock_source = "default"
        notes.append("Sevkiyat noktası tanımlanmadı; varsayılan olarak ilk koridorun önüne yerleştirildi. "
                     "Ayarlar sayfasından gerçek koordinatı girin.")
    return WarehouseGeometry(geo_aisles.sort_values("x_center").reset_index(drop=True),
                             (float(dock_xy[0]), float(dock_xy[1])), source, dock_source, notes)
