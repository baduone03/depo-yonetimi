"""Genel Bakış (overview) page."""
from __future__ import annotations

import streamlit as st

from ..optimization.slotting_engine import METHOD_LABELS
from . import common as c


def render() -> None:
    c.page_header("Warehouse Intelligence & Slotting Optimizer",
                  "Depo yerleşim analizi, yerleşim önerisi ve aynı siparişler üzerinde önce/sonra simülasyonu")
    res = c.require_result()
    if res is None:
        _how_it_works()
        return
    c.provenance_banner(res)
    method = res.selected_method
    comp = res.comparisons[method].summary
    slot = res.slotting[method]
    tables = res.validation.tables
    counts = res.abc.class_counts()

    st.subheader("Veri kapsamı")
    k = st.columns(4)
    k[0].metric("Analiz edilen SKU", c.fmt_num(len(res.abc.table)))
    k[1].metric("Sipariş (analiz dönemi)", c.fmt_num(res.period_lines["order_id"].nunique()))
    k[2].metric("Lokasyon", c.fmt_num(len(tables["locations"])))
    k[3].metric("Analiz dönemi", f"{res.period.days} gün", help=res.period.label())
    if res.period.note:
        st.caption("⚠️ " + res.period.note)

    st.subheader("ABC sınıf dağılımı")
    k = st.columns(3)
    shares = res.abc.class_share()
    for col, cls in zip(k, "ABC"):
        col.metric(f"Sınıf {cls}", f"{counts[cls]} SKU", help="Hareket payı: " + c.fmt_pct(shares[cls] * 100
                                                                                         if not c.is_missing(shares[cls]) else None))
    if not res.abc.defined:
        st.warning("Analiz döneminde çıkış hareketi yok; ABC sınıflandırması tanımsız.")

    st.subheader(f"Yerleşim önerisi ve simülasyon — {METHOD_LABELS[method]}")
    k = st.columns(4)
    k[0].metric("Taşınması önerilen SKU", c.fmt_num(slot.moved_sku_count), help=f"{slot.move_count} taşıma hareketi")
    k[1].metric("Mevcut toplam toplama mesafesi", c.fmt_num(comp.get("total_current_m"), 0, " m"))
    k[2].metric("Önerilen toplam toplama mesafesi", c.fmt_num(comp.get("total_proposed_m"), 0, " m"))
    imp = comp.get("improvement_pct")
    k[3].metric("İyileşme", c.fmt_pct(imp),
                help="((mevcut − önerilen) / mevcut) × 100. Negatif değer kötüleşmedir.")
    k = st.columns(4)
    t = comp.get("time_difference_h")
    k[0].metric("Tahmini zaman farkı", c.fmt_num(t * 60 if not c.is_missing(t) else None, 0, " dk"),
                help="Simüle edilen siparişler için. " + ("Yürüme + toplama süresi." if comp.get("time_includes_pick_time")
                                                         else "Yalnızca yürüme süresi (toplama süresi girilmedi)."))
    k[1].metric("Karşılaştırılan sipariş", c.fmt_num(comp.get("orders_compared")))
    k[2].metric("Kötüleşen sipariş", c.fmt_num(comp.get("orders_worse")))
    k[3].metric("Atanamayan / taşınamaz SKU", f"{len(slot.unassignable)} / {len(slot.not_movable)}")
    if not c.is_missing(imp) and imp < 0:
        st.error("Önerilen yerleşim bu siparişlerde toplam mesafeyi ARTIRIYOR. Parametreleri gözden geçirin.")
    st.caption("Mesafe ve süreler depo modeli üzerinde yapılan simülasyon sonuçlarıdır; ölçülmüş değer değildir. "
               + res.model.label + ".")

    issues = res.validation.issues
    st.subheader("Veri kalitesi")
    k = st.columns(3)
    k[0].metric("Hata", int((issues["severity"] == "hata").sum()))
    k[1].metric("Uyarı", int((issues["severity"] == "uyarı").sum()))
    k[2].metric("Bilgi", int((issues["severity"] == "bilgi").sum()))


def _how_it_works() -> None:
    st.markdown(
        """
**Akış**
1. **Veri Yükleme** — ürünler, sipariş satırları, lokasyonlar ve stok (CSV/XLSX) ya da sentetik demo verisi.
2. **ABC ve Hareket Analizi** — seçilen metriğin kümülatif katkısına göre sınıflandırma.
3. **Depo Yerleşim Haritası** — koridorlar, lokasyonlar, mevcut ve önerilen yerleşim.
4. **Yerleşim Optimizasyonu** — sınıf tabanlı ve hibrit yöntemlerle kısıtlara uygun öneri.
5. **Rota ve Önce/Sonra Simülasyonu** — aynı siparişler, aynı rota modeli.
6. **Taşıma Planı ve Raporlar** — CSV/XLSX dışa aktarma.

Uygulama yerel çalışır; dosyalarınız dışarı gönderilmez ve hiçbir WMS'e değişiklik yazılmaz.
"""
    )
