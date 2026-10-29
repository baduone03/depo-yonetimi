"""CSV / XLSX export of all reports.

Every export carries its metadata (analysis period, metric, parameters,
calculation method): as leading `# key: value` lines in CSV and as a
"Rapor bilgisi" sheet in XLSX.
"""
from __future__ import annotations

import io
import math

import pandas as pd

COLUMN_LABELS = {
    "sku": "SKU", "product_name": "Ürün adı", "product_family": "Ürün ailesi", "abc_class": "ABC sınıfı",
    "metric_value": "Metrik değeri", "share": "Pay", "cumulative_share": "Kümülatif pay", "rank": "Sıra",
    "quantity": "Çıkış miktarı", "order_lines": "Sipariş satırı", "active_days": "Hareketli gün",
    "orders": "Sipariş sayısı", "lines_per_day": "Günlük satır",
    "current_location": "Mevcut lokasyon", "current_dock_distance_m": "Mevcut erişim mesafesi (m)",
    "proposed_location": "Önerilen lokasyon", "proposed_dock_distance_m": "Önerilen erişim mesafesi (m)",
    "relocation_proposed": "Taşıma önerildi",
    "sequence": "Uygulama sırası", "group": "Grup", "from_location": "Mevcut lokasyon",
    "to_location": "Hedef lokasyon", "move_type": "Hareket tipi", "score_gain": "Puan kazancı",
    "group_score_gain": "Grup puan kazancı", "reason": "Gerekçe", "constraint_check": "Kısıt kontrolü",
    "estimated_travel_saving_m": "Tahmini katkı (m/dönem, tek-sefer proxy)",
    "location_id": "Lokasyon", "dock_distance_m": "Sevkiyata mesafe (m)",
    "order_id": "Sipariş", "order_date": "Sipariş tarihi", "lines": "Satır",
    "stops_current": "Durak (mevcut)", "stops_proposed": "Durak (önerilen)",
    "distance_current_m": "Mesafe mevcut (m)", "distance_proposed_m": "Mesafe önerilen (m)",
    "difference_m": "Fark (m)", "change_pct": "Değişim (%)",
    "table": "Tablo", "row": "Satır no", "field": "Alan", "severity": "Önem", "message": "Açıklama",
    "value": "Değer", "action": "İşlem", "current_locations": "Mevcut lokasyonlar", "reason_code": "Neden kodu",
}

MOVE_TYPE_LABELS = {"move": "Taşıma", "evict": "Yer açma taşıması"}


def localize(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    if "move_type" in out:
        out["move_type"] = out["move_type"].map(MOVE_TYPE_LABELS).fillna(out["move_type"])
    return out.rename(columns={c: COLUMN_LABELS.get(c, c) for c in out.columns})


def _metadata_lines(metadata: dict | None) -> str:
    if not metadata:
        return ""
    return "".join(f"# {k}: {v}\n" for k, v in metadata.items())


def to_csv_bytes(df: pd.DataFrame, metadata: dict | None = None) -> bytes:
    body = df.to_csv(index=False)
    return (_metadata_lines(metadata) + body).encode("utf-8-sig")


def _sheet_name(name: str, used: set[str]) -> str:
    base = "".join(ch for ch in name if ch not in '[]:*?/\\')[:31] or "Sayfa"
    candidate, i = base, 2
    while candidate in used:
        suffix = f" ({i})"
        candidate = base[:31 - len(suffix)] + suffix
        i += 1
    used.add(candidate)
    return candidate


def to_excel_bytes(sheets: dict[str, pd.DataFrame], metadata: dict | None = None) -> bytes:
    buffer = io.BytesIO()
    used: set[str] = set()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        if metadata:
            meta = pd.DataFrame({"Alan": list(metadata.keys()), "Değer": [str(v) for v in metadata.values()]})
            meta.to_excel(writer, sheet_name=_sheet_name("Rapor bilgisi", used), index=False)
        for name, df in sheets.items():
            sheet = _sheet_name(name, used)
            frame = df.copy()
            for col in frame.columns:
                if pd.api.types.is_datetime64_any_dtype(frame[col]):
                    frame[col] = frame[col].dt.tz_localize(None) if frame[col].dt.tz is not None else frame[col]
            frame.to_excel(writer, sheet_name=sheet, index=False)
            ws = writer.sheets[sheet]
            for idx, col in enumerate(frame.columns, start=1):
                width = max([len(str(col))] + [len(str(v)) for v in frame[col].head(200)]) + 2
                ws.column_dimensions[ws.cell(row=1, column=idx).column_letter].width = min(width, 60)
    return buffer.getvalue()


def kpi_frame(summary: dict) -> pd.DataFrame:
    def fmt(value):
        if value is None or (isinstance(value, float) and math.isnan(value)):
            return "Hesaplanamadı"
        return value

    labels = [
        ("orders_compared", "Karşılaştırılan sipariş"),
        ("total_current_m", "Toplam mesafe — mevcut (m)"),
        ("total_proposed_m", "Toplam mesafe — önerilen (m)"),
        ("mean_current_m", "Sipariş başına ortalama — mevcut (m)"),
        ("mean_proposed_m", "Sipariş başına ortalama — önerilen (m)"),
        ("median_current_m", "Sipariş başına medyan — mevcut (m)"),
        ("median_proposed_m", "Sipariş başına medyan — önerilen (m)"),
        ("stops_current", "Toplam toplama durağı — mevcut"),
        ("stops_proposed", "Toplam toplama durağı — önerilen"),
        ("time_current_h", "Tahmini toplam süre — mevcut (saat)"),
        ("time_proposed_h", "Tahmini toplam süre — önerilen (saat)"),
        ("difference_m", "Toplam mesafe farkı (m)"),
        ("time_difference_h", "Tahmini süre farkı (saat)"),
        ("improvement_pct", "İyileşme (%)"),
        ("orders_improved", "İyileşen sipariş"),
        ("orders_worse", "Kötüleşen sipariş"),
        ("daily_orders", "Günlük sipariş (projeksiyon)"),
        ("projected_hours_saved", "Projeksiyon: kazanılan saat (tahmini)"),
        ("projected_distance_saved_km", "Projeksiyon: azalan mesafe km (tahmini)"),
        ("projected_labor_cost_saved", "Projeksiyon: işçilik maliyet farkı (tahmini)"),
    ]
    return pd.DataFrame([{"Gösterge": label, "Değer": fmt(summary.get(key))} for key, label in labels])
