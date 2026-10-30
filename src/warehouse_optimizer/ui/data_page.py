"""Veri Yükleme ve Veri Kalitesi page."""
from __future__ import annotations

import io
from pathlib import Path

import pandas as pd
import streamlit as st

from ..data.loaders import Dataset, read_table
from ..data.schemas import REQUIRED_TABLES, SCHEMAS, TABLE_LABELS, data_dictionary_rows
from ..hosting import is_hosted, privacy_notice
from ..reporting.exports import localize, to_excel_bytes
from . import common as c

TEMPLATE_DIR = Path(__file__).resolve().parents[3] / "templates"
SEVERITY_ORDER = {"hata": 0, "uyarı": 1, "bilgi": 2}


def render() -> None:
    c.page_header("Veri Yükleme ve Veri Kalitesi", "CSV veya XLSX dosyaları")
    if is_hosted():
        st.warning(privacy_notice(), icon="☁️")
    else:
        st.caption(privacy_notice())
    tab_upload, tab_quality, tab_dict = st.tabs(["Yükleme", "Veri kalite raporu", "Veri sözlüğü ve şablonlar"])
    with tab_upload:
        _upload_section()
    with tab_quality:
        _quality_section()
    with tab_dict:
        _dictionary_section()


def _upload_section() -> None:
    ds = c.dataset()
    if ds is not None:
        label = ds.source_label or "Kullanıcı verisi"
        st.success(f"Yüklü veri: **{label}** — " + ", ".join(f"{TABLE_LABELS[t]}: {len(df)} satır"
                                                           for t, df in ds.tables.items()))
        if ds.is_synthetic:
            st.warning("Bu veri sentetiktir (deterministik demo üreticisi). Gerçek depo sonuçları gibi sunulmamalıdır.")

    st.markdown("#### Demo modu")
    if st.button("Sentetik demo verisini yükle", type="primary"):
        c.load_demo()
        st.rerun()
    st.caption("80 SKU, 280 lokasyon, 8 koridor, 400 sipariş; sabit seed=42. Tüm akışı uçtan uca denemek içindir.")

    st.markdown("#### Kendi verinizi yükleyin")
    s = c.settings()
    u1, u2 = st.columns(2)
    dim = u1.selectbox("Dosyalardaki boyut birimi", ["m", "cm", "mm"], index=["m", "cm", "mm"].index(s["units"]["dimension"]))
    wgt = u2.selectbox("Dosyalardaki ağırlık birimi", ["kg", "g", "t"], index=["kg", "g", "t"].index(s["units"]["weight"]))
    st.caption("Boyutlar metreye, ağırlıklar kilograma çevrilir. Koordinatlar (x, y, z) her zaman metre kabul edilir.")

    mode = st.radio("Yükleme şekli", ["Tablo başına ayrı dosya", "Tek Excel çalışma kitabı (sayfa adları tablo adı)"],
                    horizontal=True)
    uploads: dict[str, object] = {}
    if mode.startswith("Tablo"):
        cols = st.columns(2)
        for i, table in enumerate(list(REQUIRED_TABLES) + ["aisles"]):
            req = "zorunlu" if table in REQUIRED_TABLES else "opsiyonel"
            uploads[table] = cols[i % 2].file_uploader(f"{TABLE_LABELS[table]} ({table}, {req})",
                                                       type=["csv", "xlsx"], key=f"up_{table}")
    else:
        workbook = st.file_uploader("Çalışma kitabı (.xlsx)", type=["xlsx"], key="up_workbook")
        if workbook is not None:
            uploads["__workbook__"] = workbook

    d1, d2 = st.columns(2)
    dock_x = d1.number_input("Sevkiyat noktası X (m)", value=None, placeholder="opsiyonel")
    dock_y = d2.number_input("Sevkiyat noktası Y (m)", value=None, placeholder="opsiyonel")

    if st.button("Yüklenen dosyaları analiz et"):
        tables: dict[str, pd.DataFrame] = {}
        errors = []
        if "__workbook__" in uploads:
            wb = uploads["__workbook__"]
            data = wb.getvalue()
            sheets = pd.ExcelFile(io.BytesIO(data), engine="openpyxl").sheet_names
            for table in SCHEMAS:
                if table in sheets:
                    tables[table] = read_table(data, wb.name, sheet_name=table)
        else:
            for table, up in uploads.items():
                if up is None:
                    continue
                try:
                    tables[table] = read_table(up.getvalue(), up.name)
                except Exception as exc:  # noqa: BLE001 - show any parser error to the user
                    errors.append(f"{TABLE_LABELS[table]}: {exc}")
        missing = [TABLE_LABELS[t] for t in REQUIRED_TABLES if t not in tables]
        if errors:
            st.error("Dosya okunamadı: " + "; ".join(errors))
        elif missing:
            st.error("Eksik zorunlu tablo: " + ", ".join(missing))
        else:
            s["units"]["dimension"], s["units"]["weight"] = dim, wgt
            dock = (float(dock_x), float(dock_y)) if dock_x is not None and dock_y is not None else None
            c.set_dataset(Dataset(tables=tables, is_synthetic=False, source_label="Kullanıcı verisi", dock_xy=dock))
            st.success("Veri yüklendi. Veri kalite raporunu inceleyin.")
            st.rerun()


