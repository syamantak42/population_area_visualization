from __future__ import annotations

from io import StringIO
import json
import math
import re
import unicodedata
from pathlib import Path

import geopandas as gpd
import pandas as pd
import requests
from pyproj import Geod
from rapidfuzz import fuzz, process

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "data" / "raw"
PROCESSED = ROOT / "data" / "processed"
RAW.mkdir(parents=True, exist_ok=True)
PROCESSED.mkdir(parents=True, exist_ok=True)

REGIONS_URL = "https://raw.githubusercontent.com/lukes/iso-3166-countries-with-regional-codes/master/all/all.csv"
JHU_URL = "https://raw.githubusercontent.com/CSSEGISandData/COVID-19/master/csse_covid_19_data/UID_ISO_FIPS_LookUp_Table.csv"
NE_ADMIN1_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_10m_admin_1_states_provinces.geojson"
WB_URL = "https://api.worldbank.org/v2/country/all/indicator/{indicator}?format=json&per_page=20000"
INDONESIA_URL = "https://en.wikipedia.org/wiki/Provinces_of_Indonesia"

TARGETS = {
    "IND": ("India", "India"),
    "CHN": ("China", "China"),
    "RUS": ("Russia", "Russia"),
    "USA": ("United States", "US"),
    "CAN": ("Canada", "Canada"),
    "AUS": ("Australia", "Australia"),
    "BRA": ("Brazil", "Brazil"),
    "PAK": ("Pakistan", "Pakistan"),
    "IDN": ("Indonesia", "Indonesia"),
}

# Normalization aliases are intentionally explicit. They are only used after exact
# normalized matching, and fuzzy matching is conservative.
ALIASES = {
    "united states": {
        "district of columbia": "district of columbia",
    },
    "brazil": {
        "federal district": "distrito federal",
    },
    "pakistan": {
        "azad kashmir": "azad jammu and kashmir",
        "islamabad capital territory": "islamabad",
        "n w f p": "khyber pakhtunkhwa",
    },
    "russia": {
        "republic of adygea": "adygea republic",
        "republic of altai": "altai republic",
        "republic of bashkortostan": "bashkortostan republic",
        "republic of buryatia": "buryatia republic",
        "republic of dagestan": "dagestan republic",
        "republic of ingushetia": "ingushetia republic",
        "republic of kalmykia": "kalmykia republic",
        "republic of karelia": "karelia republic",
        "republic of khakassia": "khakassia republic",
        "republic of mordovia": "mordovia republic",
        "republic of north ossetia alania": "north ossetia alania republic",
        "republic of tatarstan": "tatarstan republic",
        "republic of tuva": "tuva republic",
        "udmurt republic": "udmurtia republic",
    },
}


def download(url: str, path: Path, force: bool = False) -> Path:
    if path.exists() and not force:
        return path
    print(f"Downloading {url}")
    r = requests.get(url, timeout=120)
    r.raise_for_status()
    path.write_bytes(r.content)
    return path


def latest_world_bank(indicator: str, raw_name: str, value_name: str) -> pd.DataFrame:
    path = RAW / raw_name
    if not path.exists():
        r = requests.get(WB_URL.format(indicator=indicator), timeout=120)
        r.raise_for_status()
        path.write_text(r.text, encoding="utf-8")
    payload = json.loads(path.read_text(encoding="utf-8"))
    rows = payload[1]
    df = pd.DataFrame(
        {
            "iso3": [r["countryiso3code"] for r in rows],
            "year": [pd.to_numeric(r["date"], errors="coerce") for r in rows],
            value_name: [r["value"] for r in rows],
        }
    )
    df = df[df["iso3"].str.len().eq(3) & df[value_name].notna()].copy()
    df["year"] = pd.to_numeric(df["year"], errors="coerce")
    df = df.sort_values(["iso3", "year"], ascending=[True, False]).drop_duplicates("iso3")
    return df


def normalize(text: object) -> str:
    s = "" if pd.isna(text) else str(text)
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    s = s.lower().replace("&", " and ")
    s = re.sub(r"\brepublic of\b", "republic of", s)
    s = re.sub(r"[^a-z0-9]+", " ", s).strip()
    return re.sub(r"\s+", " ", s)


def normalize_admin_name(text: object) -> str:
    value = normalize(text)
    suffixes = (
        "autonomous community", "autonomous province", "autonomous region",
        "capital territory", "federal district", "union territory",
        "administrative region", "division", "province", "state", "region",
        "governorate", "department", "district", "territory", "prefecture",
        "oblast", "republic", "county", "parish",
    )
    for suffix in suffixes:
        if value.endswith(" " + suffix):
            return value[: -(len(suffix) + 1)].strip()
    return value


