# Population vs. area project

Interactive log-log scatter plot of country population vs. area, with selected first-level subdivisions and equal-density lines.

## Requested behavior

- All country/area points available from the country source are included; India and China remain whole-country points.
- First-level subdivisions are added for India, China, Russia, United States, Canada, Australia, Brazil, Pakistan, and Indonesia.
- Asia is split into West Asia, East Asia, South Asia, Southeast Asia, and Central Asia.
- Country colors and marker shapes encode continent / Asian subregion. Each selected
  country's subdivisions have their own color and marker shape, shown at the same size
  as country markers. Both sets of styles are included in the chart legend.
- Visible legend entries share one ranked high-contrast marker palette. If the current
  filters produce `K` legend entries, the chart uses the first `K` color/symbol pairs;
  hidden or empty groups do not consume styles.
- Hover shows name, parent country, level, area, population, population density, and population year when supplied.
- Both axes are logarithmic.
- Drag a rectangle to zoom; mouse-wheel zoom is enabled; double-click resets.
- Equal-density guides: 1, 10, 100, 1,000, and 10,000 people/km².

## Build

```bash
python -m pip install -r requirements.txt
python build_all.py
```

Output:

- `data/processed/points.csv` — exact rows used in the plot.
- `population_area_density_chart.html` — self-contained interactive Plotly chart.
- `data/processed/unmatched_subdivisions.txt` — only created if a Natural Earth subdivision cannot be matched to a population row.

## Interactive app

```bash
streamlit run app.py
```

The sidebar filters country points by continent and accepts up to seven countries for
first-level subdivision overlays. Countries already present in `points.csv` use those
rows. Other selections use Wikidata population and area data. If Wikidata has a
population but no area, the app matches that subdivision to Natural Earth for its
geodesic area. If usable data cannot be found, the app reports that country and
continues plotting all other available selections.

The on-demand pipeline retries temporary Wikidata failures and accepts common
administrative suffix differences such as `Dhaka` versus `Dhaka Division`. It uses
Wikidata population and area values directly. Natural Earth supplies a geodesic area
only when Wikidata has a real population but no area for that subdivision. Values are
never inferred from national totals.

Successful on-demand results are stored in `data/raw/subdivisions/<ISO3>.csv` and
reused on every later app run without another network request. Cache files are checked
for the expected schema, positive population and area values, and genuine Wikidata
population sources before use. New cache files are written atomically.

## Data sources

1. **Country population** — World Bank indicator `SP.POP.TOTL`; downloader chooses the latest non-null observation per ISO-3 code.
2. **Country area** — World Bank indicator `AG.SRF.TOTL.K2`; downloader chooses the latest non-null observation per ISO-3 code.
3. **Regional grouping** — ISO-3166 regional-code CSV based on the UN M49 geoscheme. Asia is explicitly relabeled into the five requested subregions. The Americas are split into North America (Northern America + Central America + Caribbean) and South America.
4. **Subdivision population, except Indonesia** — Johns Hopkins CSSE `UID_ISO_FIPS_LookUp_Table.csv`, using top-level `Province_State` rows. This is a historical COVID-era lookup, so subdivision population years are not uniform; the source field is kept in the output.
5. **Subdivision area** — Natural Earth 1:10m Admin-1 polygons. Area is calculated geodesically on WGS84 from the polygon geometry.
6. **Indonesia subdivision population** — table from the Wikipedia page `Provinces of Indonesia`, used only because the JHU UID lookup has no Indonesia province rows. The downloader records the chosen population column in `population_source`.
7. **On-demand subdivision population** — Wikidata property `P1082`, used by the interactive app for selected countries not already present in the processed data.

### Important comparability note

The chart is intended for geographic/demographic comparison, **not a same-date census comparison**. Country values use the latest World Bank observation available for each indicator. Subdivision populations come from source tables with different reference dates. Keep `population_year`, `population_source`, and `area_source` when doing quantitative analysis.

### Administrative-boundary note

Natural Earth states that its Admin-1 theme is difficult to keep current because countries frequently rearrange first-level units, and it uses de-facto boundary treatment by default. The build writes any unmatched names to `data/processed/unmatched_subdivisions.txt` rather than inventing or silently approximating values.

## Cached files included in this ZIP

- `data/raw/UID_ISO_FIPS_LookUp_Table.csv`
- `data/raw/iso_regions.csv`
- `data/raw/previous_plot_snapshot.csv` (the earlier plot data from this conversation, retained only as provenance/reference)

`download_data.py` reuses cached raw files when present and downloads missing/current inputs.
