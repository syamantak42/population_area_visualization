from __future__ import annotations

import pandas as pd
import streamlit as st

from build_chart import DATA, build_figure
from subdivision_data import download_subdivisions

CONTINENT_REGIONS = {
    "Africa": ["Africa"],
    "Asia": ["West Asia", "East Asia", "South Asia", "Southeast Asia", "Central Asia", "Asia - other"],
    "Europe": ["Europe"],
    "North America": ["North America"],
    "South America": ["South America"],
    "Oceania": ["Oceania"],
    "Antarctica": ["Antarctica"],
}

st.set_page_config(page_title="Population and area explorer", layout="wide")
st.markdown("""
<style>
    .block-container {max-width: 1440px; padding-top: 2rem;}
    [data-testid="stSidebar"] {background: #f6f7f9;}
    h1 {letter-spacing: 0; font-weight: 650;}
    .stAlert {border-radius: 6px;}
</style>
""", unsafe_allow_html=True)


@st.cache_data
def load_points() -> pd.DataFrame:
    return pd.read_csv(DATA)


@st.cache_data(ttl=86_400, show_spinner=False)
def fetch_subdivisions(
    iso3: str,
    country: str,
    region: str,
) -> pd.DataFrame:
    return download_subdivisions(iso3, country, region)


points = load_points()
country_rows = points[points.level == "Country"].drop_duplicates("name").sort_values("name")
country_lookup = country_rows.set_index("name")[["iso3", "region_group"]].to_dict("index")
existing_subdivision_iso3 = set(
    points.loc[points.level == "Subdivision", "iso3"].dropna()
)

st.title("Population and area explorer")
st.caption("Compare countries and selected first-level subdivisions on a logarithmic scale.")

with st.sidebar:
    st.header("Chart filters")
    selected_continents = st.multiselect(
        "Continents",
        options=list(CONTINENT_REGIONS),
        default=list(CONTINENT_REGIONS),
    )
    selected_countries = st.multiselect(
        "Country subdivisions",
        options=list(country_lookup),
        max_selections=7,
        placeholder="Choose up to 7 countries",
    )
    st.caption(f"{len(selected_countries)} of 7 countries selected")

selected_regions = {
    region
    for continent in selected_continents
    for region in CONTINENT_REGIONS[continent]
}
country_points = points[
    (points.level == "Country") & points.region_group.isin(selected_regions)
].copy()

subdivision_frames = []
warnings = []
for country in selected_countries:
    metadata = country_lookup[country]
    if metadata["iso3"] in existing_subdivision_iso3:
        subdivisions = points[
            (points.level == "Subdivision") & (points.iso3 == metadata["iso3"])
        ].copy()
    else:
        try:
            with st.spinner(f"Loading subdivision data for {country}..."):
                subdivisions = fetch_subdivisions(
                    metadata["iso3"],
                    country,
                    metadata["region_group"],
                )
        except Exception:
            subdivisions = pd.DataFrame()
            warnings.append(f"Data for {country} subdivisions could not be found.")
    if not subdivisions.empty:
        subdivision_frames.append(subdivisions)

for warning in warnings:
    st.warning(warning)

chart_data = pd.concat([country_points, *subdivision_frames], ignore_index=True)
if chart_data.empty:
    st.info("Select at least one continent or a country with available subdivision data.")
else:
    st.plotly_chart(build_figure(chart_data), use_container_width=True)