def region_group(row: pd.Series) -> str:
    region = str(row.get("region", ""))
    sub = str(row.get("sub-region", ""))
    intermediate = str(row.get("intermediate-region", ""))
    if region == "Asia":
        return {
            "Western Asia": "West Asia",
            "Eastern Asia": "East Asia",
            "Southern Asia": "South Asia",
            "South-eastern Asia": "Southeast Asia",
            "Central Asia": "Central Asia",
        }.get(sub, "Asia - other")
    if region == "Americas":
        if intermediate == "South America":
            return "South America"
        return "North America"  # Northern America + Central America + Caribbean
    return region or "Other"


def load_regions() -> pd.DataFrame:
    path = download(REGIONS_URL, RAW / "iso_regions.csv")
    df = pd.read_csv(path, dtype={"alpha-3": str})
    df["region_group"] = df.apply(region_group, axis=1)
    return df


def build_country_points(regions: pd.DataFrame) -> pd.DataFrame:
    pop = latest_world_bank("SP.POP.TOTL", "world_bank_population.json", "population")
    area = latest_world_bank("AG.SRF.TOTL.K2", "world_bank_surface_area.json", "area_km2")
    countries = regions[["name", "alpha-3", "region_group"]].rename(columns={"alpha-3": "iso3"})
    df = countries.merge(pop, on="iso3", how="left", suffixes=("", "_pop"))
    df = df.merge(area, on="iso3", how="left", suffixes=("_population", "_area"))
    df = df.rename(columns={"year_population": "population_year", "year_area": "area_year"})
    df = df[df["population"].notna() & df["area_km2"].notna() & (df["area_km2"] > 0)].copy()
    df["parent_country"] = df["name"]
    df["level"] = "Country"
    df["population_source"] = "World Bank SP.POP.TOTL"
    df["area_source"] = "World Bank AG.SRF.TOTL.K2"
    return df[[
        "name", "parent_country", "level", "iso3", "region_group", "area_km2",
        "population", "population_year", "area_year", "population_source", "area_source"
    ]]


def jhu_population_table() -> pd.DataFrame:
    path = download(JHU_URL, RAW / "UID_ISO_FIPS_LookUp_Table.csv")
    df = pd.read_csv(path)
    rows = []
    for iso3, (parent, jhu_name) in TARGETS.items():
        if iso3 == "IDN":
            continue
        d = df[(df["Country_Region"] == jhu_name) & df["Province_State"].notna()].copy()
        top = d[d["Admin2"].isna()].copy()
        top = top[top["Population"].notna() & (top["Population"] > 0)]
        # Known non-administrative / non-state entries are removed. Natural Earth matching
        # also acts as a second filter.
        bad = {"unknown", "diamond princess", "grand princess", "recovered"}
        top = top[~top["Province_State"].map(normalize).isin(bad)]
        for _, r in top.iterrows():
            rows.append({
                "iso3": iso3,
                "parent_country": parent,
                "pop_name": r["Province_State"],
                "population": float(r["Population"]),
                "population_year": None,
                "population_source": "Johns Hopkins CSSE UID lookup (population field)",
            })
    return pd.DataFrame(rows)


def indonesia_population_table() -> pd.DataFrame:
    # JHU's UID lookup has no Indonesia province rows. Use the province table on the
    # Indonesia provinces page as an explicit fallback; the table/column selected is
    # saved into the processed data source field.
    html = requests.get(
    INDONESIA_URL,
    headers={"User-Agent": "population-area-visualization/1.0"},
    timeout=120,
)
    html.raise_for_status()

    tables = pd.read_html(StringIO(html.text))
    best = None
    for t in tables:
        t = t.copy()
        if isinstance(t.columns, pd.MultiIndex):
            t.columns = [" ".join(str(x) for x in c if str(x) != "nan").strip() for c in t.columns]
        else:
            t.columns = [str(c) for c in t.columns]
        cols = [c.lower() for c in t.columns]
        if any("province" in c for c in cols) and any("population" in c for c in cols):
            best = t
            break
    if best is None:
        raise RuntimeError("Could not locate Indonesia province population table")
    province_col = next(c for c in best.columns if "province" in c.lower())
    pop_candidates = [c for c in best.columns if "population" in c.lower()]
    pop_col = pop_candidates[-1]
    year_match = re.findall(r"20\d{2}", pop_col)
    pop_year = int(year_match[-1]) if year_match else None
    out = pd.DataFrame({
        "iso3": "IDN",
        "parent_country": "Indonesia",
        "pop_name": best[province_col].astype(str).str.replace(r"\[[^\]]+\]", "", regex=True).str.strip(),
        "population": pd.to_numeric(best[pop_col].astype(str).str.replace(r"[^0-9.]", "", regex=True), errors="coerce"),
    })
    out = out[out["population"].notna() & (out["population"] > 0)].copy()
    out["population_year"] = pop_year
    out["population_source"] = f"Wikipedia: Provinces of Indonesia ({pop_col})"
    return out


