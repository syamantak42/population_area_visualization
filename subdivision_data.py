from __future__ import annotations

from functools import lru_cache

import geopandas as gpd
import pandas as pd
import requests
from pyproj import Geod
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

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


REQUIRED_CACHE_COLUMNS = {
    "name", "parent_country", "level", "iso3", "region_group", "area_km2",
    "population", "population_year", "area_year", "population_source",
    "area_source",
}


def _load_cached_subdivisions(iso3: str) -> pd.DataFrame | None:
    path = CACHE / f"{iso3}.csv"
    if not path.exists():
        return None
    try:
        cached = pd.read_csv(path)
    except (OSError, ValueError, pd.errors.ParserError):
        return None
    if not REQUIRED_CACHE_COLUMNS.issubset(cached.columns) or cached.empty:
        return None
    if not cached.iso3.astype(str).eq(iso3).all():
        return None
    if not cached.population_source.astype(str).eq("Wikidata P1082").all():
        return None
    cached["population"] = pd.to_numeric(cached.population, errors="coerce")
    cached["area_km2"] = pd.to_numeric(cached.area_km2, errors="coerce")
    if cached.population.isna().any() or cached.area_km2.isna().any():
        return None
    if (cached.population <= 0).any() or (cached.area_km2 <= 0).any():
        return None
    cached["density_per_km2"] = cached.population / cached.area_km2
    return cached


def _wikidata_subdivisions(iso3: str) -> pd.DataFrame:
    query = f"""
    SELECT ?subdivision ?subdivisionLabel ?population ?date ?area WHERE {{
      ?country wdt:P298 \"{iso3}\".
      {{ ?country wdt:P150 ?subdivision. }}
      UNION {{
        ?subdivision wdt:P131 ?country;
                     wdt:P31/wdt:P279* wd:Q10864048.
      }}
      UNION {{
        ?subdivision wdt:P17 ?country;
                     wdt:P31/wdt:P279* wd:Q10864048.
      }}
      ?subdivision p:P1082 ?populationStatement.
      ?populationStatement ps:P1082 ?population.
      OPTIONAL {{ ?populationStatement pq:P585 ?date. }}
      OPTIONAL {{ ?subdivision wdt:P2046 ?area. }}
      SERVICE wikibase:label {{ bd:serviceParam wikibase:language \"en\". }}
    }}
    """
    retry = Retry(
        total=4,
        backoff_factor=1,
        status_forcelist=(429, 500, 502, 503, 504),
        allowed_methods=("GET",),
    )
    session = requests.Session()
    session.mount("https://", HTTPAdapter(max_retries=retry))
    response = session.get(
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
            "area_km2": pd.to_numeric(
                row.get("area", {}).get("value"), errors="coerce"
            ),
        }
        for row in bindings
        if "subdivisionLabel" in row and "population" in row
    ]
    if not rows:
        return pd.DataFrame(columns=[
            "pop_name", "population", "population_year", "area_km2"
        ])

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
    cached = _load_cached_subdivisions(iso3)
    if cached is not None:
        return cached

    wikidata = _wikidata_subdivisions(iso3)
    if wikidata.empty:
        raise SubdivisionDataError("Wikidata returned no subdivision populations")

    boundaries = None
    boundary_areas = None
    geod = Geod(ellps="WGS84")
    rows = []
    for _, subdivision in wikidata.iterrows():
        area = subdivision.area_km2
        area_source = "Wikidata P2046"
        if pd.isna(area) or not area > 0:
            if boundaries is None:
                boundaries = _country_boundaries(iso3)
                name_column = "name" if "name" in boundaries.columns else "name_en"
                boundary_areas = pd.DataFrame({
                    "pop_name": boundaries[name_column].astype(str),
                    "parent_country": parent_country,
                    "area_km2": [
                        geodesic_area_km2(geometry, geod)
                        for geometry in boundaries.geometry
                    ],
                })
            boundary = match_population(
                subdivision.pop_name, parent_country, boundary_areas
            )
            if boundary is None or not boundary.area_km2 > 0:
                continue
            area = float(boundary.area_km2)
            area_source = "Natural Earth 1:10m Admin-1 polygon; geodesic area on WGS84"

        rows.append({
            "name": subdivision.pop_name,
            "parent_country": parent_country,
            "level": "Subdivision",
            "iso3": iso3,
            "region_group": region_group,
            "area_km2": float(area),
            "population": float(subdivision.population),
            "population_year": subdivision.population_year,
            "area_year": None,
            "population_source": "Wikidata P1082",
            "area_source": area_source,
        })

    if not rows:
        raise SubdivisionDataError("No subdivisions had both population and area data")

    result = pd.DataFrame(rows)
    result["density_per_km2"] = result.population / result.area_km2
    cache_path = CACHE / f"{iso3}.csv"
    temporary_path = cache_path.with_suffix(".csv.tmp")
    result.to_csv(temporary_path, index=False)
    temporary_path.replace(cache_path)
    return result
