# Project Status and Research Roadmap

**Project:** Historical comparison of wind-support mechanisms in the Italian
electricity market

**Working journal target:** *Energy Policy*

**Status date:** 21 July 2026

**Current phase:** Phase 2 completed — final manuscript drafting and Overleaf preparation

## 1. Executive Summary

The project studies how alternative Contracts for Difference (CfDs) would have
performed for Italian onshore wind under the price and wind-resource
variability observed from 2015 to 2024.

The central policy question is:

> Can a support mechanism reduce the producer's annual revenue risk while also
> reducing the public counterparty's net cost relative to a conventional
> two-sided CfD?

The current analysis does not forecast future electricity prices. Future price
levels are highly uncertain and may change structurally as renewable
penetration increases. Instead, the project uses a homogeneous ten-year
historical backtest to compare contract designs under the same observed price
and weather variability. The results will therefore support claims about the
relative behaviour of incentive mechanisms, not point forecasts of future
prices or public expenditure.

The first empirical comparison covers:

1. market-only revenue;
2. a conventional two-sided CfD;
3. a Newbery-inspired Zonal Yardstick CfD;
4. a Schlecht-inspired Financial CfD.

An original hybrid mechanism, NPV/ROI analysis, and stochastic future scenarios
are outside the final scope. The paper remains a historical, descriptive
comparison of settlement design, producer-revenue risk, and public cash flows.

## 2. Intended Scientific Contribution

The contribution is not the invention of a new metric or an unnecessarily
complex forecasting model. It is the consistent application of mechanisms
proposed in the literature to an extensive Italian case study characterised
by:

- strong regional differences in wind availability;
- zonal electricity prices and a bidding-zone revision in 2021;
- covariance between local wind output and market prices;
- potential distributional differences in producer support and public cost;
- an hourly, regionally explicit empirical design covering ten years.

This setting is relevant to the distortion identified by Newbery: settling a
conventional CfD on the individual plant's metered production can affect
production incentives and expose the public counterparty directly to local
volume variation. Production-independent yardsticks and financial settlements
are tested as alternatives under actual Italian conditions.

The comparative performance of the literature mechanisms is policy-relevant in
itself. The final scope ends with this validated historical comparison and does
not assess a modified or hybrid design.

## 3. Current Analytical Design

### 3.1 Observation period and unit of analysis

- Period: 2015–2024.
- Resolution: hourly.
- Representative asset: one stylised 1 MW regional onshore-wind proxy asset.
- Market exposure: the historical GME price of the bidding zone containing the
  region in the relevant year.
- Monetary basis: real 2024 EUR.

The regional representative plant is a normalized analytical unit. Results are
reported per contracted MW and, separately, as a national counterfactual scaled
by observed installed capacity.

### 3.2 Price data

Hourly GME zonal prices are used for the full decade. The region-to-zone mapping
changes with the Italian market configuration:

- through 2020, Umbria belongs to Centro Nord and Calabria to Sud;
- from 2021, Umbria belongs to Centro Sud and Calabria is a separate zone.

Nominal prices are converted to real 2024 EUR/MWh using the Italian annual HICP.

### 3.3 Wind data

One homogeneous source is used for hourly wind-resource dynamics throughout the
decade: the Copernicus Climate Data Store global energy reanalysis, based on
ERA5, at ADM1/subnational level.

The global ADM1 exports contain 110 coded Italian provincial units. They are
mapped to the 20 regions with Natural Earth 5.1.1 and aggregated using geodesic
area weights. The normalized dataset contains exactly 8,767,200
timestamp-region-technology observations.

The source supplies hourly onshore wind capacity factors for five turbine and
wind-input specifications. For each specification, annual national MWh/MW are
constructed using Terna regional installed-capacity weights. One specification
is selected for the entire decade by the lowest mean absolute error against
Terna annual national gross wind production per MW.

Terna annual production is therefore a validation target, not an alternative
hourly profile. This avoids mixing different hourly wind sources before and
after 2019 or falling back to the 2024 zonal-production proxy.

