from __future__ import annotations

from functools import lru_cache

import geopandas as gpd
import pandas as pd
import requests
from pyproj import Geod

from download_data import (
    NE_ADMIN1_URL,
    RAW,
    download,
    geodesic_area_km2,
    match_population,
)

WIKIDATA_SPARQL_URL = "https://query.wikidata.org/sparql"
CACHE = RAW / "subdivisions"
CACHE.mkdir(parents=True, exist_ok=True)


class SubdivisionDataError(RuntimeError):
    pass


def _wikidata_population(iso3: str) -> pd.DataFrame:
    query = f"""
    SELECT ?subdivision ?subdivisionLabel ?population ?date WHERE {{
      ?country wdt:P298 \"{iso3}\";
               wdt:P150 ?subdivision.
      ?subdivision p:P1082 ?populationStatement.
      ?populationStatement ps:P1082 ?population.
      OPTIONAL {{ ?populationStatement pq:P585 ?date. }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language \"en\". }}
    }}
    """
    response = requests.get(
        WIKIDATA_SPARQL_URL,
        params={"query": query, "format": "json"},
        headers={"User-Agent": "population-area-visualization/2.0"},
        timeout=90,
    )
    response.raise_for_status()
    bindings = response.json().get("results", {}).get("bindings", [])
    rows = [
        {
            "pop_name": row["subdivisionLabel"]["value"],
            "population": pd.to_numeric(row["population"]["value"], errors="coerce"),
            "population_year": row.get("date", {}).get("value", "")[:4] or None,
            "date": row.get("date", {}).get("value", ""),
        }
        for row in bindings
        if "subdivisionLabel" in row and "population" in row
    ]
    if not rows:
        raise SubdivisionDataError("Wikidata returned no subdivision populations")

    populations = pd.DataFrame(rows).dropna(subset=["population"])
    populations = populations[populations.population > 0].copy()
    populations = populations.sort_values(["pop_name", "date"], ascending=[True, False])
    return populations.drop_duplicates("pop_name")


@lru_cache(maxsize=1)
def _all_boundaries() -> gpd.GeoDataFrame:
    path = download(NE_ADMIN1_URL, RAW / "ne_10m_admin_1_states_provinces.geojson")
    return gpd.read_file(path)


def _country_boundaries(iso3: str) -> gpd.GeoDataFrame:
    boundaries = _all_boundaries()
    mask = pd.Series(False, index=boundaries.index)
    for column in ["adm0_a3", "gu_a3", "sov_a3"]:
        if column in boundaries.columns:
            mask |= boundaries[column].astype(str).eq(iso3)
    result = boundaries[mask].copy()
    if result.empty:
        raise SubdivisionDataError("Natural Earth returned no subdivision boundaries")
    return result


def download_subdivisions(
    iso3: str,
    parent_country: str,
    region_group: str,
) -> pd.DataFrame:
    populations = _wikidata_population(iso3)
    boundaries = _country_boundaries(iso3)
    name_column = "name" if "name" in boundaries.columns else "name_en"

    populations["parent_country"] = parent_country
    geod = Geod(ellps="WGS84")
    rows = []
    for _, boundary in boundaries.iterrows():
        name = str(boundary[name_column])
        population = match_population(name, parent_country, populations)
        if population is None:
            continue
        area = geodesic_area_km2(boundary.geometry, geod)
        if not area > 0:
            continue
        rows.append({
            "name": name,
            "parent_country": parent_country,
            "level": "Subdivision",
            "iso3": iso3,
            "region_group": region_group,
            "area_km2": area,
            "population": float(population.population),
            "population_year": population.population_year,
            "area_year": None,
            "population_source": "Wikidata P1082",
            "area_source": "Natural Earth 1:10m Admin-1 polygon; geodesic area on WGS84",
        })

    if not rows:
        raise SubdivisionDataError("subdivision names could not be matched across data sources")

    result = pd.DataFrame(rows)
    result["density_per_km2"] = result.population / result.area_km2
    result.to_csv(CACHE / f"{iso3}.csv", index=False)
    return result
