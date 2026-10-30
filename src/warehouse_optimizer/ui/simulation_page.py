"""Önce / Sonra Simülasyonu page."""
from __future__ import annotations

import streamlit as st

from ..layout import visualization as viz
from ..optimization.slotting_engine import METHOD_LABELS
from ..pipeline import report_metadata
from ..reporting.exports import kpi_frame, localize
from . import common as c


def render() -> None:
    c.page_header("Önce / Sonra Simülasyonu",
                  "Aynı siparişler, aynı rota modeli ve aynı parametrelerle mevcut ve önerilen yerleşim")
    res = c.require_result()
    if res is None:
        return
    c.provenance_banner(res)
    o = c.settings()["operations"]

    with st.form("ops"):
        p = st.columns(5)
        speed = p[0].number_input("Yürüme hızı (m/s)", 0.1, 5.0, float(o["walking_speed_m_s"]), step=0.1)
        pick = p[1].number_input("Toplama süresi (sn/durak, 0 = bilinmiyor)", 0.0, 600.0,
                                 float(o["pick_time_s_per_stop"] or 0))
        daily = p[2].number_input("Günlük sipariş (boş = veriden)", min_value=0.0, value=o["daily_orders"],
                                  placeholder="veriden türet")
        days = p[3].number_input("Operasyon günü (boş = projeksiyon yok)", min_value=0, value=o["operating_days"],
                                 placeholder="girilmedi")
        cost = p[4].number_input("Saatlik işçilik maliyeti (boş = yok)", min_value=0.0, value=o["hourly_labor_cost"],
                                 placeholder="girilmedi")
        if st.form_submit_button("Uygula"):
            o.update(walking_speed_m_s=speed, pick_time_s_per_stop=pick, daily_orders=daily or None,
                     operating_days=int(days) if days else None, hourly_labor_cost=cost or None)
            st.rerun()

    method = res.selected_method
    comp = res.comparisons[method]
    s = comp.summary
    st.subheader(METHOD_LABELS[method])
    if s.get("orders_compared", 0) == 0:
        st.warning("Karşılaştırılabilir sipariş yok.")
        return

    k = st.columns(4)
    k[0].metric("Toplam mesafe — mevcut", c.fmt_num(s["total_current_m"], 0, " m"))
    k[1].metric("Toplam mesafe — önerilen", c.fmt_num(s["total_proposed_m"], 0, " m"),
                delta=c.fmt_num(-s["difference_m"], 0, " m"), delta_color="inverse")
    k[2].metric("İyileşme", c.fmt_pct(s["improvement_pct"]))
    k[3].metric("Karşılaştırılan sipariş", s["orders_compared"])
    k = st.columns(4)
    k[0].metric("Ortalama / sipariş", f"{c.fmt_num(s['mean_current_m'], 1)} → {c.fmt_num(s['mean_proposed_m'], 1)} m")
    k[1].metric("Medyan / sipariş", f"{c.fmt_num(s['median_current_m'], 1)} → {c.fmt_num(s['median_proposed_m'], 1)} m")
    k[2].metric("Toplam durak", f"{s['stops_current']} → {s['stops_proposed']}")
    k[3].metric("Tahmini süre", f"{c.fmt_num(s['time_current_h'], 1)} → {c.fmt_num(s['time_proposed_h'], 1)} sa",
                help="Yürüme + toplama" if s.get("time_includes_pick_time") else "Yalnızca yürüme süresi")
    if s["improvement_pct"] < 0:
        st.error(f"Önerilen yerleşim toplam mesafeyi %{abs(s['improvement_pct']):.1f} ARTIRIYOR.")
    st.caption(f"İyileşen sipariş: {s['orders_improved']} · kötüleşen: {s['orders_worse']} · "
               "iyileşme % = (mevcut − önerilen) / mevcut × 100")

    l, r = st.columns([3, 2])
    l.plotly_chart(viz.order_distance_scatter(comp.per_order), theme=None)
    r.plotly_chart(viz.distance_distribution_chart(comp.per_order), theme=None)

    st.subheader("Dönemsel projeksiyon (tahmini)")
    k = st.columns(4)
    k[0].metric("Günlük sipariş", c.fmt_num(s.get("daily_orders"), 1), help=s.get("daily_orders_source", ""))
    k[1].metric("Sipariş başına zaman farkı", c.fmt_num(s.get("time_saving_per_order_s"), 1, " sn"))
    k[2].metric("Kazanılan saat", c.fmt_num(s.get("projected_hours_saved"), 0, " sa", c.DATA_REQUIRED))
    k[3].metric("İşçilik maliyet farkı", c.fmt_num(s.get("projected_labor_cost_saved"), 0, "", c.DATA_REQUIRED))
    st.warning("Projeksiyon, simüle edilen siparişlerin ortalamasının girilen gün ve sipariş sayısına ölçeklenmesidir. "
               "Kesin finansal tasarruf değildir. Taşıma işçiliği, yeniden stoklama, operasyon kesintisi, sipariş "
               "profili değişimi ve kapasite değişiklikleri hesaba katılmamıştır.")
    for note in comp.notes:
        st.caption("• " + note)

    st.subheader("Sipariş bazında karşılaştırma")
    st.dataframe(localize(comp.per_order), hide_index=True, column_config={
        "Mesafe mevcut (m)": st.column_config.NumberColumn(format="%.1f"),
        "Mesafe önerilen (m)": st.column_config.NumberColumn(format="%.1f"),
        "Fark (m)": st.column_config.NumberColumn(format="%.1f"),
        "Değişim (%)": st.column_config.NumberColumn(format="%.1f"),
    })
    if not comp.excluded.empty:
        st.markdown("**Karşılaştırma dışı siparişler**")
        st.dataframe(comp.excluded, hide_index=True)
    meta = report_metadata(res)
    c.download_pair("Rota karşılaştırması", localize(comp.per_order), "rota_karsilastirmasi", meta, "route")
    c.download_pair("KPI raporu", kpi_frame(s), "once_sonra_kpi", meta, "kpi")