### 3.4 Strike prices

Two uniform cost-based strikes are calculated from:

- CAPEX: 1,580,000 EUR/MW;
- OPEX: 35,000 EUR/MW-year;
- WACC: 6.5%;
- useful life: 20 years.

The annualized cost is divided by two empirical full-load-hour benchmarks:

- `K_P50`: median annual national full-load hours in 2015–2024;
- `K_P25`: lower-quartile annual national full-load hours in 2015–2024.

Using both strikes shows how conclusions change between a central production
assumption and a more conservative one without introducing many arbitrary
sensitivities.

### 3.5 Mechanisms

Let `P_h` be the real zonal price, `Q_h` the representative regional plant's
production per MW, `M_h` the capacity-weighted zonal wind benchmark, and `K`
the strike.

**Market-only**

```text
producer revenue = P_h * Q_h
```

**Conventional two-sided CfD**

```text
settlement = (K - P_h) * Q_h
producer revenue = K * Q_h
```

**Zonal Yardstick CfD**

```text
settlement = (K - P_h) * M_h
producer revenue = P_h * Q_h + settlement
```

The settlement depends on a zonal benchmark rather than the individual plant's
production. The analysis also estimates the years required to reach Newbery's
30,000 MWh/MW contract-volume limit.

**Financial CfD**

```text
producer revenue = P_h * Q_h + fixed payment - max(P_h, 0) * M_h
```

The fixed annual payment is the exact annualised cost,
`CAPEX * CRF + OPEX = 178,395.1047 EUR/MW-year`, under both strike scenarios.
Its settlement legs are independent of the individual proxy asset's production.

## 4. Evaluation Framework

The main analysis reports seven complementary metrics.

Producer perspective:

1. mean annual revenue per MW;
2. standard deviation of annual revenue per MW.
3. Sharpe Ratio with a zero risk-free rate;
4. annual market-only Value Factor.

Public-counterparty perspective:

5. gross top-up;
6. gross clawback;
7. net public cost, equal to top-up minus clawback.

The synthesis figure has producer revenue standard deviation on the horizontal
axis and net public cost on the vertical axis. Mean producer revenue is shown
in the labels. No arbitrary composite score is used.

A mechanism is described as dominant only if it reduces producer risk and
public cost without materially reducing mean producer revenue. Otherwise, the
result is presented as a trade-off rather than ranked through subjective
weights.

## 5. Geographic Analysis

The geographic output includes one 20-region capacity-factor heatmap, one
market-only 1x3 map, and six 1x3 CfD comparison figures for the two strike
scenarios. Regional borders are thin, zone borders are heavier, and common
metric-specific scales permit direct comparisons across mechanisms.

The fixed geography affects visualization only. Historical hourly prices,
benchmarks, Umbria, and Calabria retain the market configuration valid in each
year. Separate regional and 49-row zonal source tables make every colour
traceable.

## 6. Final Phase 2 Status at 21 July 2026

### Completed and validated

- Phase 2 is 100% complete; no further empirical extension is planned for this
  paper.
- Repository and Phase 1 preprocessing structure reorganized.
- Clean 2024 GME/Terna preprocessing baseline completed.
- 2024 region-to-zone mapping, including Calabria, audited.
- Historical GME price loader for 2015–2024 implemented and checked.
- Historical pre-/post-2021 region-to-zone mapping implemented.
- Real-2024 price conversion implemented.
- Official generalized ISTAT regional boundaries downloaded and the 20-region
  geographic join visually checked.
- Cost-based `K_P50` and `K_P25` calibration implemented.
- Market-only, conventional CfD, Zonal Yardstick, and Financial-CfD hourly
  settlement logic implemented.
- Natural Earth 5.1.1 provincial mapping, geodesic weights, and complete
  Copernicus normalization implemented and validated.
- Full hourly 2015–2024 backtest completed for all four mechanisms and both
  strikes.
- Copernicus `IC2.5HH100E` selected by the lowest national annual MWh/MW MAE
  against Terna; this resulting series is named the Reference Onshore Wind
  Profile (ROWP).