def _quality_section() -> None:
    if c.dataset() is None:
        st.info("Önce veri yükleyin.")
        return
    res = c.result()
    c.provenance_banner(res)
    v = res.validation
    rows = [{"Tablo": TABLE_LABELS.get(t, t), "Girdi satırı": n["input"], "Geçerli satır": n["valid"]}
            for t, n in v.row_counts.items()]
    k = st.columns(3)
    k[0].metric("Hata", v.error_count)
    k[1].metric("Uyarı", v.warning_count)
    k[2].metric("Eksik zorunlu tablo", len(v.missing_tables()))
    st.dataframe(pd.DataFrame(rows), hide_index=True)
    st.caption("Geçerli satır: hatalı satırlar çıkarıldıktan ve yinelenen satırlar birleştirildikten sonraki sayı. "
               "Değerler sessizce düzeltilmez; analiz dışı kalan her kayıt aşağıda listelenir.")
    issues = v.issues.copy()
    if issues.empty:
        st.success("Doğrulama sorunu bulunmadı.")
        return
    sev = st.multiselect("Önem", ["hata", "uyarı", "bilgi"], default=["hata", "uyarı", "bilgi"])
    tables = st.multiselect("Tablo", sorted(issues["table"].unique()), default=sorted(issues["table"].unique()))
    shown = issues[issues["severity"].isin(sev) & issues["table"].isin(tables)]
    shown = shown.sort_values(["severity", "table", "row"], key=lambda col: col.map(SEVERITY_ORDER)
                              if col.name == "severity" else col, kind="mergesort")
    st.dataframe(localize(shown), hide_index=True)
    meta = {"Veri kaynağı": c.dataset().source_label, "Satır no": "Dosya satırı (başlık = 1)"}
    c.download_pair("Veri kalite raporu", localize(issues), "veri_kalite_raporu", meta, "dq")


def _dictionary_section() -> None:
    st.dataframe(pd.DataFrame(data_dictionary_rows()), hide_index=True)
    st.markdown("**Şablonlar** (örnek satırlı)")
    cols = st.columns(len(SCHEMAS))
    for col, table in zip(cols, SCHEMAS):
        path = TEMPLATE_DIR / f"{table}_template.csv"
        if path.exists():
            col.download_button(table, path.read_bytes(), path.name, "text/csv", key=f"tpl_{table}")
    all_templates = {t: pd.read_csv(TEMPLATE_DIR / f"{t}_template.csv", dtype=str)
                     for t in SCHEMAS if (TEMPLATE_DIR / f"{t}_template.csv").exists()}
    if all_templates:
        st.download_button("Tüm şablonlar — tek XLSX", to_excel_bytes(all_templates), "sablonlar.xlsx",
                           "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    st.caption("Bir SKU birden fazla lokasyonda bulunabilir (stok tablosunda birden çok satır). Stok seviyesi geçmiş "
               "çıkışlardan türetilmez; stok tablosu ayrıca sağlanmalıdır.")
