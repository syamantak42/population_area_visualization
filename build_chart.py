from __future__ import annotations

from pathlib import Path
import math

import numpy as np
import pandas as pd
import plotly.graph_objects as go

ROOT = Path(__file__).resolve().parent
DATA = ROOT / "data" / "processed" / "points.csv"
OUT = ROOT / "population_area_density_chart.html"

MARKER_STYLES = [
    ("#0072B2", "circle"),
    ("#E69F00", "diamond"),
    ("#009E73", "square"),
    ("#D55E00", "triangle-up"),
    ("#CC79A7", "star"),
    ("#56B4E9", "cross"),
    ("#6A3D9A", "triangle-down"),
    ("#B2182B", "hexagon"),
    ("#1B7837", "pentagon"),
    ("#2166AC", "x"),
    ("#E08214", "triangle-right"),
    ("#762A83", "star-diamond"),
    ("#008080", "hexagram"),
    ("#C51B7D", "diamond-open"),
    ("#4D4D4D", "square-open"),
    ("#A6761D", "triangle-left"),
    ("#01665E", "hourglass"),
    ("#8C510A", "triangle-ne"),
    ("#5E3C99", "pentagon-open"),
    ("#B35806", "cross-open"),
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
    visible_groups = [
        group for group in groups if (countries.region_group == group).any()
    ]
    subdivisions = df[df.level == "Subdivision"]
    subdivision_parents = sorted(subdivisions.parent_country.dropna().unique())
    legend_names = visible_groups + [
        f"Subdivision: {parent}" for parent in subdivision_parents
    ]
    legend_styles = {
        name: MARKER_STYLES[index % len(MARKER_STYLES)]
        for index, name in enumerate(legend_names)
    }

    for group in visible_groups:
        d = countries[countries.region_group == group].copy()
        color, symbol = legend_styles[group]
        add_marker_trace(d, group, color, symbol)

    for parent_country in subdivision_parents:
        d = subdivisions[subdivisions.parent_country == parent_country].copy()
        legend_name = f"Subdivision: {parent_country}"
        color, symbol = legend_styles[legend_name]
        add_marker_trace(d, legend_name, color, symbol)

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
