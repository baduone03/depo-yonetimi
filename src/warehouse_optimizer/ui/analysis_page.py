"""ABC ve Hareket Analizi page."""
from __future__ import annotations

import streamlit as st

from ..analytics.movement_analysis import METRIC_LABELS, daily_activity
from ..layout import visualization as viz
from ..pipeline import report_metadata
from ..reporting.exports import localize
from . import common as c


def render() -> None:
    c.page_header("ABC ve Hareket Analizi")
    res = c.require_result()
    if res is None:
        return
    c.provenance_banner(res)
    s = c.settings()
    a = s["analysis"]

    with st.expander("Analiz parametreleri", expanded=False):
        with st.form("abc_params"):
            p1, p2, p3, p4 = st.columns(4)
            metric = p1.selectbox("Metrik", list(METRIC_LABELS), index=list(METRIC_LABELS).index(a["metric"]),
                                  format_func=METRIC_LABELS.get)
            days = p2.number_input("Dönem (gün)", 7, 3650, int(a["period_days"]))
            a_share = p3.number_input("A eşiği (%)", 1.0, 99.0, a["a_share"] * 100, step=1.0)
            b_share = p4.number_input("B eşiği (%)", 0.0, 98.0, a["b_share"] * 100, step=1.0)
            if st.form_submit_button("Uygula"):
                if a_share + b_share > 100:
                    st.error("A + B eşiği %100'ü aşamaz.")
                else:
                    a.update(metric=metric, period_days=int(days), a_share=a_share / 100, b_share=b_share / 100)
                    st.rerun()

    st.markdown(f"**Dönem:** {res.period.label()} · **Metrik:** {METRIC_LABELS[a['metric']]} · "
                f"**Eşikler:** A %{a['a_share'] * 100:.0f}, B %{a['b_share'] * 100:.0f}, C kalan")
    if res.period.note:
        st.warning(res.period.note)
    if not res.abc.defined:
        st.warning("Dönemde çıkış hareketi olmadığından ABC sınıflandırması tanımsız; tüm SKU'lar C gösterilir.")
    st.caption("Sınıflandırma SKU sayısına göre değil, metriğin kümülatif katkısına göredir. Sıralama: metrik azalan, "
               "eşitlikte SKU kodu artan. Kümülatif payı (kendisinden önce) A eşiğinin altında olan SKU A'dır; "
               "hareketi olmayan SKU'lar C'dir. İade ve iptaller dahil değildir.")

    table = res.sku_table()
    l, r = st.columns(2)
    l.plotly_chart(viz.pareto_chart(table, a["a_share"], a["b_share"], METRIC_LABELS[a["metric"]]), theme=None,
                   config=viz.CHART_CONFIG)
    r.plotly_chart(viz.abc_distribution_chart(table), theme=None, config=viz.CHART_CONFIG)
    st.plotly_chart(viz.frequency_chart(table, res.period.days), theme=None, config=viz.CHART_CONFIG)
    daily = daily_activity(res.validation.tables["order_lines"], res.period)
    if not daily.empty:
        st.plotly_chart(viz.daily_activity_chart(daily), theme=None, config=viz.CHART_CONFIG)

    st.subheader("SKU tablosu")
    f1, f2 = st.columns([1, 3])
    classes = f1.multiselect("Sınıf", ["A", "B", "C"], default=["A", "B", "C"])
    query = f2.text_input("SKU / ürün adı ara")
    shown = table[table["abc_class"].isin(classes)]
    if query:
        mask = shown["sku"].str.contains(query, case=False) | shown["product_name"].fillna("").str.contains(query, case=False)
        shown = shown[mask]
    cols = ["rank", "sku", "product_name", "abc_class", "quantity", "order_lines", "active_days", "share",
            "cumulative_share", "current_location", "current_dock_distance_m", "proposed_location",
            "proposed_dock_distance_m"]
    st.dataframe(localize(shown[cols]), hide_index=True, column_config={
        "Pay": st.column_config.NumberColumn(format="percent"),
        "Kümülatif pay": st.column_config.NumberColumn(format="percent"),
        "Mevcut erişim mesafesi (m)": st.column_config.NumberColumn(format="%.1f"),
        "Önerilen erişim mesafesi (m)": st.column_config.NumberColumn(format="%.1f"),
    })
    st.caption("Erişim mesafesi: lokasyonun erişim noktasından sevkiyat noktasına tek yön en kısa yol. "
               "Önerilen lokasyon, seçili yerleşim yöntemine göredir.")
    c.download_pair("ABC analizi", localize(table[cols]), "abc_analizi", report_metadata(res), "abc")
