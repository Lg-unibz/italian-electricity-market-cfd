# Historical Italian Wind CfD Backtest, 2015-2024

This document is the authoritative technical specification of the empirical
pipeline. `project_status.md` records decisions and progress, but intentionally
does not repeat the data contracts, equations, output schemas, or validation
rules defined here.

## Scope

The Phase 2 backtest compares market-only revenue, a conventional two-sided
CfD, a Newbery-inspired Zonal Yardstick CfD, and a Schlecht-inspired Financial
CfD. It uses observed hourly price and wind-resource variability only. It does
not forecast future electricity prices, bootstrap synthetic years, calculate
NPV/ROI, or introduce an original hybrid mechanism.

The implementation is in:

```text
src/cfd_analysis/historical_inputs.py
src/cfd_analysis/copernicus_normalization.py
src/cfd_analysis/mechanisms.py
src/cfd_analysis/historical_backtest.py
src/cfd_analysis/geography.py
scripts/run_historical_cfd_backtest.py
```

## Homogeneous Hourly Wind Input

The backtest deliberately has no Terna-hourly fallback. The expected local
Copernicus file is:

```text
data/raw/copernicus/onshore_wind_capacity_factor_adm1_2015_2024.csv
```

It must be a long CSV with these columns:

```text
timestamp_utc,region,technology,capacity_factor
2014-12-31T23:00:00Z,Piemonte,<technology label>,0.123
```

Requirements:

- source: Copernicus Climate Data Store dataset `sis-energy-global-reanalysis`;
- indicator: onshore wind power capacity factor;
- spatial aggregation: ADM1/subnational;
- temporal aggregation: hourly;
- geography: all 20 Italian regions;
- technological specifications: all five onshore series offered by the dataset
  (`IC2.5HH100`, `IC2.5HH100E`, `IC3.3HH84`, `IC6HH135`, and
  `IC6HH135E`), representing three turbine designs and the alternative wind
  inputs available for hub heights at or above 100 m;
- values bounded to `[0,1]`;
- timestamps expressed as UTC starts of hourly intervals.

Because GME delivery hours follow `Europe/Rome`, complete local-year coverage
requires UTC timestamps from `2014-12-31T23:00:00Z` through
`2024-12-31T22:00:00Z`. The loader validates each technology-region-year grid,
including the 23-hour and 25-hour daylight-saving days. Wide CSVs are also
accepted when technology columns start with `capacity_factor_` or `cf_`.

The CDS dataset is *Global climate and energy indicators from 1950 to present
derived from reanalysis*, DOI `10.24381/3bb607bd`. CDS authentication and
licence acceptance are user-specific, so the raw export remains a local,
ignored provenance input.

After configuring CDS API credentials and accepting the CC-BY licence on the
dataset page, the exact official requests can be run with:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\fetch_copernicus_wind_archives.py
```

The CDS ADM1 product is global. The downloaded archives therefore remain a raw
intermediate. For Italy the official CSV columns contain 110 coded provincial
units (`ITA-*`), rather than 20 named regions. Download the matching Natural
Earth 10m Admin-1 layer and normalize the archives with:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\fetch_natural_earth_admin1.py
.\.venv\Scripts\python.exe -X utf8 scripts\prepare_copernicus_wind.py
```

The normalizer reads directly from the ZIP members, selects the 110 Italian
columns, and maps them to the 20 regions through Natural Earth's `adm1_code`
and `region` fields. Each regional hourly profile is a geodesic-area-weighted
mean of its provincial units. The weights, Natural Earth URL, retrieval date,
version, and checksums are recorded locally. The final validation requires
exactly 8,767,200 rows: five technologies, 20 regions, and every Europe/Rome
delivery hour in 2015-2024, including the December 2014 UTC boundary hour.

For every technology and year, regional Copernicus full-load hours are scaled
by Terna regional installed capacity and aggregated nationally. One technology
is then selected for the entire decade by the lowest mean absolute error
against national annual Terna gross wind MWh/MW. Terna annual production is
used only in this validation. The selected `IC2.5HH100E` configuration
corresponds to the GE Energy 2.5--103 onshore turbine (2.5 MW, 100 m hub
height, 103 m rotor diameter); the resulting regional series is referred to as
the Reference Onshore Wind Profile (ROWP). ROWP is a representative model
profile, not an identification of the actual turbine fleet in each region.

## Prices, Mapping, and Real Values

