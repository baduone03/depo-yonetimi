"""Type conversion and data-quality validation.

Rules:
* Every problem is reported with table, file row number, field and message.
* Rows that cannot be used are excluded and the exclusion is reported; values
  are never silently "repaired". Defaults are applied only to empty optional
  cells and that is reported as well (aggregated per column).
* File row numbers assume a single header row (data row 1 == file row 2).
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .loaders import Dataset, convert_units
from .schemas import (DEFAULTS, FALSE_VALUES, MOVEMENT_TYPE_ALIASES, REQUIRED_TABLES, SCHEMAS,
                      TRUE_VALUES, ColumnSpec)

ERROR = "hata"
WARNING = "uyarı"
INFO = "bilgi"

MAX_DIMENSION_M = 30.0
MAX_UNIT_WEIGHT_KG = 30000.0

ISSUE_COLUMNS = ["table", "row", "field", "severity", "message", "value", "action"]


@dataclass
class ValidationReport:
    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    issues: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=ISSUE_COLUMNS))
    row_counts: dict[str, dict[str, int]] = field(default_factory=dict)

    @property
    def error_count(self) -> int:
        return int((self.issues["severity"] == ERROR).sum())

    @property
    def warning_count(self) -> int:
        return int((self.issues["severity"] == WARNING).sum())

    def missing_tables(self) -> list[str]:
        return [t for t in REQUIRED_TABLES if t not in self.tables or self.tables[t].empty]

    def is_usable(self) -> bool:
        return not self.missing_tables()


class _IssueLog:
    def __init__(self) -> None:
        self.rows: list[dict] = []

    def add(self, table, row, field_name, severity, message, value="", action="") -> None:
        self.rows.append({
            "table": table,
            "row": None if row is None else int(row),
            "field": field_name,
            "severity": severity,
            "message": message,
            "value": "" if value is None else str(value),
            "action": action,
        })

    def frame(self) -> pd.DataFrame:
        if not self.rows:
            return pd.DataFrame(columns=ISSUE_COLUMNS)
        return pd.DataFrame(self.rows, columns=ISSUE_COLUMNS)


def _file_row(index) -> int:
    return int(index) + 2


def parse_bool(value: str) -> bool | None:
    text = str(value).strip().lower()
    if text in TRUE_VALUES:
        return True
    if text in FALSE_VALUES:
        return False
    return None


def _parse_dates(series: pd.Series) -> pd.Series:
    parsed = pd.to_datetime(series, errors="coerce", format="ISO8601")
    missing = parsed.isna() & (series != "")
    if missing.any():
        parsed.loc[missing] = pd.to_datetime(series[missing], errors="coerce", dayfirst=True, format="mixed")
    return parsed


def _parse_table(table: str, raw: pd.DataFrame, log: _IssueLog) -> pd.DataFrame | None:
    specs: list[ColumnSpec] = SCHEMAS[table]
    missing_required = [s.name for s in specs if s.required and s.name not in raw.columns]
    if missing_required:
        for col in missing_required:
            log.add(table, None, col, ERROR, "Zorunlu kolon dosyada yok", action="tablo kullanılamaz")
        return None

    df = raw.copy()
    defaults = DEFAULTS.get(table, {})
    excluded = pd.Series(False, index=df.index)

    for spec in specs:
        col = spec.name
        if col not in df.columns:
            if col in defaults:
                df[col] = defaults[col]
                log.add(table, None, col, INFO, "Opsiyonel kolon yok, varsayılan uygulandı",
                        defaults[col], "varsayılan")
            else:
                df[col] = np.nan if spec.dtype == "float" else ""
            continue

        values = df[col].astype(str).str.strip()
        empty = values == ""

        if spec.dtype == "str":
            if spec.required:
                for idx in df.index[empty & ~excluded]:
                    log.add(table, _file_row(idx), col, ERROR, "Zorunlu alan boş", "", "satır analiz dışı")
                excluded |= empty
            elif col in defaults and empty.any():
                log.add(table, None, col, INFO, f"{int(empty.sum())} boş hücreye varsayılan uygulandı",
                        defaults[col], "varsayılan")
                values = values.where(~empty, defaults[col])
            df[col] = values

        elif spec.dtype == "float":
            numeric = pd.to_numeric(values.str.replace(",", ".", regex=False), errors="coerce")
            invalid = numeric.isna() & ~empty
            for idx in df.index[invalid & ~excluded]:
                if spec.required:
                    log.add(table, _file_row(idx), col, ERROR, "Sayısal değer bekleniyor", values[idx],
                            "satır analiz dışı")
                else:
                    log.add(table, _file_row(idx), col, WARNING, "Sayısal değer bekleniyor; bilinmiyor kabul edildi",
                            values[idx], "değer boş bırakıldı")
            if spec.required:
                for idx in df.index[empty & ~excluded]:
                    log.add(table, _file_row(idx), col, ERROR, "Zorunlu alan boş", "", "satır analiz dışı")
                excluded |= invalid | empty
            elif col in defaults and empty.any():
                numeric = numeric.where(~empty, defaults[col])
            df[col] = numeric.astype(float)

        elif spec.dtype == "bool":
            parsed = values.map(parse_bool)
            invalid = parsed.isna() & ~empty
            for idx in df.index[invalid & ~excluded]:
                log.add(table, _file_row(idx), col, WARNING, "Evet/hayır değeri anlaşılamadı; varsayılan uygulandı",
                        values[idx], "varsayılan")
            default = defaults.get(col, False)
            if empty.any():
                log.add(table, None, col, INFO, f"{int(empty.sum())} boş hücreye varsayılan uygulandı",
                        default, "varsayılan")
            parsed = parsed.where(~(empty | invalid), default)
            df[col] = parsed.astype(bool)

        elif spec.dtype == "date":
            parsed = _parse_dates(values)
            invalid = parsed.isna()
            for idx in df.index[invalid & ~excluded]:
                msg = "Zorunlu alan boş" if empty[idx] else "Geçersiz tarih"
                log.add(table, _file_row(idx), col, ERROR, msg, values[idx], "satır analiz dışı")
            excluded |= invalid
            df[col] = parsed

    df["_row"] = [_file_row(i) for i in df.index]
    return df[~excluded].copy()


def _exclude_duplicates(table: str, df: pd.DataFrame, key: list[str], log: _IssueLog) -> pd.DataFrame:
    dup = df.duplicated(subset=key, keep="first")
    for _, row in df[dup].iterrows():
        log.add(table, row["_row"], ",".join(key), ERROR, "Yinelenen anahtar; ilk kayıt kullanıldı",
                "/".join(str(row[k]) for k in key), "satır analiz dışı")
    return df[~dup].copy()


def _check_range(table, df, col, low, high, log, message, inclusive_low=False) -> pd.Series:
    values = df[col]
    bad = (values <= low) if not inclusive_low else (values < low)
    bad = bad | (values > high)
    bad = bad & values.notna()
    for _, row in df[bad].iterrows():
        log.add(table, row["_row"], col, ERROR, message, row[col], "satır analiz dışı")
    return bad


def validate_dataset(dataset: Dataset, dimension_unit: str = "m", weight_unit: str = "kg") -> ValidationReport:
    log = _IssueLog()
    report = ValidationReport()
    typed: dict[str, pd.DataFrame] = {}

    for table in SCHEMAS:
        raw = dataset.tables.get(table)
        if raw is None:
            if table in REQUIRED_TABLES:
                log.add(table, None, "", ERROR, "Tablo yüklenmedi", action="analiz yapılamaz")
            continue
        parsed = _parse_table(table, raw, log)
        report.row_counts[table] = {"input": int(len(raw)), "valid": 0}
        if parsed is None:
            continue
        typed[table] = convert_units(table, parsed, dimension_unit, weight_unit)

    # --- products -----------------------------------------------------
    if "products" in typed:
        df = _exclude_duplicates("products", typed["products"], ["sku"], log)
        bad = pd.Series(False, index=df.index)
        for col in ("length_m", "width_m", "height_m"):
            bad |= _check_range("products", df, col, 0, MAX_DIMENSION_M, log,
                                f"Fiziksel olarak imkânsız boyut (0 < değer ≤ {MAX_DIMENSION_M:g} m olmalı)")
        bad |= _check_range("products", df, "weight_kg", 0, MAX_UNIT_WEIGHT_KG, log,
                            f"Fiziksel olarak imkânsız ağırlık (0 < değer ≤ {MAX_UNIT_WEIGHT_KG:g} kg olmalı)")
        df = df[~bad].copy()
        df["storage_requirements"] = df["storage_requirements"].str.lower()
        df["handling_type"] = df["handling_type"].str.lower()
        df["unit_volume_m3"] = df["length_m"] * df["width_m"] * df["height_m"]
        typed["products"] = df

    known_skus = set(typed["products"]["sku"]) if "products" in typed else set()

    # --- locations ----------------------------------------------------
    if "locations" in typed:
        df = _exclude_duplicates("locations", typed["locations"], ["location_id"], log)
        capacity_cols = ["max_weight_kg", "max_volume_m3", "max_length_m", "max_width_m", "max_height_m"]
        for col in capacity_cols:
            nonpositive = df[col].notna() & (df[col] <= 0)
            for _, row in df[nonpositive].iterrows():
                log.add("locations", row["_row"], col, WARNING, "Kapasite sıfır veya negatif; bilinmiyor kabul edildi",
                        row[col], "hedef lokasyon olarak kullanılmaz")
            df.loc[nonpositive, col] = np.nan
        unknown_cap = df[capacity_cols].isna().any(axis=1)
        if unknown_cap.any():
            sample = ", ".join(df.loc[unknown_cap, "location_id"].head(5))
            log.add("locations", None, "kapasite", WARNING,
                    f"{int(unknown_cap.sum())} lokasyonda kapasite bilgisi eksik (ör. {sample})",
                    "", "bu lokasyonlar hedef olarak kullanılmaz")
        df["location_type"] = df["location_type"].str.lower()
        df["storage_class"] = df["storage_class"].str.lower()
        typed["locations"] = df

    known_locations = set(typed["locations"]["location_id"]) if "locations" in typed else set()

    # --- order lines --------------------------------------------------
    if "order_lines" in typed:
        df = typed["order_lines"]
        neg = df["quantity"] <= 0
        for _, row in df[neg].iterrows():
            log.add("order_lines", row["_row"], "quantity", ERROR, "Miktar sıfır veya negatif", row["quantity"],
                    "satır analiz dışı")
        df = df[~neg].copy()
        normalized = df["movement_type"].str.lower().map(MOVEMENT_TYPE_ALIASES)
        unknown_type = normalized.isna()
        for _, row in df[unknown_type].iterrows():
            log.add("order_lines", row["_row"], "movement_type", ERROR, "Bilinmeyen hareket türü",
                    row["movement_type"], "satır analiz dışı")
        df = df[~unknown_type].copy()
        df["movement_type"] = normalized[~unknown_type]
        if known_skus:
            unknown = ~df["sku"].isin(known_skus)
            for _, row in df[unknown].iterrows():
                log.add("order_lines", row["_row"], "sku", ERROR, "Bilinmeyen SKU (ürün listesinde yok)",
                        row["sku"], "satır analiz dışı")
            df = df[~unknown].copy()
        key = ["order_id", "sku", "movement_type"]
        dup_mask = df.duplicated(subset=key, keep=False)
        if dup_mask.any():
            n_groups = df[dup_mask].groupby(key).ngroups
            log.add("order_lines", None, ",".join(key), WARNING,
                    f"{int(dup_mask.sum())} yinelenen satır {n_groups} satırda birleştirildi (miktarlar toplandı)",
                    "", "birleştirildi")
            df = (df.groupby(key, as_index=False, sort=False)
                  .agg(order_date=("order_date", "min"), quantity=("quantity", "sum"), _row=("_row", "min")))
        returns = int((df["movement_type"] == "return").sum())
        cancels = int((df["movement_type"] == "cancel").sum())
        if returns or cancels:
            log.add("order_lines", None, "movement_type", INFO,
                    f"{returns} iade ve {cancels} iptal satırı çıkış hareketlerinden ayrıldı",
                    "", "ABC ve rota analizine katılmaz")
        typed["order_lines"] = df

    # --- inventory ----------------------------------------------------
    if "inventory" in typed:
        df = typed["inventory"]
        neg = df["current_quantity"] < 0
        for _, row in df[neg].iterrows():
            log.add("inventory", row["_row"], "current_quantity", ERROR, "Negatif stok", row["current_quantity"],
                    "satır analiz dışı")
        zero = df["current_quantity"] == 0
        for _, row in df[zero].iterrows():
            log.add("inventory", row["_row"], "current_quantity", WARNING, "Stok sıfır; lokasyon boş kabul edildi",
                    0, "satır analiz dışı")
        df = df[~(neg | zero)].copy()
        if known_skus:
            unknown = ~df["sku"].isin(known_skus)
            for _, row in df[unknown].iterrows():
                log.add("inventory", row["_row"], "sku", ERROR, "Bilinmeyen SKU", row["sku"], "satır analiz dışı")
            df = df[~unknown].copy()
        if known_locations or "locations" in typed:
            unknown = ~df["location_id"].isin(known_locations)
            for _, row in df[unknown].iterrows():
                log.add("inventory", row["_row"], "location_id", ERROR, "Eşleşmeyen lokasyon (lokasyon listesinde yok)",
                        row["location_id"], "satır analiz dışı")
            df = df[~unknown].copy()
        key = ["sku", "location_id"]
        dup_mask = df.duplicated(subset=key, keep=False)
        if dup_mask.any():
            log.add("inventory", None, "sku,location_id", WARNING,
                    f"{int(dup_mask.sum())} yinelenen stok satırı birleştirildi (miktarlar toplandı)", "", "birleştirildi")
            df = df.groupby(key, as_index=False, sort=False).agg(current_quantity=("current_quantity", "sum"),
                                                                 _row=("_row", "min"))
        per_location = df.groupby("location_id")["sku"].nunique()
        mixed = per_location[per_location > 1]
        for loc_id, n in mixed.items():
            log.add("inventory", None, "location_id", WARNING,
                    f"Aynı lokasyonda {n} farklı SKU var (tek SKU kuralı ihlali)", loc_id,
                    "lokasyon optimizasyonda sabit kabul edilir")
        typed["inventory"] = df

    if "aisles" in typed:
        typed["aisles"] = _exclude_duplicates("aisles", typed["aisles"], ["aisle_id"], log)

    # --- cross-table physical checks on the current placement ---------------
    if all(t in typed for t in ("products", "locations", "inventory")):
        from ..optimization.constraints import check_current_placement

        for violation in check_current_placement(typed["products"], typed["locations"], typed["inventory"]):
            log.add("inventory", violation["row"], violation["field"], WARNING,
                    f"Mevcut yerleşim kısıt ihlali: {violation['message']}",
                    f"{violation['sku']} @ {violation['location_id']}", "raporlandı; SKU uygun bir lokasyona taşınabilir")

    for table, df in typed.items():
        report.row_counts.setdefault(table, {"input": len(df), "valid": 0})
        report.row_counts[table]["valid"] = int(len(df))
    report.tables = typed
    report.issues = log.frame()
    return report
