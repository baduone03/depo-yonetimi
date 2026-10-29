"""Taşıma Planı page."""
from __future__ import annotations

import streamlit as st

from ..optimization.slotting_engine import METHOD_LABELS
from ..pipeline import report_metadata
from ..reporting.exports import localize
from . import common as c

PLAN_COLUMNS = ["sequence", "sku", "product_name", "abc_class", "from_location", "to_location", "move_type",
                "order_lines", "current_dock_distance_m", "proposed_dock_distance_m", "estimated_travel_saving_m",
                "reason", "constraint_check"]


def render() -> None:
    c.page_header("Taşıma Planı")
    res = c.require_result()
    if res is None:
        return
    c.provenance_banner(res)
    method = res.selected_method
    plan = res.move_plans[method]
    st.markdown(f"**Yöntem:** {METHOD_LABELS[method]}")
    st.info("Bu plan yalnızca bir öneridir. Uygulama hiçbir stok hareketi yapmaz ve harici WMS sistemlerine değişiklik "
            "göndermez. Taşımalar **Uygulama sırası** kolonuna göre yürütülmelidir: yer açma taşımaları, ilgili "
            "lokasyona yapılacak taşımadan önce gelir.", icon="ℹ️")
    if plan.empty:
        st.warning("Önerilen taşıma yok. Taşıma eşiğini düşürmeyi veya maksimum taşıma sayısını artırmayı "
                   "deneyebilirsiniz.")
        return
    k = st.columns(4)
    k[0].metric("Taşıma hareketi", len(plan))
    k[1].metric("Yer açma taşıması", int((plan["move_type"] == "evict").sum()))
    k[2].metric("Kısıt kontrolünden geçen", int((plan["constraint_check"] == "Geçti").sum()))
    k[3].metric("Toplam tahmini katkı (proxy)", c.fmt_num(plan["estimated_travel_saving_m"].sum(), 0, " m"))
    violations = plan[plan["constraint_check"] != "Geçti"]
    if not violations.empty:
        st.error(f"{len(violations)} taşıma bağımsız kısıt kontrolünden geçemedi; bunları uygulamayın.")
    st.dataframe(localize(plan[PLAN_COLUMNS]), hide_index=True, column_config={
        "Mevcut erişim mesafesi (m)": st.column_config.NumberColumn(format="%.1f"),
        "Önerilen erişim mesafesi (m)": st.column_config.NumberColumn(format="%.1f"),
        "Tahmini katkı (m/dönem, tek-sefer proxy)": st.column_config.NumberColumn(format="%.0f"),
    })
    st.caption("Sıralama: taşıma grubunun puan kazancına göre (azalan). Tahmini katkı = dönem sipariş satırı × 2 × "
               "erişim mesafesi farkı; her satır ayrı bir tur gibi varsayılan kaba bir göstergedir. Gerçekçi etki için "
               "Önce/Sonra Simülasyonu sayfasına bakın. Kısıt kontrolü her taşımayı motordan bağımsız olarak yeniden "
               "doğrular (boyut, ağırlık, hacim, istif, depolama koşulu, elleçleme, hedefin boş olması).")
    c.download_pair("Taşıma planı", localize(plan[PLAN_COLUMNS]), "tasima_plani", report_metadata(res), "plan")
