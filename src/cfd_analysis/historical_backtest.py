"""Hourly 2015-2024 backtest of Italian wind CfD settlement mechanisms."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from market_preprocessing.config import RESULTS_DIR
from market_preprocessing.mapping import REGION_TO_ZONE

from .geography import (
    find_istat_region_shapefile,
    load_istat_region_geometries,
    plot_market_only_metrics,
    plot_regional_mechanism_comparison,
    plot_single_regional_map,
)
from .historical_inputs import (
    COPERNICUS_WIND_FILE,
    HISTORICAL_YEARS,
    inflation_audit_table,
    load_copernicus_hourly_wind,
    load_gme_hourly_prices,
    load_terna_annual_wind,
    map_region_to_zone_for_year,
    select_copernicus_technology,
)
from .mechanisms import (
    WindCostAssumptions,
    aggregate_annual_regions,
    aggregate_national_annual,
    build_annual_market_value_factor,
    build_decadal_market_value_factor,
    build_regional_value_factor_summary,
    build_metric_summary,
    build_regional_comparison_source,
    build_regional_distribution_summary,
    build_regional_metric_summary,
    build_zonal_heatmap_source,
    calculate_uniform_strikes,
    settle_hourly,
)


OUTPUT_ROOT = RESULTS_DIR / "historical_cfd_backtest_2015_2024"
TABLE_DIR = OUTPUT_ROOT / "tables"
FIGURE_DIR = OUTPUT_ROOT / "figures"


@dataclass(frozen=True)
class HistoricalBacktestOutputs:
    """Paths and key choices produced by the historical CfD backtest."""

    tables: tuple[Path, ...]
    figures: tuple[Path, ...]
    selected_copernicus_technology: str
    strikes_real_2024_eur_per_mwh: dict[str, float]


def run_historical_cfd_backtest(
    years: tuple[int, ...] = HISTORICAL_YEARS,
    copernicus_path: Path = COPERNICUS_WIND_FILE,
    istat_shapefile: Path | None = None,
    generate_maps: bool = True,
    assumptions: WindCostAssumptions = WindCostAssumptions(),
) -> HistoricalBacktestOutputs:
    """Run the complete historical market-only and CfD comparison."""

    wind = load_copernicus_hourly_wind(copernicus_path, years)
    terna = load_terna_annual_wind(years)
    prices = load_gme_hourly_prices(years)
    selected, technology_diagnostics, technology_annual = select_copernicus_technology(
        wind,
        terna,
    )
    wind_coverage_audit = _build_wind_coverage_audit(wind)
    selected_validation = technology_annual[
        technology_annual["technology"] == selected
    ].copy()
    strikes = calculate_uniform_strikes(
        selected_validation["copernicus_mwh_per_mw"],
        assumptions,
    )
    panel = _build_regional_hourly_panel(
        wind[wind["technology"] == selected].copy(),
        terna,
        prices,
        years,
    )

    annual_frames: list[pd.DataFrame] = []
    # Baseline is calculated and validated before the advanced mechanisms.
    market_hourly = settle_hourly(
        panel,
        mechanism="market_only",
        strike_real_2024_eur_per_mwh=None,
    )
    annual_frames.append(aggregate_annual_regions(market_hourly, "not_applicable"))
    del market_hourly

    for strike in strikes.itertuples(index=False):
        conventional = settle_hourly(
            panel,
            mechanism="conventional_cfd",
            strike_real_2024_eur_per_mwh=strike.strike_real_2024_eur_per_mwh,
        )
        annual_frames.append(aggregate_annual_regions(conventional, strike.strike_label))
        del conventional

    for strike in strikes.itertuples(index=False):
        for mechanism in ("zonal_yardstick_cfd", "schlecht_fcfd"):
            advanced = settle_hourly(
                panel,
                mechanism=mechanism,
                strike_real_2024_eur_per_mwh=strike.strike_real_2024_eur_per_mwh,
                annualized_cost_real_2024_eur_per_mw=(
                    strike.annualized_cost_real_2024_eur_per_mw
                    if mechanism == "schlecht_fcfd"
                    else None
                ),
            )
            annual_frames.append(aggregate_annual_regions(advanced, strike.strike_label))
            del advanced

    annual_region = pd.concat(annual_frames, ignore_index=True)
    annual_region = _attach_strikes(annual_region, strikes)
    national_annual = aggregate_national_annual(annual_region)
    metrics = build_metric_summary(national_annual)
    metrics = _attach_strikes(metrics, strikes)
    regional_metrics = build_regional_metric_summary(annual_region)
    regional_metrics = _attach_strikes(regional_metrics, strikes)
    annual_value_factor = build_annual_market_value_factor(panel)
    annual_value_factor["zone_2024"] = annual_value_factor["region"].map(REGION_TO_ZONE)
    decadal_value_factor = build_decadal_market_value_factor(annual_value_factor)
    regional_value_factor_summary = build_regional_value_factor_summary(
        annual_value_factor
    )
    regional_comparison = build_regional_comparison_source(regional_metrics)
    regional_comparison_k_p25 = build_regional_comparison_source(
        regional_metrics,
        strike_label="K_P25",
    )
    regional_distribution = build_regional_distribution_summary(regional_comparison)
    regional_resource = _build_regional_resource_source(panel)
    zonal_heatmap_source = build_zonal_heatmap_source(annual_region)
    yardstick_limit = _build_zonal_yardstick_limit_table(panel)
    price_sign_audit = _build_price_sign_audit(prices)

    tables = _write_tables(
        annual_region=annual_region,
        national_annual=national_annual,
        metrics=metrics,
        regional_metrics=regional_metrics,
        regional_comparison=regional_comparison,
        regional_distribution=regional_distribution,
        strikes=strikes,
        regional_resource=regional_resource,
        annual_value_factor=annual_value_factor,
        decadal_value_factor=decadal_value_factor,
        regional_value_factor_summary=regional_value_factor_summary,
        zonal_heatmap_source=zonal_heatmap_source,
        yardstick_limit=yardstick_limit,
        technology_diagnostics=technology_diagnostics,
        technology_annual=technology_annual,
        wind_coverage_audit=wind_coverage_audit,
        price_sign_audit=price_sign_audit,
        terna=terna,
        years=years,
    )
    figures: list[Path] = []
    if generate_maps:
        shp_path = istat_shapefile or find_istat_region_shapefile()
        figures.extend(
            _plot_regional_results(
                regional_comparison,
                regional_comparison_k_p25,
                regional_resource,
                decadal_value_factor,
                shp_path,
            )
        )
    return HistoricalBacktestOutputs(
        tables=tuple(tables),
        figures=tuple(figures),
        selected_copernicus_technology=selected,
        strikes_real_2024_eur_per_mwh={
            str(row.strike_label): float(row.strike_real_2024_eur_per_mwh)
            for row in strikes.itertuples(index=False)
        },
    )


def _build_regional_hourly_panel(
    selected_wind: pd.DataFrame,
    terna: pd.DataFrame,
    prices: pd.DataFrame,
    years: tuple[int, ...],
) -> pd.DataFrame:
    wind = selected_wind.rename(columns={"capacity_factor": "quantity_mwh_per_mw"})
    wind["year"] = wind["timestamp_utc"].dt.tz_convert("Europe/Rome").dt.year
    mapping = pd.DataFrame(
        [
            {
                "year": year,
                "region": region,
                "zone": map_region_to_zone_for_year(region, year),
            }
            for year in years
            for region in REGION_TO_ZONE
        ]
    )
    wind = wind.merge(mapping, on=["year", "region"], how="left", validate="many_to_one")
    wind = wind.merge(
        terna[["year", "region", "installed_capacity_mw"]],
        on=["year", "region"],
        how="left",
        validate="many_to_one",
    )
    if wind[["zone", "installed_capacity_mw"]].isna().any().any():
        raise ValueError("Incomplete historical region-zone or Terna capacity join")
    wind["weighted_quantity"] = (
        wind["quantity_mwh_per_mw"] * wind["installed_capacity_mw"]
    )
    benchmark = (
        wind.groupby(["year", "timestamp_utc", "zone"], as_index=False)
        .agg(
            weighted_quantity=("weighted_quantity", "sum"),
            zone_installed_capacity_mw=("installed_capacity_mw", "sum"),
        )
    )
    if (benchmark["zone_installed_capacity_mw"] <= 0).any():
        failed = benchmark.loc[
            benchmark["zone_installed_capacity_mw"] <= 0,
            ["year", "zone"],
        ].drop_duplicates()
        raise ValueError(f"Non-positive benchmark capacity: {failed.to_dict(orient='records')}")
    benchmark["benchmark_mwh_per_mw"] = (
        benchmark["weighted_quantity"] / benchmark["zone_installed_capacity_mw"]
    )
    wind = wind.merge(
        benchmark[["year", "timestamp_utc", "zone", "benchmark_mwh_per_mw"]],
        on=["year", "timestamp_utc", "zone"],
        how="left",
        validate="many_to_one",
    )
    panel = wind.merge(
        prices[
            [
                "year",
                "timestamp_utc",
                "zone",
                "price_real_2024_eur_per_mwh",
            ]
        ],
        on=["year", "timestamp_utc", "zone"],
        how="left",
        validate="many_to_one",
    )
    required = [
        "quantity_mwh_per_mw",
        "benchmark_mwh_per_mw",
        "price_real_2024_eur_per_mwh",
    ]
    if panel[required].isna().any().any():
        raise ValueError("Incomplete Copernicus-benchmark-GME hourly join")
    if not panel["benchmark_mwh_per_mw"].between(0, 1).all():
        raise ValueError("Zonal benchmark capacity factor outside [0, 1]")
    expected_rows = sum(len(pd.date_range(
        start=f"{year}-01-01", end=f"{year + 1}-01-01", inclusive="left", freq="h", tz="Europe/Rome"
    )) for year in years) * 20
    if len(panel) != expected_rows:
        raise ValueError(f"Unexpected regional hourly panel size: {len(panel)} != {expected_rows}")
    return panel[
        [
            "year",
            "timestamp_utc",
            "region",
            "zone",
            "installed_capacity_mw",
            "price_real_2024_eur_per_mwh",
            "quantity_mwh_per_mw",
            "benchmark_mwh_per_mw",
        ]
    ].sort_values(["year", "timestamp_utc", "region"]).reset_index(drop=True)


def _attach_strikes(frame: pd.DataFrame, strikes: pd.DataFrame) -> pd.DataFrame:
    strike_lookup = strikes[
        ["strike_label", "strike_real_2024_eur_per_mwh"]
    ]
    output = frame.drop(columns="strike_real_2024_eur_per_mwh", errors="ignore").merge(
        strike_lookup,
        on="strike_label",
        how="left",
        validate="many_to_one",
    )
    return output


def _build_regional_resource_source(panel: pd.DataFrame) -> pd.DataFrame:
    """Build the traceable 20-region source for the wind-resource map."""

    resource = (
        panel.groupby("region", as_index=False)
        .agg(mean_capacity_factor_2015_2024=("quantity_mwh_per_mw", "mean"))
    )
    resource["zone_2024"] = resource["region"].map(REGION_TO_ZONE)
    resource["zone_basis"] = "Fixed GME bidding-zone configuration valid in 2024"
    if len(resource) != 20 or resource.isna().any().any():
        raise ValueError(f"Incomplete regional resource map source: {len(resource)} != 20")
    return resource.sort_values("region").reset_index(drop=True)


def _build_zonal_yardstick_limit_table(panel: pd.DataFrame) -> pd.DataFrame:
    annual = (
        panel.groupby(["year", "region"], as_index=False)
        .agg(
            annual_benchmark_mwh_per_mw=("benchmark_mwh_per_mw", "sum"),
            annual_generation_mwh_per_mw=("quantity_mwh_per_mw", "sum"),
        )
    )
    output = (
        annual.groupby("region", as_index=False)
        .agg(
            mean_annual_benchmark_mwh_per_mw=("annual_benchmark_mwh_per_mw", "mean"),
            mean_annual_generation_mwh_per_mw=("annual_generation_mwh_per_mw", "mean"),
            observed_years=("year", "nunique"),
        )
    )
    output["zone_2024"] = output["region"].map(REGION_TO_ZONE)
    output["estimated_years_to_30000_mwh_per_mw"] = (
        30_000 / output["mean_annual_generation_mwh_per_mw"]
    )
    output["limit_mwh_per_mw"] = 30_000
    return output.sort_values(["zone_2024", "region"]).reset_index(drop=True)



def _build_wind_coverage_audit(wind: pd.DataFrame) -> pd.DataFrame:
    frame = wind.copy()
    frame["year"] = frame["timestamp_utc"].dt.tz_convert("Europe/Rome").dt.year
    return (
        frame.groupby(["technology", "region", "year"], as_index=False, observed=True)
        .agg(
            observed_hours=("timestamp_utc", "nunique"),
            first_timestamp_utc=("timestamp_utc", "min"),
            last_timestamp_utc=("timestamp_utc", "max"),
            minimum_capacity_factor=("capacity_factor", "min"),
            maximum_capacity_factor=("capacity_factor", "max"),
            mean_capacity_factor=("capacity_factor", "mean"),
        )
        .sort_values(["technology", "region", "year"])
        .reset_index(drop=True)
    )


def _build_price_sign_audit(prices: pd.DataFrame) -> pd.DataFrame:
    """Summarize negative and zero GME observations used by Schlecht restitution."""

    return (
        prices.groupby("year", as_index=False)
        .agg(
            observed_zone_hours=("price_nominal_eur_per_mwh", "size"),
            minimum_nominal_eur_per_mwh=("price_nominal_eur_per_mwh", "min"),
            maximum_nominal_eur_per_mwh=("price_nominal_eur_per_mwh", "max"),
            negative_price_observations=(
                "price_nominal_eur_per_mwh",
                lambda values: int((values < 0).sum()),
            ),
            zero_price_observations=(
                "price_nominal_eur_per_mwh",
                lambda values: int((values == 0).sum()),
            ),
        )
        .sort_values("year")
        .reset_index(drop=True)
    )


def _write_tables(
    *,
    annual_region: pd.DataFrame,
    national_annual: pd.DataFrame,
    metrics: pd.DataFrame,
    regional_metrics: pd.DataFrame,
    regional_comparison: pd.DataFrame,
    regional_distribution: pd.DataFrame,
    strikes: pd.DataFrame,
    regional_resource: pd.DataFrame,
    annual_value_factor: pd.DataFrame,
    decadal_value_factor: pd.DataFrame,
    regional_value_factor_summary: pd.DataFrame,
    zonal_heatmap_source: pd.DataFrame,
    yardstick_limit: pd.DataFrame,
    technology_diagnostics: pd.DataFrame,
    technology_annual: pd.DataFrame,
    wind_coverage_audit: pd.DataFrame,
    price_sign_audit: pd.DataFrame,
    terna: pd.DataFrame,
    years: tuple[int, ...],
) -> list[Path]:
    TABLE_DIR.mkdir(parents=True, exist_ok=True)
    validation = technology_annual.merge(
        technology_diagnostics[
            ["technology", "selected_national_technology"]
        ],
        on="technology",
        how="left",
    )
    tables = {
        "annual_region_mechanism_results.csv": annual_region,
        "annual_national_mechanism_results.csv": national_annual,
        "five_metric_summary.csv": metrics,
        "regional_five_metric_summary.csv": regional_metrics,
        "regional_comparison_map_source.csv": _format_map_source_for_export(
            regional_comparison
        ),
        "regional_metric_distribution_summary.csv": regional_distribution,
        "uniform_strike_calibration.csv": strikes,
        "regional_capacity_factor_map_source.csv": regional_resource,
        "annual_market_only_value_factor.csv": annual_value_factor,
        "market_only_value_factor_10_year_mean.csv": decadal_value_factor,
        "regional_value_factor_summary.csv": regional_value_factor_summary,
        "zonal_heatmap_source.csv": zonal_heatmap_source,
        "zonal_yardstick_30000_mwh_limit.csv": yardstick_limit,
        "copernicus_technology_selection.csv": technology_diagnostics,
        "copernicus_terna_annual_validation.csv": validation,
        "copernicus_hourly_coverage_audit.csv": wind_coverage_audit,
        "gme_price_sign_audit.csv": price_sign_audit,
        "historical_region_zone_mapping.csv": _mapping_audit_table(years),
        "terna_annual_capacity_production_audit.csv": terna,
        "inflation_real_2024_audit.csv": inflation_audit_table(years),
    }
    paths: list[Path] = []
    for filename, frame in tables.items():
        path = TABLE_DIR / filename
        frame.to_csv(path, index=False)
        paths.append(path)
    return paths


def _format_map_source_for_export(source: pd.DataFrame) -> pd.DataFrame:
    """Format infinite Sharpe values as LaTeX-safe strings for CSV export."""

    output = source.copy()
    column = "producer_sharpe_ratio"
    values = pd.to_numeric(output[column], errors="raise")
    formatted = values.astype(object)
    formatted.loc[values.eq(float("inf"))] = r"+\infty"
    formatted.loc[values.eq(float("-inf"))] = r"-\infty"
    output[column] = formatted
    return output


def _mapping_audit_table(years: tuple[int, ...]) -> pd.DataFrame:
    source_url = (
        "https://www.terna.it/en/electric-system/publications/operators-news/"
        "detail/Suddivisione-in-zone-di-mercato-della-Rete-di-Trasmissione-"
        "Nazionale-valida-a-partire-dal-1%C2%B0-gennaio-2021"
    )
    return pd.DataFrame(
        [
            {
                "year": year,
                "region": region,
                "zone": map_region_to_zone_for_year(region, year),
                "configuration": "pre-2021" if year < 2021 else "from-2021",
                "source": (
                    "Terna zonal revision implementing ARERA 103/2019/R/eel; "
                    "Umbria and Calabria changes effective 2021"
                ),
                "source_url": source_url,
            }
            for year in years
            for region in REGION_TO_ZONE
        ]
    )


def _plot_regional_results(
    regional_comparison: pd.DataFrame,
    regional_comparison_k_p25: pd.DataFrame,
    regional_resource: pd.DataFrame,
    decadal_value_factor: pd.DataFrame,
    shp_path: Path,
) -> list[Path]:
    """Generate market-only, CfD comparison, and resource figures."""

    geometries = load_istat_region_geometries(shp_path)
    market_only = regional_comparison[
        regional_comparison["mechanism"] == "market_only"
    ].copy()
    cfd_p50 = regional_comparison[
        regional_comparison["mechanism"] != "market_only"
    ].copy()
    cfd_p25 = regional_comparison_k_p25[
        regional_comparison_k_p25["mechanism"] != "market_only"
    ].copy()
    cfd_scale = pd.concat([cfd_p50, cfd_p25], ignore_index=True)

    paths: list[Path] = []
    market_map_path = FIGURE_DIR / "italy_market_only_maps.png"
    plot_market_only_metrics(
        geometries,
        market_only,
        decadal_value_factor,
        market_map_path,
    )
    paths.append(market_map_path)
    stale_value_factor_path = FIGURE_DIR / "italy_value_factor_trend.png"
    if stale_value_factor_path.exists():
        stale_value_factor_path.unlink()

    specifications = (
        (
            "producer_mean_annual_revenue_real_2024_eur_per_mw",
            "viridis",
            "Mean annual producer revenue [kEUR/MW-year, real 2024]",
            "cfd_comparison_mean_revenue_k_p50.png",
            False,
            cfd_p50,
        ),
        (
            "producer_sharpe_ratio",
            "plasma",
            "Sharpe Ratio [mean annual revenue / annual SD]",
            "cfd_comparison_sharpe_ratio_k_p50.png",
            False,
            cfd_p50,
        ),
        (
            "mean_annual_net_public_cost_real_2024_eur_per_mw",
            "RdBu_r",
            "Mean annual net public cost [kEUR/MW-year, real 2024]",
            "cfd_comparison_net_public_cost_k_p50.png",
            True,
            cfd_p50,
        ),
        (
            "producer_mean_annual_revenue_real_2024_eur_per_mw",
            "viridis",
            "Mean annual producer revenue [kEUR/MW-year, real 2024]",
            "cfd_comparison_mean_revenue_k_p25.png",
            False,
            cfd_p25,
        ),
        (
            "producer_sharpe_ratio",
            "plasma",
            "Sharpe Ratio [mean annual revenue / annual SD]",
            "cfd_comparison_sharpe_ratio_k_p25.png",
            False,
            cfd_p25,
        ),
        (
            "mean_annual_net_public_cost_real_2024_eur_per_mw",
            "RdBu_r",
            "Mean annual net public cost [kEUR/MW-year, real 2024]",
            "cfd_comparison_net_public_cost_k_p25.png",
            True,
            cfd_p25,
        ),
    )
    for value_column, colour_map, label, filename, centre_on_zero, source in specifications:
        path = FIGURE_DIR / filename
        plot_regional_mechanism_comparison(
            geometries,
            source,
            value_column,
            colour_map,
            label,
            path,
            centre_on_zero=centre_on_zero,
            scale_source=cfd_scale,
        )
        paths.append(path)

    resource_path = FIGURE_DIR / "italy_regional_wind_capacity_factor.png"
    plot_single_regional_map(
        geometries,
        regional_resource,
        "mean_capacity_factor_2015_2024",
        "YlGnBu",
        "Mean annual onshore wind capacity factor [2015–2024]",
        resource_path,
    )
    paths.append(resource_path)
    return paths
