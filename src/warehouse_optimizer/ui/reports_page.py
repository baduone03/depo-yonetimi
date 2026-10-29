"""Raporlar page."""
from __future__ import annotations

import streamlit as st

from ..reporting.exports import to_excel_bytes
from ..reporting.report_builder import REPORT_TITLES, build_reports, report_bundle_metadata
from . import common as c

FILE_STEMS = {
    "abc": "abc_analizi", "movement": "urun_hareket_analizi", "data_quality": "veri_kalite_raporu",
    "current_placement": "mevcut_yerlesim", "proposed_placement": "onerilen_yerlesim", "move_plan": "tasima_plani",
    "route_comparison": "rota_karsilastirmasi", "kpi": "once_sonra_kpi", "method_comparison": "yontem_karsilastirmasi",
    "constraints": "kisit_ihlalleri_atanamayanlar", "assumptions": "varsayimlar_sinirlamalar",
}


def render() -> None:
    c.page_header("Raporlar", "Her rapor analiz dönemi, metrik, parametreler ve hesaplama yöntemi bilgisini içerir.")
    if c.dataset() is None:
        c.require_result()
        return
    res = c.result()
    c.provenance_banner(res)
    reports = build_reports(res)
    meta = report_bundle_metadata(res)
    with st.expander("Rapor bilgisi (tüm dosyalara eklenir)", expanded=True):
        for k, v in meta.items():
            st.markdown(f"- **{k}:** {v}")
    st.download_button("Tüm raporlar — tek XLSX çalışma kitabı",
                       to_excel_bytes({REPORT_TITLES[k]: v for k, v in reports.items()}, meta),
                       "depo_analiz_raporlari.xlsx",
                       "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", type="primary")
    st.divider()
    for key, df in reports.items():
        st.markdown(f"**{REPORT_TITLES[key]}** · {len(df)} satır")
        c.download_pair(REPORT_TITLES[key], df, FILE_STEMS[key], meta, f"rep_{key}")
    st.divider()
    st.subheader("Varsayımlar ve bilinen sınırlamalar")
    for item in reports["assumptions"]["Madde"]:
        st.markdown(f"- {item}")
