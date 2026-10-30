"""Yerleşim Optimizasyonu page."""
from __future__ import annotations

import streamlit as st

from ..optimization.slotting_engine import METHOD_LABELS
from ..pipeline import METHODS, method_comparison_table
from . import common as c


def render() -> None:
    c.page_header("Yerleşim Optimizasyonu",
                  "İki yöntem aynı veri, aynı kısıtlar ve aynı siparişlerle karşılaştırılır.")
    res = c.require_result()
    if res is None:
        return
    c.provenance_banner(res)
    s = c.settings()
    sl = s["slotting"]

    with st.form("slotting_params"):
        st.markdown("**Parametreler**")
        p = st.columns(3)
        method = p[0].selectbox("Seçili yöntem (taşıma planı ve raporlar için)", list(METHODS),
                                index=list(METHODS).index(sl["method"]), format_func=METHOD_LABELS.get)
        max_moves = p[1].number_input("Maksimum taşıma hareketi", 0, 5000, int(sl["max_moves"]),
                                      help="Yer açma taşımaları da sayılır.")
        st.markdown("Yöntem A — sınıf ağırlıkları")
        q = st.columns(4)
        cb = sl["class_based"]
        wa = q[0].number_input("A ağırlığı", 0.0, 100.0, float(cb["class_weight_a"]))
        wb = q[1].number_input("B ağırlığı", 0.0, 100.0, float(cb["class_weight_b"]))
        wc = q[2].number_input("C ağırlığı", 0.0, 100.0, float(cb["class_weight_c"]))
        mg = q[3].number_input("Min. puan kazancı / taşıma", 0.0, 1000.0, float(cb["min_gain"]))
        st.markdown("Yöntem B — hibrit katsayılar (metre eşdeğeri / analiz dönemi)")
        h = sl["hybrid"]
        r = st.columns(5)
        w_travel = r[0].number_input("Yürüme", 0.0, 100.0, float(h["w_travel"]))
        w_height = r[1].number_input("Yükseklik (m başına)", 0.0, 100.0, float(h["w_height"]))
        w_family = r[2].number_input("Aile yakınlığı", 0.0, 100.0, float(h["w_family"]),
                                     help="0 = kapalı. Ailenin mevcut ağırlık merkezine uzaklık.")
        w_fit = r[3].number_input("Hacim uyumu", 0.0, 1000.0, float(h["w_fit"]))
        move_cost = r[4].number_input("Taşıma eşiği (m)", 0.0, 100000.0, float(h["move_cost_m"]),
                                      help="Bir taşımanın önerilmesi için dönem boyunca beklenen minimum kazanç.")
        if st.form_submit_button("Uygula ve yeniden hesapla"):
            sl.update(method=method, max_moves=int(max_moves))
            cb.update(class_weight_a=wa, class_weight_b=wb, class_weight_c=wc, min_gain=mg)
            h.update(w_travel=w_travel, w_height=w_height, w_family=w_family, w_fit=w_fit, move_cost_m=move_cost)
            st.rerun()

    st.info("Her iki yöntem de **sezgiseldir**: puanı adım adım düşüren taşımaları seçer ve küresel optimumu garanti "
            "etmez. Çıktı bir **önerilen yerleşimdir**. Gerçek etki aşağıda rota simülasyonuyla ölçülür (simülasyon, "
            "ölçüm değildir).", icon="ℹ️")

    st.subheader("Yöntem karşılaştırması (aynı siparişler)")
    table = method_comparison_table(res)
    st.dataframe(table, hide_index=True, column_config={
        "Mevcut toplam mesafe (m)": st.column_config.NumberColumn(format="%.0f"),
        "Önerilen toplam mesafe (m)": st.column_config.NumberColumn(format="%.0f"),
        "Mesafe farkı (m)": st.column_config.NumberColumn(format="%.0f"),
        "İyileşme (%)": st.column_config.NumberColumn(format="%.1f"),
    })

    method = res.selected_method
    slot = res.slotting[method]
    st.subheader(METHOD_LABELS[method])
    k = st.columns(4)
    k[0].metric("Taşınabilir SKU", slot.movable_count)
    k[1].metric("Uygun hedef havuzu", f"{slot.pool_size} lokasyon")
    k[2].metric("Önerilen taşıma", slot.move_count)
    k[3].metric("Atanamayan SKU", len(slot.unassignable))
    for note in slot.notes:
        st.caption("• " + note)

    with st.expander("Zorunlu kısıtlar", expanded=False):
        st.markdown(
            """
- Ürün birim boyutu lokasyona sığmalı (yatayda döndürme serbest, devirme yok).
- Miktar × birim ağırlık ≤ maksimum ağırlık; miktar × birim hacim ≤ maksimum hacim.
- Miktar geometrik olarak sığmalı (katman başına adet × katman sayısı; istiflenemeyen ürün tek katman).
- Kullanılamayan, toplanamayan, sabit ve karışık (çok SKU'lu) lokasyonlar hedef olamaz.
- Kapasite bilgisi eksik lokasyonlar hedef olamaz (güvenli varsayılan).
- Depolama koşulu (ör. soğuk) eşleşmeli; elleçleme tipi lokasyon tipiyle uyumlu olmalı.
- Her lokasyon tek SKU; her taşıma yürütüldüğü anda boş bir lokasyona yapılır (sıralı plan).
- Stok bölme politikası: birden çok toplama lokasyonundaki SKU'lar taşınmaz, taşınan SKU tüm miktarıyla taşınır.
"""
        )
    l, r = st.columns(2)
    l.markdown("**Taşınamaz SKU'lar**")
    l.dataframe(slot.not_movable.drop(columns=["reason_code"]).rename(
        columns={"sku": "SKU", "current_locations": "Mevcut lokasyon", "reason": "Neden"}), hide_index=True)
    r.markdown("**Uygun hedef bulunamayan SKU'lar**")
    if slot.unassignable.empty:
        r.caption("Yok — taşınabilir her SKU için en az bir uygun lokasyon var.")
    else:
        r.dataframe(slot.unassignable.rename(columns={"sku": "SKU", "abc_class": "Sınıf", "reason": "Neden"}),
                    hide_index=True)
