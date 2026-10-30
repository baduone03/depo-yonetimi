"""Shared Streamlit helpers: session state, cached pipeline run, formatting, downloads."""
from __future__ import annotations

import copy
import hashlib
import json
import math

import pandas as pd
import streamlit as st

from ..data.loaders import Dataset
from ..pipeline import PipelineResult, run_pipeline
from ..reporting.exports import to_csv_bytes, to_excel_bytes
from ..settings import load_settings

NOT_AVAILABLE = "Hesaplanamadı"
DATA_REQUIRED = "Veri gerekli"


def settings() -> dict:
    if "settings" not in st.session_state:
        st.session_state["settings"] = load_settings()
    return st.session_state["settings"]


def update_settings(new_settings: dict) -> None:
    st.session_state["settings"] = copy.deepcopy(new_settings)


def dataset() -> Dataset | None:
    return st.session_state.get("dataset")


def set_dataset(ds: Dataset) -> None:
    st.session_state["dataset"] = ds
    st.session_state["dataset_token"] = st.session_state.get("dataset_token", 0) + 1
    st.session_state.pop("result", None)
    st.session_state.pop("result_key", None)
    if ds.dock_xy is not None:
        s = settings()
        s["geometry"]["dock_x"], s["geometry"]["dock_y"] = None, None


def result() -> PipelineResult | None:
    ds = dataset()
    if ds is None:
        return None
    key = hashlib.sha1((str(st.session_state.get("dataset_token")) +
                        json.dumps(settings(), sort_keys=True, default=str)).encode()).hexdigest()
    if st.session_state.get("result_key") != key:
        with st.spinner("Analiz çalışıyor: doğrulama, ABC, yerleşim, rota ve simülasyon..."):
            st.session_state["result"] = run_pipeline(ds, copy.deepcopy(settings()))
        st.session_state["result_key"] = key
    return st.session_state["result"]


def require_result() -> PipelineResult | None:
    """Return a usable result, or render guidance and return None."""
    ds = dataset()
    if ds is None:
        st.info("Henüz veri yüklenmedi. **Veri Yükleme** sayfasından dosyalarınızı yükleyin veya demo veriyle "
                "deneyin.")
        if st.button("Sentetik demo verisini yükle", type="primary", key=f"demo_{st.session_state.get('page', '')}"):
            load_demo()
            st.rerun()
        return None
    res = result()
    if not res.ok:
        st.error("Analiz yapılamadı: " + "; ".join(res.errors))
        st.caption("Ayrıntılar için Veri Yükleme ve Veri Kalitesi sayfasına bakın.")
        return None
    return res


def load_demo() -> None:
    from ..data.demo_generator import generate_demo_dataset

    set_dataset(generate_demo_dataset())


def provenance_banner(res: PipelineResult | None) -> None:
    if res is None:
        return
    if res.is_synthetic:
        st.warning("**Sentetik demo verisi.** Bu ekrandaki tüm sonuçlar yapay veriyle üretilmiştir ve gerçek bir "
                   "deponun performansını göstermez.", icon="⚠️")
    if res.distance_is_estimate:
        st.warning("**Tahmini mesafe modu.** Mesafeler koordinatlar arası Manhattan mesafesidir; koridor ağı "
                   "kullanılmadığı için gerçek yürüme mesafesi değildir.", icon="📐")
    elif res.geometry is not None and res.geometry.is_approximate:
        st.info("Depo geometrisi kısmen türetilmiş veya varsayılan değerlerle kurulmuştur. Ayrıntı: Ayarlar ve "
                "Raporlar → Varsayımlar.", icon="ℹ️")


def is_missing(value) -> bool:
    return value is None or (isinstance(value, float) and (math.isnan(value) or math.isinf(value)))


def fmt_num(value, digits: int = 0, suffix: str = "", missing: str = NOT_AVAILABLE) -> str:
    if is_missing(value):
        return missing
    text = f"{value:,.{digits}f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"{text}{suffix}"


def fmt_pct(value, digits: int = 1) -> str:
    if is_missing(value):
        return NOT_AVAILABLE
    return fmt_num(value, digits, " %")


def download_pair(label: str, df: pd.DataFrame, file_stem: str, metadata: dict | None, key: str) -> None:
    c1, c2 = st.columns(2)
    c1.download_button(f"{label} — CSV", to_csv_bytes(df, metadata), f"{file_stem}.csv", "text/csv",
                       key=f"{key}_csv", width="stretch")
    c2.download_button(f"{label} — XLSX", to_excel_bytes({label[:31]: df}, metadata), f"{file_stem}.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", key=f"{key}_xlsx",
                       width="stretch")


def map_plot_width() -> int:
    """Rough plot width for sizing the warehouse map: narrow on phones, wide otherwise."""
    try:
        agent = st.context.headers.get("User-Agent", "") or ""
    except Exception:  # noqa: BLE001 - st.context is unavailable in some test runners
        agent = ""
    return 340 if any(token in agent for token in ("iPhone", "Android", "Mobile")) else 900


def page_header(title: str, subtitle: str = "") -> None:
    st.title(title)
    if subtitle:
        st.caption(subtitle)
