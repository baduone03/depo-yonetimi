"""Streamlit entry point: `streamlit run app.py`."""
from __future__ import annotations

import sys
from pathlib import Path

SRC = Path(__file__).resolve().parent / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

import streamlit as st  # noqa: E402

from warehouse_optimizer.hosting import privacy_notice  # noqa: E402
from warehouse_optimizer.ui import (analysis_page, dashboard, data_page, layout_page, move_plan_page,  # noqa: E402
                                    optimization_page, reports_page, routing_page, settings_page, simulation_page)

st.set_page_config(page_title="Warehouse Intelligence & Slotting Optimizer", page_icon="📦", layout="wide")

PAGES = [
    st.Page(dashboard.render, title="Genel Bakış", icon="📊", url_path="genel-bakis", default=True),
    st.Page(data_page.render, title="Veri Yükleme ve Veri Kalitesi", icon="📥", url_path="veri"),
    st.Page(analysis_page.render, title="ABC ve Hareket Analizi", icon="📈", url_path="abc"),
    st.Page(layout_page.render, title="Depo Yerleşim Haritası", icon="🗺️", url_path="harita"),
    st.Page(optimization_page.render, title="Yerleşim Optimizasyonu", icon="🧩", url_path="optimizasyon"),
    st.Page(routing_page.render, title="Rota ve Mesafe Analizi", icon="🚶", url_path="rota"),
    st.Page(simulation_page.render, title="Önce / Sonra Simülasyonu", icon="⚖️", url_path="simulasyon"),
    st.Page(move_plan_page.render, title="Taşıma Planı", icon="📋", url_path="tasima-plani"),
    st.Page(reports_page.render, title="Raporlar", icon="📑", url_path="raporlar"),
    st.Page(settings_page.render, title="Ayarlar", icon="⚙️", url_path="ayarlar"),
]

nav = st.navigation(PAGES)
with st.sidebar:
    ds = st.session_state.get("dataset")
    if ds is None:
        st.caption("Veri yüklenmedi")
    elif ds.is_synthetic:
        st.warning("SENTETİK DEMO VERİSİ")
    else:
        st.caption("Kullanıcı verisi yüklü")
    st.caption(privacy_notice(short=True))
nav.run()