- Empirical strikes calculated: `K_P50 = 91.64` and `K_P25 = 98.68` real-2024
  EUR/MWh.
- Regional/national aggregation, Sharpe Ratio and Value Factor summaries, and
  the market-only 1x3 plus 1x3 CfD comparison figures generated for both
  `K_P50` and `K_P25`.
- Financial-CfD gross top-up and gross clawback are separately accounted before
  calculating net public cost.
- The Financial-CfD fixed leg is invariant across `K_P50` and `K_P25`.
- All 30 repository tests pass, including the accounting, normalization,
  mapping, output-contract, and NotebookLM-bundle tests.
- `compileall` passes for `src`, `scripts`, and `tests`.
- Phase 1 pipeline rerun successfully after clearing stale generated results.

### Generated local empirical outputs

- 20 auditable CSV tables under `results/historical_cfd_backtest_2015_2024/tables`.
- Eight paper figures: one market-only 1x3 figure, three primary `K_P50` CfD
  maps, three `K_P25` appendix maps, and the regional wind-resource map.
- Natural Earth, normalized Copernicus, and generated results remain local and
  ignored by Git under the repository data policy.

### Final scope boundaries

The validated descriptive backtest does not claim that one mechanism is
universally best. Its conclusions remain conditional on the observed
2015--2024 price and wind record, the stylised regional proxy assets, and the
implemented settlement rules. No future-price, welfare, dispatch, financing,
NPV, ROI, or long-run investment conclusion is made.

## 7. Immediate Next Steps

1. Complete the author-controlled Introduction and Literature review while
   preserving the validated research question and evidence boundaries.
2. Perform final British-English and editorial consistency checks.
3. Transfer the manuscript, bibliography, and eight economic/resource figures to
   Overleaf and inspect the complete layout.
4. Complete authorship, CRediT, funding, conflicts, acknowledgements, and data-
   archive metadata.
5. Archive the normalized results and submission materials.

## 8. Intended Claims and Boundaries

The current design can support statements about:

- relative producer-revenue stabilization across mechanisms;
- relative public top-up, clawback, and net cost under historical conditions;
- geographic heterogeneity within Italy;
- the effect of replacing plant-level settlement volume with a zonal yardstick;
- robustness to two transparent cost-based strike calibrations.

It cannot, by itself, establish:

- future Italian wholesale-price levels;
- future absolute government expenditure;
- causal investment responses;
- general superiority under every future market design;
- project bankability or financing outcomes.

## 9. Repository Guide

Use this document as the stable high-level research status. NotebookLM should
start from `docs/notebooklm_exchange/codex_to_notebooklm.md`, which identifies
the current cycle and exact upload bundle. Supporting material is divided as
follows:

- `README.md`: repository setup, inputs, commands, and generated-output paths;
- `docs/research/historical_cfd_backtest.md`: authoritative technical specification for
  the backtest, including the data contract, equations, outputs, and validation
  rules; these implementation details are deliberately not duplicated here;
- `docs/research/paper_structure.md`: short editorial outline for the Energy Policy
  manuscript; the actual manuscript text remains in `docs/latex/main.tex`;
- `docs/notebooklm_exchange/`: the current two-file Codex-NotebookLM exchange;
- `scripts/build_notebooklm_bundle.py`: deterministic conversion of the current
  exchange, selected source files, and validated result tables into an ignored
  Markdown-only upload folder for NotebookLM;
- `docs/literature/`: local literature corpus and the Zotero BibLaTeX master;
- `docs/latex/references.bib`: manuscript bibliography obtained by merging the
  NotebookLM/Zotero corpus with the official data and regulatory sources;
- `src/cfd_analysis/`: implemented economic and geographic logic;
- `tests/test_historical_cfd.py`: core accounting and mapping tests.

This document records the final Phase 2 research decisions and validation
status. Generated numerical results remain under the ignored `results/`
directory and are represented in the manuscript only after validation.
