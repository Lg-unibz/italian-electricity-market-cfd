# Data contract

This directory documents the inputs required by the pipelines. It contains
neither original provider files nor generated datasets.

## Historical backtest inputs

Place the following files under `data/raw/`:

```text
data/raw/xlsx/<YYYY>0101_<YYYY>1231_MGP_PrezziZonali.xlsx          # 2015--2024
data/raw/terna/terna_capacity_renewable_sources_<YYYY>.csv         # 2015--2024
data/raw/terna/terna_production_renewable_sources_<YYYY>.csv       # 2015--2024
data/raw/copernicus/onshore_wind_capacity_factor_adm1_2015_2024.csv
```

The canonical Copernicus CSV is long-form with the columns
`timestamp_utc`, `region`, `technology`, and `capacity_factor`. It must cover
20 Italian regions, five onshore technologies, and all Europe/Rome delivery
hours from 2015 through 2024.

## 2024 preprocessing inputs

`scripts/fetch_terna_wind_data.py` downloads the 2024 Terna wind forecast and
gross installed-capacity files. The 2024 GME workbook must be placed under
`data/raw/xlsx/` with the filename documented above.

For regional maps, run `scripts/fetch_istat_boundaries.py`. The Copernicus
normalisation additionally requires the Natural Earth Admin-1 layer, which is
downloaded by `scripts/fetch_natural_earth_admin1.py`.

## Provenance

Record retrieval dates, archive checksums, and any source revision in local
metadata files. The source catalogue and licence notes are in
[`source_manifest.csv`](source_manifest.csv).

The exact file sizes and SHA-256 checksums used for the paper are stored in
`reproducibility/reference_manifest.json`. After acquiring the files, run:

```powershell
python -X utf8 scripts/verify_reproduction.py --inputs-only
```

## What is published where

- GitHub repository: source code, tests, documentation, environment lock,
  source catalogue, and checksum manifest.
- Zenodo software record: the tagged GitHub release.
- Separate Zenodo dataset record: the normalized Copernicus CSV compressed
  with gzip plus all paper result tables and figures.
- Not redistributed: GME workbooks and Terna raw CSV files. Users obtain these
  from the providers and verify them against the reference checksums.

Build the local Zenodo dataset deposit after a successful reproduction run:

```powershell
python -X utf8 scripts/build_zenodo_data_deposit.py
```
