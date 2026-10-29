"""File loading (CSV / XLSX) and the Dataset container.

Files are read as text so that validation can report the original value of
every bad cell. Type conversion happens in validators.py.
"""
from __future__ import annotations

import io
import re
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd

from .schemas import SCHEMAS

DIMENSION_FACTORS = {"m": 1.0, "cm": 0.01, "mm": 0.001}
WEIGHT_FACTORS = {"kg": 1.0, "g": 0.001, "t": 1000.0}


@dataclass
class Dataset:
    """Raw input tables plus provenance information."""

    tables: dict[str, pd.DataFrame] = field(default_factory=dict)
    is_synthetic: bool = False
    source_label: str = ""
    # Optional geometry that is not part of the tables.
    dock_xy: tuple[float, float] | None = None
    notes: list[str] = field(default_factory=list)

    def has(self, table: str) -> bool:
        df = self.tables.get(table)
        return df is not None and not df.empty


def normalize_column_name(name: object) -> str:
    text = str(name).strip().lower()
    text = re.sub(r"[\s\-/]+", "_", text)
    return re.sub(r"[^0-9a-zçğıöşü_]", "", text)


def read_table(source, filename: str | None = None, sheet_name: str | int = 0) -> pd.DataFrame:
    """Read a CSV or XLSX file (path, bytes or file-like) into a text DataFrame."""
    name = filename or (str(source) if isinstance(source, (str, Path)) else getattr(source, "name", ""))
    suffix = Path(name).suffix.lower()
    if isinstance(source, bytes):
        source = io.BytesIO(source)
    if suffix in (".xlsx", ".xlsm", ".xls"):
        df = pd.read_excel(source, sheet_name=sheet_name, dtype=str, engine="openpyxl")
    elif suffix in (".csv", ".txt", ""):
        df = _read_csv_flexible(source)
    else:
        raise ValueError(f"Desteklenmeyen dosya türü: {suffix} (CSV veya XLSX bekleniyor)")
    df.columns = [normalize_column_name(c) for c in df.columns]
    df = df.fillna("")
    for col in df.columns:
        df[col] = df[col].astype(str).str.strip()
    # Drop rows that are completely empty (common at the end of Excel exports).
    df = df[~(df == "").all(axis=1)]
    return df


def _read_csv_flexible(source) -> pd.DataFrame:
    if hasattr(source, "read"):
        raw = source.read()
    else:
        raw = Path(source).read_bytes()
    if isinstance(raw, str):
        raw = raw.encode("utf-8")
    for encoding in ("utf-8-sig", "cp1254", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    first_line = text.splitlines()[0] if text else ""
    sep = ";" if first_line.count(";") > first_line.count(",") else ","
    return pd.read_csv(io.StringIO(text), sep=sep, dtype=str, keep_default_na=False)


def convert_units(table: str, df: pd.DataFrame, dimension_unit: str = "m", weight_unit: str = "kg") -> pd.DataFrame:
    """Convert dimension / weight columns of a *typed* table to metres and kilograms."""
    dim_factor = DIMENSION_FACTORS[dimension_unit]
    weight_factor = WEIGHT_FACTORS[weight_unit]
    out = df.copy()
    if table == "products":
        for col in ("length_m", "width_m", "height_m"):
            if col in out:
                out[col] = out[col] * dim_factor
        if "weight_kg" in out:
            out["weight_kg"] = out["weight_kg"] * weight_factor
    elif table == "locations":
        for col in ("max_length_m", "max_width_m", "max_height_m"):
            if col in out:
                out[col] = out[col] * dim_factor
        if "max_volume_m3" in out:
            out["max_volume_m3"] = out["max_volume_m3"] * dim_factor ** 3
        if "max_weight_kg" in out:
            out["max_weight_kg"] = out["max_weight_kg"] * weight_factor
    return out


def template_frame(table: str) -> pd.DataFrame:
    specs = SCHEMAS[table]
    return pd.DataFrame([{s.name: s.example for s in specs}])
