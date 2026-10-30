"""Rota ve Mesafe Analizi page."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ..layout import visualization as viz
from ..routing.picking_routes import route_locations, route_path_xy
from ..simulation.comparison import resolve_pick_location
from . import common as c
from .layout_page import scenario_placement, sku_info_frame

LOCATION_COLUMNS = {"location_id": "Lokasyon", "aisle_id": "Koridor", "zone": "Bölge", "x": "X (m)", "y": "Y (m)",
                    "z": "Z (m)", "dock_distance_m": "Sevkiyata tek yön (m)"}


def render() -> None:
    c.page_header("Rota ve Mesafe Analizi")
    res = c.require_result()
    if res is None:
        return
    c.provenance_banner(res)
    model = res.model
    st.markdown(f"**Mesafe modeli:** {model.label}")
    if res.model.mode == "graph":
        st.caption(f"Koridor ağı: {res.model.graph.number_of_nodes()} düğüm, {res.model.graph.number_of_edges()} kenar "
                   "(koridor uçları, raf erişim noktaları, sevkiyat). En kısa yol: Dijkstra (NetworkX). "
                   "Çok duraklı tur: en yakın komşu + 2-opt (sezgisel).")
    for note in model.notes:
        st.caption("• " + note)

    tab_access, tab_order = st.tabs(["Lokasyon erişim mesafesi", "Sipariş rotası"])
    with tab_access:
        locs = res.locations
        unreachable = locs[locs["dock_distance_m"].isna()]
        k = st.columns(3)
        k[0].metric("Lokasyon", len(locs))
        k[1].metric("Ulaşılamayan", len(unreachable))
        k[2].metric("Ortalama sevkiyat mesafesi", c.fmt_num(locs["dock_distance_m"].mean(), 1, " m"))
        if not unreachable.empty:
            st.error("Ulaşılamayan lokasyonlar rotalara katılamaz:")
            st.dataframe(unreachable[["location_id", "aisle_id", "x", "y"]].rename(columns=LOCATION_COLUMNS),
                         hide_index=True)
        st.dataframe(locs[["location_id", "aisle_id", "zone", "x", "y", "z", "dock_distance_m"]]
                     .sort_values("dock_distance_m").rename(columns=LOCATION_COLUMNS), hide_index=True,
                     column_config={"Sevkiyata tek yön (m)": st.column_config.NumberColumn(format="%.1f")})

    with tab_order:
        method = res.selected_method
        slot = res.slotting[method]
        comp = res.comparisons[method].per_order
        if comp.empty:
            st.info("Karşılaştırılabilir sipariş yok.")
            return
        order_ids = comp.sort_values("difference_m", ascending=False)["order_id"].tolist()
        order_id = st.selectbox("Sipariş (en çok iyileşenden en aza sıralı)", order_ids)
        lines = res.period_lines[res.period_lines["order_id"] == order_id]
        dock = res.locations.set_index("location_id")["dock_distance_m"]
        cur_map = resolve_pick_location(slot.placement_current, dock)
        new_map = resolve_pick_location(slot.placement_proposed, dock)
        skus = sorted(s for s in lines["sku"].unique() if s in cur_map)
        use_2opt = res.settings["operations"]["use_two_opt"]
        cur = route_locations(model, [cur_map[s] for s in skus], use_2opt)
        new = route_locations(model, [new_map.get(s, cur_map[s]) for s in skus], use_2opt)
        k = st.columns(4)
        k[0].metric("Durak", cur.n_stops)
        k[1].metric("Mevcut rota", c.fmt_num(cur.distance_m, 1, " m"))
        k[2].metric("Önerilen rota", c.fmt_num(new.distance_m, 1, " m"))
        diff = cur.distance_m - new.distance_m
        k[3].metric("Fark", c.fmt_num(diff, 1, " m"), delta=c.fmt_num(diff, 1, " m"), delta_color="normal")
        routes = []
        if cur.valid:
            routes.append(("Mevcut rota", route_path_xy(model, cur), viz.ROUTE_CURRENT))
        if new.valid:
            routes.append(("Önerilen rota", route_path_xy(model, new), viz.ROUTE_PROPOSED))
        abc_map = dict(zip(res.abc.table["sku"], res.abc.table["abc_class"]))
        fig = viz.warehouse_map(res.locations, res.geometry, scenario_placement(res, method, "proposed"), abc_map,
                                sku_info_frame(res), "abc", f"Sipariş {order_id}: mevcut ve önerilen rota",
                                routes=routes, is_synthetic=res.is_synthetic,
                                is_approximate=res.geometry.is_approximate,
                                plot_width=c.map_plot_width())
        st.plotly_chart(fig, theme=None, config=viz.MAP_CONFIG)
        detail = pd.DataFrame({"SKU": skus, "Mevcut lokasyon": [cur_map[s] for s in skus],
                               "Önerilen lokasyon": [new_map.get(s, cur_map[s]) for s in skus]})
        st.dataframe(detail, hide_index=True)
        st.caption("Rota: sevkiyat → duraklar → sevkiyat. Aynı lokasyondaki ürünler tek durakta toplanır. "
                   "Harita önerilen yerleşimi gösterir.")
