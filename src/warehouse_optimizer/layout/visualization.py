"""Plotly figures: warehouse map, Pareto / ABC charts, route and simulation charts.

Colour roles (validated reference palette, first three categorical slots,
which pass the all-pairs CVD checks for scatter-type charts):
    A = blue, B = orange, C = aqua; empty / unknown = neutral grey.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import plotly.graph_objects as go

ABC_COLORS = {"A": "#2a78d6", "B": "#eb6834", "C": "#1baf7a"}
EMPTY_COLOR = "#c9c8c2"
UNAVAILABLE_COLOR = "#7a7974"
AISLE_FILL = "#efeee9"
TEXT_MUTED = "#52514e"
ROUTE_CURRENT = "#52514e"
ROUTE_PROPOSED = "#2a78d6"
LEVEL_OFFSET_M = 0.35

_LAYOUT = dict(
    template="plotly_white",
    font=dict(family="Inter, Segoe UI, sans-serif", size=12, color="#0b0b0b"),
    margin=dict(l=10, r=10, t=86, b=10),
    paper_bgcolor="white",
    plot_bgcolor="white",
    hoverlabel=dict(bgcolor="white", font_size=12),
    legend=dict(orientation="h", yanchor="bottom", y=1.01, xanchor="left", x=0),
)


def _apply(fig: go.Figure, title: str, height: int = 380) -> go.Figure:
    fig.update_layout(title=dict(text=title, x=0, xanchor="left", y=0.985, yanchor="top", yref="container",
                                 font=dict(size=14)), height=height, **_LAYOUT)
    fig.update_xaxes(showgrid=False, linecolor="#d4d3cd")
    fig.update_yaxes(gridcolor="#eeede8", zeroline=False)
    return fig


# --- ABC & movement ----------------------------------------------------------

def pareto_chart(abc_table: pd.DataFrame, a_share: float, b_share: float, metric_label: str) -> go.Figure:
    fig = go.Figure()
    df = abc_table
    for cls in ("A", "B", "C"):
        sub = df[df["abc_class"] == cls]
        fig.add_trace(go.Scatter(
            x=sub["rank"], y=sub["cumulative_share"] * 100, mode="markers", name=f"Sınıf {cls}",
            marker=dict(color=ABC_COLORS[cls], size=8, line=dict(color="white", width=1)),
            customdata=np.stack([sub["sku"], sub["metric_value"]], axis=-1) if len(sub) else None,
            hovertemplate="%{customdata[0]}<br>Sıra %{x}<br>Metrik: %{customdata[1]:,.0f}"
                          "<br>Kümülatif: %{y:.1f}%<extra></extra>"))
    fig.add_trace(go.Scatter(x=df["rank"], y=df["cumulative_share"] * 100, mode="lines", showlegend=False,
                             line=dict(color="#a3a29c", width=2), hoverinfo="skip"))
    for share, label in ((a_share, "A sınırı"), (a_share + b_share, "B sınırı")):
        fig.add_hline(y=share * 100, line=dict(color="#a3a29c", width=1, dash="dot"),
                      annotation_text=f"{label} %{share * 100:.0f}", annotation_position="bottom right",
                      annotation_font_color=TEXT_MUTED)
    fig.update_xaxes(title=f"SKU sırası ({metric_label}, azalan)")
    fig.update_yaxes(title="Kümülatif katkı (%)", range=[0, 103])
    return _apply(fig, "Pareto eğrisi")


def abc_distribution_chart(abc_table: pd.DataFrame) -> go.Figure:
    counts = abc_table["abc_class"].value_counts()
    total_sku = max(len(abc_table), 1)
    metric_total = abc_table["metric_value"].sum()
    rows = []
    for cls in ("A", "B", "C"):
        sku_pct = counts.get(cls, 0) / total_sku * 100
        metric_pct = (abc_table.loc[abc_table["abc_class"] == cls, "metric_value"].sum() / metric_total * 100
                      if metric_total > 0 else np.nan)
        rows.append((cls, sku_pct, metric_pct, counts.get(cls, 0)))
    fig = go.Figure()
    fig.add_trace(go.Bar(name="SKU payı", x=[r[0] for r in rows], y=[r[1] for r in rows],
                         marker=dict(color="#a3a29c", cornerradius=4),
                         text=[f"{r[3]} SKU" for r in rows], textposition="outside",
                         hovertemplate="Sınıf %{x}<br>SKU payı %{y:.1f}%<extra></extra>"))
    fig.add_trace(go.Bar(name="Hareket payı", x=[r[0] for r in rows], y=[r[2] for r in rows],
                         marker=dict(color=[ABC_COLORS[r[0]] for r in rows], cornerradius=4),
                         hovertemplate="Sınıf %{x}<br>Hareket payı %{y:.1f}%<extra></extra>"))
    fig.update_layout(barmode="group", bargap=0.35, bargroupgap=0.08)
    fig.update_yaxes(title="%", range=[0, 110])
    return _apply(fig, "ABC dağılımı: SKU payı ve hareket payı")


def frequency_chart(abc_table: pd.DataFrame, period_days: int) -> go.Figure:
    df = abc_table.sort_values("rank")
    fig = go.Figure(go.Bar(
        x=df["sku"], y=df["order_lines"],
        marker=dict(color=[ABC_COLORS.get(c, EMPTY_COLOR) for c in df["abc_class"]], cornerradius=2),
        hovertemplate="%{x}<br>%{y} sipariş satırı<extra></extra>"))
    fig.update_xaxes(title="SKU (sıralı)", showticklabels=len(df) <= 60, tickangle=-90)
    fig.update_yaxes(title=f"Sipariş satırı ({period_days} gün)")
    return _apply(fig, "Hareket sıklığı (SKU başına sipariş satırı)")


def daily_activity_chart(daily: pd.DataFrame) -> go.Figure:
    fig = go.Figure(go.Scatter(x=daily["date"], y=daily["orders"], mode="lines",
                               line=dict(color=ABC_COLORS["A"], width=2),
                               hovertemplate="%{x|%Y-%m-%d}<br>%{y} sipariş<extra></extra>"))
    fig.update_yaxes(title="Sipariş / gün")
    return _apply(fig, "Günlük sipariş sayısı", height=280)


# --- warehouse map ------------------------------------------------------------

def _level_offsets(locations: pd.DataFrame) -> pd.Series:
    z = locations["z"].fillna(0)
    rank = z.groupby([locations["x"], locations["y"]]).rank(method="dense") - 1
    return rank * LEVEL_OFFSET_M


def warehouse_map(locations: pd.DataFrame, geometry, placement: dict[str, str], abc_class: dict[str, str],
                  sku_info: pd.DataFrame | None = None, color_by: str = "abc", title: str = "",
                  moves: pd.DataFrame | None = None, highlight_sku: str | None = None,
                  routes: list[tuple[str, list[tuple[float, float]], str]] | None = None,
                  is_synthetic: bool = False, is_approximate: bool = False) -> go.Figure:
    """placement: location_id -> sku for the scenario shown."""
    fig = go.Figure()
    for _, a in geometry.aisles.iterrows():
        fig.add_shape(type="rect", x0=a["x_center"] - 0.6, x1=a["x_center"] + 0.6, y0=a["y_start"], y1=a["y_end"],
                      fillcolor=AISLE_FILL, line=dict(width=0), layer="below")
        fig.add_annotation(x=a["x_center"], y=a["y_end"], text=str(a["aisle_id"]), showarrow=False, yshift=10,
                           font=dict(size=10, color=TEXT_MUTED))
    xs = geometry.aisles["x_center"]
    for y in (geometry.aisles["y_start"].min(), geometry.aisles["y_end"].max()):
        fig.add_shape(type="line", x0=xs.min(), x1=xs.max(), y0=y, y1=y, line=dict(color="#dedcd5", width=10),
                      layer="below")

    df = locations.copy()
    df["x_plot"] = df["x"] + _level_offsets(df).to_numpy()
    df["sku"] = df["location_id"].map(placement).fillna("")
    df["abc"] = df["sku"].map(abc_class).fillna("")
    if sku_info is not None:
        info = sku_info.set_index("sku")
        df["lines"] = df["sku"].map(info["order_lines"]).fillna(0).astype(int)
        df["qty"] = df["sku"].map(info["current_quantity"]) if "current_quantity" in info else ""
    else:
        df["lines"], df["qty"] = 0, ""
    df["status"] = np.where(~df["is_available"], "Kullanılamaz",
                            np.where(df["sku"] != "", "Dolu", "Boş"))
    df["hover"] = (df["location_id"] + "<br>Koridor " + df["aisle_id"].astype(str)
                   + "<br>Durum: " + df["status"]
                   + np.where(df["sku"] != "", "<br>SKU: " + df["sku"] + " (" + df["abc"] + ")"
                              + "<br>Dönem satırı: " + df["lines"].astype(str)
                              + "<br>Stok: " + df["qty"].astype(str), "")
                   + "<br>Max: " + df["max_weight_kg"].round(0).astype(str) + " kg, "
                   + df["max_volume_m3"].round(3).astype(str) + " m³"
                   + "<br>Sevkiyata: " + df["dock_distance_m"].round(1).astype(str) + " m"
                   + np.where(df["is_fixed"], "<br>SABİT LOKASYON", ""))

    if color_by == "abc":
        groups = [("Boş", df["status"] == "Boş", EMPTY_COLOR), ("Kullanılamaz", df["status"] == "Kullanılamaz",
                                                                 UNAVAILABLE_COLOR)]
        groups += [(f"Sınıf {c}", (df["abc"] == c) & (df["status"] == "Dolu"), ABC_COLORS[c]) for c in "ABC"]
    else:
        groups = [("Boş", df["status"] == "Boş", EMPTY_COLOR), ("Dolu", df["status"] == "Dolu", ABC_COLORS["A"]),
                  ("Kullanılamaz", df["status"] == "Kullanılamaz", UNAVAILABLE_COLOR)]
    for name, mask, color in groups:
        sub = df[mask]
        if sub.empty:
            continue
        fig.add_trace(go.Scatter(
            x=sub["x_plot"], y=sub["y"], mode="markers", name=name, customdata=sub["location_id"],
            marker=dict(symbol="square", size=11, color=color, line=dict(color="white", width=1)),
            text=sub["hover"], hovertemplate="%{text}<extra></extra>"))
    fixed = df[df["is_fixed"]]
    if not fixed.empty:
        fig.add_trace(go.Scatter(x=fixed["x_plot"], y=fixed["y"], mode="markers", name="Sabit lokasyon",
                                 marker=dict(symbol="square-open", size=15, color="#0b0b0b", line=dict(width=2)),
                                 hoverinfo="skip"))

    pos = df.set_index("location_id")[["x_plot", "y"]]
    if moves is not None and not moves.empty:
        for _, m in moves.iterrows():
            if m["from_location"] not in pos.index or m["to_location"] not in pos.index:
                continue
            (x0, y0), (x1, y1) = pos.loc[m["from_location"]], pos.loc[m["to_location"]]
            emphasized = highlight_sku is not None and m["sku"] == highlight_sku
            if highlight_sku is not None and not emphasized:
                continue
            fig.add_annotation(x=x1, y=y1, ax=x0, ay=y0, xref="x", yref="y", axref="x", ayref="y",
                               showarrow=True, arrowhead=2, arrowsize=1.2 if emphasized else 1,
                               arrowwidth=3 if emphasized else 1.2,
                               arrowcolor="#0b0b0b" if emphasized else "#8a8984", opacity=0.9)
    for name, coords, color in routes or []:
        if not coords:
            continue
        fig.add_trace(go.Scatter(x=[c[0] for c in coords], y=[c[1] for c in coords], mode="lines", name=name,
                                 line=dict(color=color, width=3), hoverinfo="skip"))

    dx, dy = geometry.dock_xy
    fig.add_trace(go.Scatter(x=[dx], y=[dy], mode="markers+text", name="Sevkiyat noktası", text=["SEVKİYAT"],
                             textposition="bottom center", marker=dict(symbol="star", size=18, color="#0b0b0b"),
                             hovertemplate=f"Sevkiyat noktası ({dx:.1f}, {dy:.1f})<extra></extra>"))
    caveats = []
    if is_synthetic:
        caveats.append("SENTETİK DEMO VERİSİ")
    if is_approximate:
        caveats.append("YAKLAŞIK GEOMETRİ")
    full_title = title + (f"  —  {' · '.join(caveats)}" if caveats else "")
    fig.update_xaxes(title="X (m)", scaleanchor="y", scaleratio=1, showgrid=False, zeroline=False)
    fig.update_yaxes(title="Y (m)", showgrid=False)
    return _apply(fig, full_title, height=640)


# --- simulation -----------------------------------------------------------------

def order_distance_scatter(per_order: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    if per_order.empty:
        return _apply(fig, "Sipariş bazında mesafe")
    better = per_order["difference_m"] >= 0
    for name, mask, color in (("İyileşen / aynı", better, ABC_COLORS["A"]), ("Kötüleşen", ~better, ABC_COLORS["B"])):
        sub = per_order[mask]
        fig.add_trace(go.Scatter(
            x=sub["distance_current_m"], y=sub["distance_proposed_m"], mode="markers", name=name,
            marker=dict(color=color, size=8, opacity=0.75, line=dict(color="white", width=1)),
            text=sub["order_id"], hovertemplate="%{text}<br>Mevcut %{x:.1f} m<br>Önerilen %{y:.1f} m<extra></extra>"))
    top = float(max(per_order["distance_current_m"].max(), per_order["distance_proposed_m"].max())) * 1.05
    fig.add_trace(go.Scatter(x=[0, top], y=[0, top], mode="lines", name="Değişim yok (y = x)",
                             line=dict(color="#a3a29c", dash="dot", width=1), hoverinfo="skip"))
    fig.update_xaxes(title="Mevcut yerleşim rota mesafesi (m)", range=[0, top])
    fig.update_yaxes(title="Önerilen yerleşim rota mesafesi (m)", range=[0, top])
    return _apply(fig, "Sipariş bazında rota mesafesi: mevcut ve önerilen", height=460)


def distance_distribution_chart(per_order: pd.DataFrame) -> go.Figure:
    fig = go.Figure()
    for name, col, color in (("Mevcut", "distance_current_m", ROUTE_CURRENT),
                             ("Önerilen", "distance_proposed_m", ROUTE_PROPOSED)):
        fig.add_trace(go.Box(y=per_order[col], name=name, marker_color=color, boxmean=True,
                             hovertemplate="%{y:.1f} m<extra></extra>"))
    fig.update_yaxes(title="Sipariş başına rota mesafesi (m)")
    return _apply(fig, "Dağılım (kutu: çeyrekler, kesikli çizgi: ortalama)", height=460)