GME zonal price workbooks are read for 2015-2024. The row sequence is aligned
to `Europe/Rome` delivery hours and converted to UTC, preserving daylight-saving
transitions.

The historical mapping implements the Terna zonal revision effective on
1 January 2021:

- through 2020, Umbria is in Centro Nord and Calabria is in Sud;
- from 2021, Umbria is in Centro Sud and Calabria is a separate zone.

All nominal GME prices are converted to real 2024 euro using the Italian
all-items annual-average HICP (`Eurostat prc_hicp_aind`, DOI
`10.2908/PRC_HICP_AIND`). The cost assumptions are already expressed in real
2024 euro.

## Strike and Settlement Logic

The common assumptions are CAPEX `1,580,000 EUR/MW`, OPEX
`35,000 EUR/MW-year`, WACC `6.5%`, and a 20-year useful life. `K_P50` is the
primary calibration, using the median of the ten annual national Copernicus
full-load-hour observations. `K_P25` uses the lower quartile as a conservative
calibration stress test for the volumetric contracts. The source recorded in
the strike table is the supporting documentation to ARERA Resolution
`239/2025/R/efr` for an onshore wind installation close to 1 MW.

For each regional representative 1 MW plant:

- `Q_h` is its Copernicus ADM1 capacity factor in MWh/MW-hour;
- `P_h` is the mapped GME zonal price in real 2024 EUR/MWh;
- `M_h` is the annual-capacity-weighted mean Copernicus profile of all regions
  in the same historical bidding zone.

The conventional settlement is `(K-P_h)Q_h`. The Zonal Yardstick settlement is
`(K-P_h)M_h`, where `M_h` is the ex-post, capacity-weighted zonal profile. The
Financial CfD adds a fixed hourly payment and returns `max(P_h,0)M_h` to the
public counterparty. Its annual fixed leg is
`F = CAPEX × CRF + OPEX = 178,395.1047 EUR/MW-year`, distributed evenly over
the delivery hours of each year. `F` is independent of `K_P50` and `K_P25`.

Schlecht et al. determine the fixed remuneration competitively in procurement.
The backtest instead uses annualised cost as a transparent cost-based proxy for
that auction outcome. This anchors the fixed leg to a zero-profit cost benchmark
but does not guarantee realised zero profit for each regional proxy asset,
because revenue retains the basis term `P_h(Q_h-M_h)`. Both advanced settlement
legs are independent of the representative asset's own production. For public
accounting, the Financial-CfD fixed payment is gross top-up and its benchmark
restitution is gross clawback. The duration estimate associated with Newbery's
proposal uses cumulative production `Q_h` to estimate the years required to
reach 30,000 MWh/MW.

## Geographic Input

Download and extract the official generalized ISTAT 2024 boundaries with:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\fetch_istat_boundaries.py
```

The script records the URL, retrieval date, SHA-256 checksum, CRS, and selected
regional shapefile under `data/raw/istat`. These files remain ignored by Git.
The plotting code reads the shapefile and DBF directly, validates an exact
20-region join, and overlays the current Italian market-zone boundaries as a
visual guide.

## Run and Outputs

After the Copernicus CSV is present:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\run_historical_cfd_backtest.py
```

For economic tables without maps:

```powershell
.\.venv\Scripts\python.exe -X utf8 scripts\run_historical_cfd_backtest.py --skip-maps
```

Generated files are isolated under:

```text
results/historical_cfd_backtest_2015_2024/tables
results/historical_cfd_backtest_2015_2024/figures
```

The tables include annual regional and national results, the capacity-weighted
national-portfolio summary, the regional metric summary with Sharpe Ratios,
annual market-only Value Factors, strike calibration, Copernicus-Terna
technology validation, GME price-sign and HICP audits, and the historical
mapping audit. The ten-year regional Value Factor summary is written as
`market_only_value_factor_10_year_mean.csv`. The regional comparison source contains 20 regions for
market-only and each mechanism/scenario. A second source reports the mean,
standard deviation, quartiles, and range of each mapped metric across the
unweighted regions. The Newbery cumulative-volume diagnostic is written as
`zonal_yardstick_30000_mwh_limit.csv`.
The full annual Value Factor statistics are written as
`regional_value_factor_summary.csv`; map-source exports represent infinite
Sharpe Ratios as the LaTeX-safe strings `+\\infty` and `-\\infty`.