def geodesic_area_km2(geom, geod: Geod) -> float:
    if geom is None or geom.is_empty:
        return math.nan
    area, _ = geod.geometry_area_perimeter(geom)
    return abs(area) / 1_000_000.0


def match_population(ne_name: str, parent: str, pop_df: pd.DataFrame) -> pd.Series | None:
    d = pop_df[pop_df["parent_country"] == parent].copy()
    if d.empty:
        return None
    d["norm"] = d["pop_name"].map(normalize)
    key = normalize(ne_name)
    alias = ALIASES.get(parent.lower(), {}).get(key)
    if alias:
        key = normalize(alias)
    exact = d[d["norm"] == key]
    if len(exact) == 1:
        return exact.iloc[0]
    admin_key = normalize_admin_name(ne_name)
    d["admin_norm"] = d["pop_name"].map(normalize_admin_name)
    admin_exact = d[d["admin_norm"] == admin_key]
    if len(admin_exact) == 1:
        return admin_exact.iloc[0]
    choices = d["admin_norm"].tolist()
    hit = process.extractOne(admin_key, choices, scorer=fuzz.token_sort_ratio)
    if hit and hit[1] >= 88:
        return d[d["admin_norm"] == hit[0]].iloc[0]
    return None


def build_subdivision_points(regions: pd.DataFrame) -> pd.DataFrame:
    ne_path = download(NE_ADMIN1_URL, RAW / "ne_10m_admin_1_states_provinces.geojson")
    ne = gpd.read_file(ne_path)
    geod = Geod(ellps="WGS84")

    pop = pd.concat([jhu_population_table(), indonesia_population_table()], ignore_index=True)
    region_map = regions.set_index("alpha-3")["region_group"].to_dict()
    out = []
    unmatched = []

    for iso3, (parent, _) in TARGETS.items():
        # Natural Earth normally uses adm0_a3. Fall back to gu_a3/sov_a3 if needed.
        mask = pd.Series(False, index=ne.index)
        for col in ["adm0_a3", "gu_a3", "sov_a3"]:
            if col in ne.columns:
                mask |= ne[col].astype(str).eq(iso3)
        d = ne[mask].copy()
        if d.empty:
            unmatched.append((parent, "<no Natural Earth admin-1 rows>"))
            continue
        name_col = "name" if "name" in d.columns else "name_en"
        for _, r in d.iterrows():
            ne_name = str(r[name_col])
            pm = match_population(ne_name, parent, pop)
            if pm is None:
                unmatched.append((parent, ne_name))
                continue
            area = geodesic_area_km2(r.geometry, geod)
            if not (area > 0):
                unmatched.append((parent, ne_name + " [bad area]"))
                continue
            out.append({
                "name": ne_name,
                "parent_country": parent,
                "level": "Subdivision",
                "iso3": iso3,
                "region_group": region_map.get(iso3, "Other"),
                "area_km2": area,
                "population": float(pm["population"]),
                "population_year": pm.get("population_year"),
                "area_year": None,
                "population_source": pm["population_source"],
                "area_source": "Natural Earth 1:10m Admin-1 polygon; geodesic area on WGS84",
            })

    if unmatched:
        report = PROCESSED / "unmatched_subdivisions.txt"
        report.write_text("\n".join(f"{c}\t{n}" for c, n in unmatched), encoding="utf-8")
        print(f"WARNING: {len(unmatched)} subdivision names were not matched. See {report}")

    return pd.DataFrame(out)


def main() -> None:
    regions = load_regions()
    countries = build_country_points(regions)
    subdivisions = build_subdivision_points(regions)
    points = pd.concat([countries, subdivisions], ignore_index=True)
    points["population"] = pd.to_numeric(points["population"], errors="coerce")
    points["area_km2"] = pd.to_numeric(points["area_km2"], errors="coerce")
    points = points[(points["population"] > 0) & (points["area_km2"] > 0)].copy()
    points["density_per_km2"] = points["population"] / points["area_km2"]
    points = points.sort_values(["level", "region_group", "parent_country", "name"])
    out = PROCESSED / "points.csv"
    points.to_csv(out, index=False)
    print(f"Wrote {len(points):,} plotted points to {out}")
    print(f"Countries: {(points.level == 'Country').sum():,}")
    print(f"Subdivisions: {(points.level == 'Subdivision').sum():,}")


if __name__ == "__main__":
    main()
