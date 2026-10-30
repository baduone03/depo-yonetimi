"""Ayarlar page."""
from __future__ import annotations

import yaml
import streamlit as st

from ..settings import load_settings
from . import common as c


def render() -> None:
    c.page_header("Ayarlar", "Değişiklikler oturum boyunca geçerlidir; varsayılanlar config/default_settings.yaml dosyasındadır.")
    s = c.settings()
    g = s["geometry"]
    ds = c.dataset()

    with st.form("geometry"):
        st.subheader("Depo geometrisi ve mesafe modeli")
        mode = st.radio("Mesafe modeli", ["graph", "manhattan"], index=["graph", "manhattan"].index(g["distance_mode"]),
                        format_func={"graph": "Koridor ağı (en kısa yol)",
                                     "manhattan": "Tahmini Manhattan (koridor ağı yoksa)"}.get, horizontal=True)
        default_dock = ds.dock_xy if ds is not None and ds.dock_xy else (None, None)
        d1, d2 = st.columns(2)
        dock_x = d1.number_input("Sevkiyat noktası X (m)", value=g["dock_x"] if g["dock_x"] is not None else default_dock[0],
                                 placeholder="tanımsız")
        dock_y = d2.number_input("Sevkiyat noktası Y (m)", value=g["dock_y"] if g["dock_y"] is not None else default_dock[1],
                                 placeholder="tanımsız")
        st.caption("Koridor tablosu (aisles) yüklenmezse koridor orta hatları lokasyon koordinatlarından türetilir ve "
                   "yaklaşık geometri olarak işaretlenir.")
        if st.form_submit_button("Uygula"):
            g["distance_mode"] = mode
            g["dock_x"], g["dock_y"] = dock_x, dock_y
            st.rerun()

    with st.form("advanced"):
        st.subheader("Gelişmiş: tüm parametreler (YAML)")
        text = st.text_area("Ayarlar", yaml.safe_dump(s, allow_unicode=True, sort_keys=False), height=420)
        st.caption("Elleçleme uyumluluğu (handling_compatibility): ürün elleçleme tipi → izin verilen lokasyon tipleri. "
                   "Listede olmayan elleçleme tipleri hiçbir lokasyona atanmaz (güvenli varsayılan).")
        if st.form_submit_button("YAML'i uygula"):
            try:
                parsed = yaml.safe_load(text)
                if not isinstance(parsed, dict):
                    raise ValueError("Geçerli bir sözlük değil")
                c.update_settings(parsed)
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"Ayarlar okunamadı: {exc}")

    if st.button("Varsayılanlara dön"):
        c.update_settings(load_settings())
        st.rerun()
