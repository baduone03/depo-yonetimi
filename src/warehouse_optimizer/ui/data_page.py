"""Veri Yükleme ve Veri Kalitesi page."""
from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pandas as pd
import streamlit as st

from ..data.column_mapping import (NONE_OPTION, apply_mapping, duplicate_sources, mapping_from_json, mapping_to_json,
                                   missing_required, resolve_with_profile, suggest_sheet, unit_hints)
from ..data.loaders import Dataset, excel_sheet_names, read_table
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
    _user_data_flow()


@st.cache_data(show_spinner=False, max_entries=32)
def _read_cached(data: bytes, name: str, sheet: str | int = 0) -> pd.DataFrame:
    return read_table(data, name, sheet_name=sheet, normalize_columns=False)


@st.cache_data(show_spinner=False, max_entries=8)
def _sheets_cached(data: bytes) -> list[str]:
    return excel_sheet_names(data)


def _file_token(up) -> str:
    return hashlib.sha1(up.getvalue()).hexdigest()[:10]


def _sample(df: pd.DataFrame, col: str) -> str:
    values = df[col][df[col] != ""]
    return str(values.iloc[0])[:24] if len(values) else "boş"


def _user_data_flow() -> None:
    s = c.settings()
    profile = st.session_state.get("mapping_profile")

    st.markdown("**1. Dosyalar**")
    mode = st.radio("Yükleme şekli", ["Tek Excel çalışma kitabı (her tablo bir sayfada)", "Tablo başına ayrı dosya"],
                    horizontal=True, label_visibility="collapsed")
    with st.expander("Kayıtlı eşleştirme dosyası (opsiyonel)"):
        saved = st.file_uploader("Daha önce indirdiğiniz eslestirme.json", type=["json"], key="up_mapping")
        if saved is not None:
            try:
                profile = mapping_from_json(saved.getvalue())
                st.session_state["mapping_profile"] = profile
                st.success("Eşleştirme dosyası yüklendi; öneriler bu dosyaya göre dolduruldu.")
            except ValueError as exc:
                st.error(str(exc))

    raw: dict[str, pd.DataFrame] = {}
    tokens: dict[str, str] = {}
    sheets_used: dict[str, str | None] = {}
    errors: list[str] = []
    tables = list(REQUIRED_TABLES) + ["aisles"]
    if mode.startswith("Tek Excel"):
        wb = st.file_uploader("Çalışma kitabı (.xlsx)", type=["xlsx"], key="up_workbook")
        if wb is None:
            st.caption("Ürünler, sipariş satırları, lokasyonlar ve stok ayrı sayfalarda olmalı. Sayfa adları serbest; "
                       "bir sonraki adımda hangi sayfanın hangi tablo olduğunu seçersiniz.")
            return
        data = wb.getvalue()
        try:
            sheet_names = _sheets_cached(data)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Çalışma kitabı okunamadı: {exc}")
            return
        st.markdown("**2. Hangi sayfa hangi tablo?**")
        cols = st.columns(2)
        options = [NONE_OPTION] + sheet_names
        for i, table in enumerate(tables):
            saved_sheet = (profile or {}).get("sheets", {}).get(table)
            default = saved_sheet if saved_sheet in sheet_names else suggest_sheet(table, sheet_names)
            req = "zorunlu" if table in REQUIRED_TABLES else "opsiyonel"
            choice = cols[i % 2].selectbox(f"{TABLE_LABELS[table]} ({req})", options,
                                           index=options.index(default) if default else 0,
                                           key=f"sheet_{table}_{_file_token(wb)}")
            if choice != NONE_OPTION:
                try:
                    raw[table] = _read_cached(data, wb.name, choice)
                    tokens[table] = f"{_file_token(wb)}_{choice}"
                    sheets_used[table] = choice
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{choice}: {exc}")
    else:
        cols = st.columns(2)
        for i, table in enumerate(tables):
            req = "zorunlu" if table in REQUIRED_TABLES else "opsiyonel"
            up = cols[i % 2].file_uploader(f"{TABLE_LABELS[table]} ({req})", type=["csv", "xlsx"], key=f"up_{table}")
            if up is not None:
                try:
                    raw[table] = _read_cached(up.getvalue(), up.name)
                    tokens[table] = _file_token(up)
                except Exception as exc:  # noqa: BLE001
                    errors.append(f"{TABLE_LABELS[table]}: {exc}")
    if errors:
        st.error("Dosya okunamadı: " + "; ".join(errors))
    if not raw:
        return

    st.markdown("**3. Birimler**")
    units = (profile or {}).get("units", {})
    dim_default = units.get("dimension", s["units"]["dimension"])
    wgt_default = units.get("weight", s["units"]["weight"])
    vol_default = units.get("volume", s["units"].get("volume", "m3"))
    u1, u2, u3 = st.columns(3)
    dim = u1.selectbox("Boyut birimi (ürün ve lokasyon ölçüleri)", ["m", "cm", "mm"],
                       index=["m", "cm", "mm"].index(dim_default if dim_default in ("m", "cm", "mm") else "m"))
    wgt = u2.selectbox("Ağırlık birimi", ["kg", "g", "t"],
                       index=["kg", "g", "t"].index(wgt_default if wgt_default in ("kg", "g", "t") else "kg"))
    vol_options = ["m3", "dm3", "cm3", "mm3"]
    vol = u3.selectbox("Lokasyon hacim birimi", vol_options,
                       index=vol_options.index(vol_default if vol_default in vol_options else "m3"),
                       format_func={"m3": "m³", "dm3": "litre (dm³)", "cm3": "cm³", "mm3": "mm³"}.get)
    st.caption("Koordinatlar (x, y, z) her zaman metre kabul edilir. Sayılarda 12,5 / 1.234,5 / 1,234.5 biçimleri "
               "desteklenir.")

    st.markdown("**4. Kolon eşleştirme**")
    st.caption("Her alan için dosyanızdaki kolonu seçin. Öneriler kolon adlarından otomatik doldurulur; lütfen "
               "kontrol edin. Parantez içinde ilk satırdaki örnek değer görünür.")
    mappings: dict[str, dict[str, str | None]] = {}
    blocking: list[str] = []
    for table in tables:
        if table not in raw:
            continue
        df = raw[table]
        columns = list(df.columns)
        suggested = resolve_with_profile(table, columns, profile)
        with st.expander(f"{TABLE_LABELS[table]} — {len(df)} satır, {len(columns)} kolon",
                         expanded=bool(missing_required(table, suggested))):
            options = [NONE_OPTION] + columns
            mapping: dict[str, str | None] = {}
            specs = SCHEMAS[table]
            for i, spec in enumerate(specs):
                if i % 2 == 0:
                    grid = st.columns(2)  # one row per pair keeps schema order when stacked on phones
                default = suggested.get(spec.name)
                short = re.split(r"[,.(]", spec.description)[0].strip()
                label = f"{short}{' *' if spec.required else ''} · {spec.name}"
                choice = grid[i % 2].selectbox(
                    label, options, index=options.index(default) if default in options else 0,
                    key=f"map_{table}_{spec.name}_{tokens[table]}", help=spec.description,
                    format_func=lambda col, d=df: col if col == NONE_OPTION else f"{col}  ({_sample(d, col)})")
                mapping[spec.name] = None if choice == NONE_OPTION else choice
            mappings[table] = mapping
            miss = missing_required(table, mapping)
            if miss:
                st.error("Zorunlu alan eşleşmedi: " + ", ".join(miss))
                blocking.append(f"{TABLE_LABELS[table]}: {', '.join(miss)}")
            for src, targets in duplicate_sources(mapping).items():
                st.warning(f"'{src}' kolonu birden fazla alana atanmış: {', '.join(targets)}")
            for hint in unit_hints(table, mapping, {"dimension": dim, "weight": wgt, "volume": vol}):
                st.info(hint)
            st.caption("Önizleme (eşleştirilmiş ilk 5 satır)")
            st.dataframe(apply_mapping(df, mapping).head(5), hide_index=True)
    missing_tables = [TABLE_LABELS[t] for t in REQUIRED_TABLES if t not in raw]
    if missing_tables:
        blocking.append("Eksik tablo: " + ", ".join(missing_tables))
    if "locations" in mappings and not (mappings["locations"].get("x") and mappings["locations"].get("y")):
        st.info("Lokasyon koordinatları (x, y) olmadan mesafe hesaplanamaz.")

    st.markdown("**5. Sevkiyat noktası**")
    d1, d2 = st.columns(2)
    dock_x = d1.number_input("Sevkiyat noktası X (m)", value=None, placeholder="opsiyonel")
    dock_y = d2.number_input("Sevkiyat noktası Y (m)", value=None, placeholder="opsiyonel")
    st.caption("Toplama turlarının başladığı/bittiği nokta, lokasyonlarla aynı koordinat sisteminde. Boş bırakılırsa "
               "varsayılan konum kullanılır ve sonuçlarda belirtilir.")

    st.markdown("**6. Analiz**")
    if blocking:
        st.warning("Analiz için tamamlanması gerekenler: " + " · ".join(blocking))
    b1, b2 = st.columns(2)
    if b1.button("Eşleştirmeyi uygula ve analiz et", type="primary", disabled=bool(blocking)):
        mapped = {t: apply_mapping(raw[t], m) for t, m in mappings.items()}
        s["units"]["dimension"], s["units"]["weight"], s["units"]["volume"] = dim, wgt, vol
        dock = (float(dock_x), float(dock_y)) if dock_x is not None and dock_y is not None else None
        st.session_state["mapping_profile"] = mapping_from_json(
            mapping_to_json(mappings, sheets_used, {"dimension": dim, "weight": wgt, "volume": vol}))
        c.set_dataset(Dataset(tables=mapped, is_synthetic=False, source_label="Kullanıcı verisi", dock_xy=dock))
        st.success("Veri yüklendi. Sonuçları Veri kalite raporu sekmesinde kontrol edin.")
        st.rerun()
    profile_json = mapping_to_json(mappings, sheets_used, {"dimension": dim, "weight": wgt, "volume": vol})
    b2.download_button("Eşleştirmeyi kaydet (.json)", profile_json.encode("utf-8"),
                       "eslestirme.json", "application/json",
                       help="Aynı formattaki bir sonraki dosyada tekrar seçim yapmamak için.")


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
    shown = shown.assign(row=shown["row"].astype(object).where(shown["row"].notna(), "—"))
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
