from __future__ import annotations

from pathlib import Path
import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "processed" / "points.csv"
OUT = ROOT / "population_area_density_chart.html"

REGION_STYLE = {
    "Africa": ("#1f77b4", "circle"),
    "Europe": ("#9467bd", "square"),
    "North America": ("#2ca02c", "diamond"),
    "South America": ("#d62728", "cross"),
    "Oceania": ("#17becf", "triangle-up"),
    "West Asia": ("#ff7f0e", "triangle-down"),
    "East Asia": ("#e377c2", "star"),
    "South Asia": ("#8c564b", "hexagon"),
    "Southeast Asia": ("#bcbd22", "pentagon"),
    "Central Asia": ("#7f7f7f", "x"),
    "Antarctica": ("#9edae5", "hourglass"),
    "Asia - other": ("#c49c94", "hexagram"),
    "Other": ("#aec7e8", "circle-open"),
}

SUBDIVISION_STYLES = [
    ("#003f5c", "triangle-right"),
    ("#ffa600", "diamond-open"),
    ("#58508d", "square-open"),
    ("#bc5090", "star-diamond"),
    ("#ff6361", "hexagon-open"),
    ("#00876c", "triangle-ne"),
    ("#7a5195", "pentagon-open"),
]

ORDER = [
    "Africa", "Europe", "North America", "South America", "Oceania",
    "West Asia", "East Asia", "South Asia", "Southeast Asia", "Central Asia",
    "Asia - other", "Antarctica", "Other",
]


def build_figure(df: pd.DataFrame) -> go.Figure:
    df = df[(df.area_km2 > 0) & (df.population > 0)].copy()
    df["density_per_km2"] = df.population / df.area_km2

    fig = go.Figure()
    groups = [g for g in ORDER if g in set(df.region_group)] + [
        g for g in sorted(set(df.region_group)) if g not in ORDER
    ]

    def add_marker_trace(d: pd.DataFrame, name: str, color: str, symbol: str) -> None:
        if d.empty:
            return

        parent_display = d["parent_country"].where(d["level"] == "Subdivision", "-")
        pop_year = d["population_year"].fillna("not specified").astype(str)
        custom = list(zip(
            d["name"], parent_display, d["level"], d["area_km2"], d["population"],
            d["density_per_km2"], pop_year,
        ))
        fig.add_trace(go.Scatter(
            x=d["area_km2"], y=d["population"], mode="markers", name=name,
            showlegend=True,
            marker={
                "color": color, "symbol": symbol, "size": 11,
                "opacity": 0.82,
                "line": {"color": "rgba(0,0,0,0.45)", "width": 1.6},
            },
            customdata=custom,
            hovertemplate=(
                "<b>%{customdata[0]}</b><br>"
                "Parent country: %{customdata[1]}<br>"
                "Level: %{customdata[2]}<br>"
                "Area: %{customdata[3]:,.0f} km²<br>"
                "Population: %{customdata[4]:,.0f}<br>"
                "Density: %{customdata[5]:,.2f} people/km²<br>"
                "Population year: %{customdata[6]}"
                "<extra>" + name + "</extra>"
            ),
        ))

    countries = df[df.level != "Subdivision"]
    for group in groups:
        d = countries[countries.region_group == group].copy()
        color, symbol = REGION_STYLE.get(group, ("#444", "circle"))
        add_marker_trace(d, group, color, symbol)

    subdivisions = df[df.level == "Subdivision"]
    for index, parent_country in enumerate(sorted(subdivisions.parent_country.dropna().unique())):
        d = subdivisions[subdivisions.parent_country == parent_country].copy()
        color, symbol = SUBDIVISION_STYLES[index % len(SUBDIVISION_STYLES)]
        add_marker_trace(d, f"Subdivision: {parent_country}", color, symbol)

    xmin, xmax = df.area_km2.min(), df.area_km2.max()
    ymin, ymax = df.population.min(), df.population.max()
    x = np.logspace(math.log10(xmin), math.log10(xmax), 500)
    for rho in [1, 10, 100, 1_000, 10_000]:
        y = rho * x
        mask = (y >= ymin) & (y <= ymax)
        if not mask.any():
            continue
        fig.add_trace(go.Scatter(
            x=x[mask], y=y[mask], mode="lines", showlegend=False,
            line={"color": "rgba(90,90,90,0.45)", "width": 1.2, "dash": "dot"},
            hovertemplate=f"Density = {rho:,} people/km²<extra></extra>",
        ))
        i = np.flatnonzero(mask)[-1]
        fig.add_annotation(
            x=x[i], y=y[i], text=f"{rho:,}/km²", showarrow=False,
            xanchor="right", yanchor="bottom", font={"size": 10, "color": "#666"},
        )

    fig.update_xaxes(type="log", title="Area (km², log scale)", showgrid=True)
    fig.update_yaxes(type="log", title="Population (log scale)", showgrid=True)
    fig.update_layout(
        title="Population vs. area: countries and selected first-level subdivisions",
        dragmode="zoom",
        hovermode="closest",
        showlegend=True,
        legend={"title": {"text": "Regions and subdivisions"}, "itemsizing": "constant"},
        template="plotly_white",
        height=820,
        margin={"l": 80, "r": 30, "t": 70, "b": 70},
    )
    return fig


def main() -> None:
    fig = build_figure(pd.read_csv(DATA))
    fig.write_html(
        OUT, include_plotlyjs=True, full_html=True,
        config={"scrollZoom": True, "displaylogo": False, "responsive": True},
    )
    print(f"Wrote {OUT}")


if __name__ == "__main__":
    main()
