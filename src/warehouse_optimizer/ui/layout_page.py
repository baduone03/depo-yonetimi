"""Depo Yerleşim Haritası page."""
from __future__ import annotations

import pandas as pd
import streamlit as st

from ..layout import visualization as viz
from ..optimization.slotting_engine import METHOD_LABELS
from . import common as c


def scenario_placement(res, method: str, scenario: str) -> dict[str, str]:
    """location_id -> sku for the chosen scenario (all inventory, moves applied for 'proposed')."""
    inv = res.validation.tables["inventory"]
    mapping: dict[str, list[str]] = {}
    for loc, sku in zip(inv["location_id"], inv["sku"]):
        mapping.setdefault(loc, []).append(sku)
    if scenario == "proposed":
        for _, m in res.slotting[method].moves.iterrows():
            mapping[m["from_location"]] = [s for s in mapping.get(m["from_location"], []) if s != m["sku"]]
            mapping.setdefault(m["to_location"], []).append(m["sku"])
    return {loc: "+".join(sorted(skus)) for loc, skus in mapping.items() if skus}


def sku_info_frame(res) -> pd.DataFrame:
    abc = res.abc.table[["sku", "order_lines", "abc_class"]]
    qty = res.validation.tables["inventory"].groupby("sku")["current_quantity"].sum().rename("current_quantity")
    return abc.merge(qty, on="sku", how="left")


def render() -> None:
    c.page_header("Depo Yerleşim Haritası")
    res = c.require_result()
    if res is None:
        return
    c.provenance_banner(res)
    method = res.selected_method
    slot = res.slotting[method]

    o1, o2, o3 = st.columns([1, 1, 2])
    scenario = o1.radio("Yerleşim", ["current", "proposed"], horizontal=True,
                        format_func={"current": "Mevcut", "proposed": "Önerilen"}.get)
    color_by = o2.radio("Renk", ["abc", "occupancy"], horizontal=True,
                        format_func={"abc": "ABC sınıfı", "occupancy": "Doluluk"}.get)
    moved_skus = (["(okları gizle)", "(tüm taşımalar)"] + sorted(slot.moves["sku"].unique())
                  if not slot.moves.empty else ["(taşıma yok)"])
    highlight = o3.selectbox("Taşıma okunu göster (mevcut → hedef)", moved_skus)
    show_moves = highlight not in ("(okları gizle)", "(taşıma yok)")
    highlight_sku = None if highlight.startswith("(") else highlight

    placement = scenario_placement(res, method, scenario)
    abc_map = dict(zip(res.abc.table["sku"], res.abc.table["abc_class"]))
    abc_map.update({k: "+" for k in placement.values() if "+" in k})
    title = f"{'Mevcut' if scenario == 'current' else 'Önerilen'} yerleşim — {METHOD_LABELS[method]}"
    fig = viz.warehouse_map(res.locations, res.geometry, placement, abc_map, sku_info_frame(res), color_by, title,
                            moves=slot.moves if show_moves else None, highlight_sku=highlight_sku,
                            is_synthetic=res.is_synthetic, is_approximate=res.geometry.is_approximate)
    event = st.plotly_chart(fig, theme=None, on_select="rerun", selection_mode="points", key="map")
    st.caption("Aynı koordinattaki raf seviyeleri haritada yan yana (0,35 m kaydırılarak) gösterilir. Kare: lokasyon; "
               "yıldız: sevkiyat noktası; gri bant: koridor. Oklar mevcut → hedef taşımalarını gösterir.")

    selected = None
    try:
        points = event.selection.points if event else []
        for p in points:
            if p.get("customdata"):
                selected = p["customdata"]
                break
    except AttributeError:
        selected = None
    loc_ids = sorted(res.locations["location_id"])
    choice = st.selectbox("Lokasyon detayı (haritada bir lokasyona tıklayın veya seçin)", loc_ids,
                          index=loc_ids.index(selected) if selected in loc_ids else 0)
    _location_detail(res, choice, placement)


def _location_detail(res, location_id: str, placement: dict[str, str]) -> None:
    loc = res.locations.set_index("location_id").loc[location_id]
    inv = res.validation.tables["inventory"]
    stock = inv[inv["location_id"] == location_id]
    sku = placement.get(location_id, "")
    abc = res.abc.table.set_index("sku")
    cols = st.columns(4)
    cols[0].metric("Ürün (bu senaryoda)", sku or "Boş")
    cols[1].metric("ABC sınıfı", abc["abc_class"].get(sku, "—") if sku else "—")
    cols[2].metric("Dönem sipariş satırı", int(abc["order_lines"].get(sku, 0)) if sku in abc.index else "—")
    cols[3].metric("Sevkiyata mesafe", c.fmt_num(loc["dock_distance_m"], 1, " m"))
    detail = {
        "Koridor": loc["aisle_id"], "Bölge": loc["zone"], "Tip": loc["location_type"],
        "Koordinat (x, y, z)": f"{loc['x']:.1f}, {loc['y']:.1f}, {loc['z']:.1f}",
        "Max ağırlık (kg)": loc["max_weight_kg"], "Max hacim (m³)": loc["max_volume_m3"],
        "Max boyut U×G×Y (m)": f"{loc['max_length_m']} × {loc['max_width_m']} × {loc['max_height_m']}",
        "Toplanabilir": "Evet" if loc["is_pickable"] else "Hayır",
        "Kullanılabilir": "Evet" if loc["is_available"] else "Hayır",
        "Sabit": "Evet" if loc["is_fixed"] else "Hayır", "Depolama sınıfı": loc["storage_class"],
        "Mevcut stok (stok tablosu)": ", ".join(f"{r.sku}: {r.current_quantity:g}" for r in stock.itertuples()) or "—",
    }
    st.dataframe(pd.DataFrame({"Alan": list(detail), "Değer": [str(v) for v in detail.values()]}), hide_index=True)