In accordance with cycle `CFD-2026-09-15-01` pre-submission refinements:
- **Primary Risk Metric Hierarchy**: Annual revenue standard deviation ($s_r$) is the
  primary measure of inter-annual cash-flow risk in main figures and tables. The
  Sharpe-type ratio is retained as a secondary summary indicator; cases with zero
  annual dispersion ($s_r = 0$) are formally designated as "Ratio undefined due
  to zero annual variance" (with `+\infty` reserved strictly as a visual plot label).
- **Regional and Zonal Proxy Validation**: All 200 region-years (2015–2024) are
  disclosed in `regional_proxy_validation_annual.csv`. Summary metrics (MAE,
  bias, RMSE, Pearson $r$, rank-based Spearman $\rho$) are provided in
  `regional_proxy_validation.csv` across three populations: all 200 observations,
  the primary diagnostic population of 187 region-years with positive realised
  production, and a sensitivity subset of 147 region-years with installed
  capacity $\ge 10$ MW. Capacity-weighted aggregates for historical bidding zones
  confirm strong temporal tracking ($r \ge 0.72$ in major wind zones).
- **Multi-Zone Benchmark Concentration**: Leave-one-out benchmarking ($M^{-r}_{zhy}$)
  is generalised across all historical multi-region zones (*Centro Nord, Centro
  Sud, Nord, Sud*) for Financial CfD and Yardstick $K_{P50}$, yielding
  `zonal_concentration_annual.csv` (352 rows) and `zonal_concentration_summary.csv`
  (36 rows). The descriptive figure `benchmark_concentration_risk_compression.png`
  plots own capacity share against the standard-deviation compression ratio
  ($s_r^{\mathrm{Inc}} / s_r^{\mathrm{LOO}}$).
- **Zonal Public Settlement and Crisis Sensitivity**: Public cash flows are reported
  at bidding-zone resolution in `zonal_public_settlement_annual.csv` and
  `zonal_public_settlement_summary.csv`. The summary reports full-sample annual
  mean, annual median, and an 8-year view excluding the 2021–2022 energy crisis.

The runner generates:
- One 1x3 market-only figure containing mean revenue, annual revenue SD, and ten-year mean Value Factor;
- Two 1x3 primary CfD comparison figures for $K_{P50}$ (mean revenue, revenue SD, net public cost incidence);
- Two corresponding 1x3 $K_{P25}$ figures (mean revenue, revenue SD, net public cost);
- The regional wind-resource figure;
- The multi-zone concentration risk-compression scatter plot;
- The focused Centro Sud self-influence diagnostic figure.

The national portfolio summary is retained for public cash-flow accounting and
to expose the identity created by the benchmark definition. Conventional and
Zonal Yardstick regional outcomes generally differ, while their capacity-weighted
zonal and national totals coincide because the weighted deviations from `M_h`
sum to zero. The Financial CfD's near-zero national portfolio risk is interpreted with
the GME price-sign audit; the 2015-2024 sample contains no negative prices.

Each comparison figure maps the 20 regional values directly and uses one common
colour scale across the three CfD mechanisms and both strike scenarios. Revenue
standard deviation uses a linear scale matching mean revenue. Sharpe Ratios in
appendix maps use a logarithmic colour scale so that the finite 1.80--85.57 range does
not compress most regions near the lower bound. Net public cost uses a
zero-centred symmetric-logarithmic scale with a linear interval of
plus-or-minus 5 kEUR/MW-year, preserving the sign and zero midpoint while
resolving moderate and extreme flows. Infinite Sharpe Ratios are shown at the
upper plotting limit and annotated explicitly.
The current market-zone boundaries are visual context only: all hourly prices,
benchmarks, and settlements use the historically valid pre-/post-2021 mapping.

## Validation

Run:

```powershell
$env:PYTHONPATH = "src"
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall src scripts tests
```

The code validates capacity-factor bounds and coverage, the 20-region joins,
the historical mapping, `producer revenue = market revenue + settlement`,
the conventional `K x Q` identity, production independence of the advanced
settlement legs, separate Financial-CfD gross flows, the 140-row regional summary,
the complete 80-row primary-strike comparison, regional distribution
statistics, asset-level differences alongside the capacity-weighted
Conventional-Yardstick portfolio identity, the invariant cost-based fixed leg,
and `top-up - clawback = net public cost` at hourly and annual aggregation
levels.
