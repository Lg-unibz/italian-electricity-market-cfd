"""Hourly 2015-2024 backtest of Italian wind CfD settlement mechanisms."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from market_preprocessing.config import RESULTS_DIR
from market_preprocessing.mapping import REGION_TO_ZONE

from .geography import (
    find_istat_region_shapefile,
    load_istat_region_geometries,
    plot_benchmark_concentration_risk_compression,
    plot_market_only_metrics,
    plot_centro_sud_benchmark_self_influence,
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
CENTRO_SUD_REGIONS = ("Campania", "Abruzzo", "Lazio", "Umbria")


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
    regional_proxy_validation_annual = _build_regional_proxy_validation_annual(panel, terna)
    regional_proxy_validation = _build_regional_proxy_validation_summary(
        regional_proxy_validation_annual
    )
    if len(regional_proxy_validation_annual) != 200:
        raise ValueError("Historical regional validation must contain 200 region-year rows")
    zonal_heatmap_source = build_zonal_heatmap_source(annual_region)
    yardstick_limit = _build_zonal_yardstick_limit_table(panel)
    price_sign_audit = _build_price_sign_audit(prices)
    p50 = strikes.loc[strikes["strike_label"] == "K_P50"].iloc[0]
    centro_sud_annual = _build_centro_sud_leave_one_out_annual(
        panel,
        annualized_cost_real_2024_eur_per_mw=float(
            p50.annualized_cost_real_2024_eur_per_mw
        ),
        yardstick_strike_real_2024_eur_per_mwh=float(
            p50.strike_real_2024_eur_per_mwh
        ),
    )
    centro_sud_summary = _build_centro_sud_leave_one_out_summary(centro_sud_annual)
    zonal_concentration_annual = _build_zonal_concentration_annual(
        panel,
        annualized_cost_real_2024_eur_per_mw=float(
            p50.annualized_cost_real_2024_eur_per_mw
        ),
        yardstick_strike_real_2024_eur_per_mwh=float(
            p50.strike_real_2024_eur_per_mwh
        ),
    )
    zonal_concentration_summary = _build_zonal_concentration_summary(
        zonal_concentration_annual
    )
    if len(zonal_concentration_annual) != 352 or len(zonal_concentration_summary) != 36:
        raise ValueError("Unexpected historical multi-zone concentration output coverage")
    zonal_public_settlement_annual = _build_zonal_public_settlement_annual(
        annual_region,
        national_annual,
    )
    zonal_public_settlement_summary = _build_zonal_public_settlement_summary(
        zonal_public_settlement_annual
    )

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
        centro_sud_annual=centro_sud_annual,
        centro_sud_summary=centro_sud_summary,
        regional_proxy_validation_annual=regional_proxy_validation_annual,
        regional_proxy_validation=regional_proxy_validation,
        zonal_concentration_annual=zonal_concentration_annual,
        zonal_concentration_summary=zonal_concentration_summary,
        zonal_public_settlement_annual=zonal_public_settlement_annual,
        zonal_public_settlement_summary=zonal_public_settlement_summary,
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
                centro_sud_summary,
                zonal_concentration_summary,
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
        benchmark[[
            "year", "timestamp_utc", "zone", "benchmark_mwh_per_mw",
            "zone_installed_capacity_mw",
        ]],
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
            "zone_installed_capacity_mw",
            "price_real_2024_eur_per_mwh",
            "quantity_mwh_per_mw",
            "benchmark_mwh_per_mw",
        ]
    ].sort_values(["year", "timestamp_utc", "region"]).reset_index(drop=True)


def _add_leave_one_out_benchmark(panel: pd.DataFrame) -> pd.DataFrame:
    """Attach the own-weight and leave-one-out reference to an hourly panel."""

    required = {
        "installed_capacity_mw", "zone_installed_capacity_mw",
        "quantity_mwh_per_mw", "benchmark_mwh_per_mw",
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"Missing leave-one-out benchmark columns: {missing}")
    output = panel.copy()
    output["own_capacity_share"] = (
        output["installed_capacity_mw"] / output["zone_installed_capacity_mw"]
    )
    other_capacity = (
        output["zone_installed_capacity_mw"] - output["installed_capacity_mw"]
    )
    output["leave_one_out_defined"] = other_capacity.gt(0)
    output["leave_one_out_benchmark_mwh_per_mw"] = np.nan
    defined = output["leave_one_out_defined"]
    output.loc[defined, "leave_one_out_benchmark_mwh_per_mw"] = (
        (
            output.loc[defined, "zone_installed_capacity_mw"]
            * output.loc[defined, "benchmark_mwh_per_mw"]
            - output.loc[defined, "installed_capacity_mw"]
            * output.loc[defined, "quantity_mwh_per_mw"]
        )
        / other_capacity.loc[defined]
    )
    loo_values = output.loc[defined, "leave_one_out_benchmark_mwh_per_mw"]
    if not loo_values.between(-1e-8, 1 + 1e-8).all():
        raise ValueError("Leave-one-out benchmark capacity factor outside [0, 1]")
    output["leave_one_out_benchmark_mwh_per_mw"] = output[
        "leave_one_out_benchmark_mwh_per_mw"
    ].clip(lower=0.0, upper=1.0)
    identity_error = (
        output.loc[defined, "quantity_mwh_per_mw"]
        - output.loc[defined, "benchmark_mwh_per_mw"]
        - (1 - output.loc[defined, "own_capacity_share"])
        * (
            output.loc[defined, "quantity_mwh_per_mw"]
            - output.loc[defined, "leave_one_out_benchmark_mwh_per_mw"]
        )
    )
    if not np.allclose(identity_error, 0.0, atol=1e-12):
        raise ValueError("Leave-one-out attenuation identity failed")
    return output


def _build_centro_sud_leave_one_out_annual(
    panel: pd.DataFrame,
    *,
    annualized_cost_real_2024_eur_per_mw: float,
    yardstick_strike_real_2024_eur_per_mwh: float,
) -> pd.DataFrame:
    """Build the diagnostic-only annual Centro Sud leave-one-out panel."""

    source = _add_leave_one_out_benchmark(panel)
    source = source.loc[
        source["zone"].eq("Centro Sud") & source["region"].isin(CENTRO_SUD_REGIONS)
    ].copy()
    if len(source.groupby(["region", "year"])) != 34:
        raise ValueError("Centro Sud diagnostic must contain exactly 34 region-year rows")
    if not source["leave_one_out_defined"].all():
        raise ValueError("Centro Sud leave-one-out benchmark unexpectedly undefined")
    hours_per_year = source.groupby("year")["timestamp_utc"].transform("nunique")
    price = source["price_real_2024_eur_per_mwh"]
    quantity = source["quantity_mwh_per_mw"]
    benchmark = source["benchmark_mwh_per_mw"]
    loo = source["leave_one_out_benchmark_mwh_per_mw"]
    source["inclusive_basis_revenue_real_2024_eur_per_mw"] = price * (quantity - benchmark)
    source["leave_one_out_basis_revenue_real_2024_eur_per_mw"] = price * (quantity - loo)
    source["financial_inclusive_revenue_real_2024_eur_per_mw"] = (
        price * quantity + annualized_cost_real_2024_eur_per_mw / hours_per_year
        - price.clip(lower=0) * benchmark
    )
    source["financial_leave_one_out_revenue_real_2024_eur_per_mw"] = (
        price * quantity + annualized_cost_real_2024_eur_per_mw / hours_per_year
        - price.clip(lower=0) * loo
    )
    source["yardstick_k_p50_inclusive_revenue_real_2024_eur_per_mw"] = (
        price * quantity + (yardstick_strike_real_2024_eur_per_mwh - price) * benchmark
    )
    source["yardstick_k_p50_leave_one_out_revenue_real_2024_eur_per_mw"] = (
        price * quantity + (yardstick_strike_real_2024_eur_per_mwh - price) * loo
    )
    annual = source.groupby(["region", "year"], as_index=False).agg(
        zone=("zone", "first"),
        observed_hours=("timestamp_utc", "size"),
        installed_capacity_mw=("installed_capacity_mw", "first"),
        zone_installed_capacity_mw=("zone_installed_capacity_mw", "first"),
        own_capacity_share=("own_capacity_share", "first"),
        plant_generation_mwh_per_mw=("quantity_mwh_per_mw", "sum"),
        inclusive_benchmark_generation_mwh_per_mw=("benchmark_mwh_per_mw", "sum"),
        leave_one_out_benchmark_generation_mwh_per_mw=("leave_one_out_benchmark_mwh_per_mw", "sum"),
        inclusive_basis_revenue_real_2024_eur_per_mw=("inclusive_basis_revenue_real_2024_eur_per_mw", "sum"),
        leave_one_out_basis_revenue_real_2024_eur_per_mw=("leave_one_out_basis_revenue_real_2024_eur_per_mw", "sum"),
        financial_inclusive_revenue_real_2024_eur_per_mw=("financial_inclusive_revenue_real_2024_eur_per_mw", "sum"),
        financial_leave_one_out_revenue_real_2024_eur_per_mw=("financial_leave_one_out_revenue_real_2024_eur_per_mw", "sum"),
        yardstick_k_p50_inclusive_revenue_real_2024_eur_per_mw=("yardstick_k_p50_inclusive_revenue_real_2024_eur_per_mw", "sum"),
        yardstick_k_p50_leave_one_out_revenue_real_2024_eur_per_mw=("yardstick_k_p50_leave_one_out_revenue_real_2024_eur_per_mw", "sum"),
    )
    return annual.sort_values(["region", "year"]).reset_index(drop=True)


def _build_centro_sud_leave_one_out_summary(annual: pd.DataFrame) -> pd.DataFrame:
    """Summarise diagnostic annual revenue without public-flow aggregation."""

    mechanisms = (
        ("Financial CfD", "not_applicable", "financial_inclusive_revenue_real_2024_eur_per_mw", "financial_leave_one_out_revenue_real_2024_eur_per_mw"),
        ("Zonal Yardstick CfD", "K_P50", "yardstick_k_p50_inclusive_revenue_real_2024_eur_per_mw", "yardstick_k_p50_leave_one_out_revenue_real_2024_eur_per_mw"),
    )
    rows: list[dict[str, float | int | str]] = []
    for mechanism, strike_label, inclusive, leave_one_out in mechanisms:
        for region, frame in annual.groupby("region", sort=False):
            current = frame[inclusive]
            loo = frame[leave_one_out]
            rows.append({
                "region": region, "mechanism": mechanism, "strike_label": strike_label,
                "eligible_years": int(frame["year"].nunique()),
                "first_year": int(frame["year"].min()), "last_year": int(frame["year"].max()),
                "mean_own_capacity_share": frame["own_capacity_share"].mean(),
                "min_own_capacity_share": frame["own_capacity_share"].min(),
                "max_own_capacity_share": frame["own_capacity_share"].max(),
                "inclusive_mean_annual_revenue_real_2024_eur_per_mw": current.mean(),
                "leave_one_out_mean_annual_revenue_real_2024_eur_per_mw": loo.mean(),
                "inclusive_std_annual_revenue_real_2024_eur_per_mw": current.std(ddof=1),
                "leave_one_out_std_annual_revenue_real_2024_eur_per_mw": loo.std(ddof=1),
                "inclusive_sharpe_ratio": _annual_revenue_sharpe(current),
                "leave_one_out_sharpe_ratio": _annual_revenue_sharpe(loo),
            })
    output = pd.DataFrame(rows)
    if len(output) != 8:
        raise ValueError("Centro Sud diagnostic must contain exactly eight summary rows")
    return output.sort_values(["mechanism", "region"]).reset_index(drop=True)


def _build_regional_proxy_validation_annual(
    panel: pd.DataFrame,
    terna: pd.DataFrame,
) -> pd.DataFrame:
    """Compare annual selected-profile FLH with observed Terna regional FLH."""

    modelled = (
        panel.groupby(["year", "region", "zone"], as_index=False)
        .agg(modelled_mwh_per_mw=("quantity_mwh_per_mw", "sum"))
    )
    output = modelled.merge(
        terna[
            [
                "year",
                "region",
                "installed_capacity_mw",
                "observed_generation_mwh",
                "observed_mwh_per_mw",
            ]
        ],
        on=["year", "region"],
        how="left",
        validate="one_to_one",
    )
    if output["observed_mwh_per_mw"].isna().any():
        raise ValueError("Regional proxy validation requires complete observed FLH")
    output["error_mwh_per_mw"] = (
        output["modelled_mwh_per_mw"] - output["observed_mwh_per_mw"]
    )
    output["absolute_error_mwh_per_mw"] = output["error_mwh_per_mw"].abs()
    output["squared_error_mwh_per_mw_squared"] = output["error_mwh_per_mw"] ** 2
    output["observed_production_positive"] = output["observed_generation_mwh"].gt(0)
    output["capacity_gte_10_mw"] = output["installed_capacity_mw"].ge(10)
    output["is_micro_fleet_lt_10_mw"] = output["installed_capacity_mw"].lt(10)
    return output.sort_values(["year", "region"]).reset_index(drop=True)


def _validation_metrics(frame: pd.DataFrame) -> dict[str, float | int]:
    """Return transparent level and association diagnostics for annual FLH."""

    modelled = pd.to_numeric(frame["modelled_mwh_per_mw"], errors="raise")
    observed = pd.to_numeric(frame["observed_mwh_per_mw"], errors="raise")
    error = modelled - observed
    correlations_defined = len(frame) >= 2 and modelled.nunique() > 1 and observed.nunique() > 1
    return {
        "eligible_region_years": int(len(frame)),
        "first_year": int(frame["year"].min()),
        "last_year": int(frame["year"].max()),
        "mae_mwh_per_mw": float(error.abs().mean()),
        "mean_bias_mwh_per_mw": float(error.mean()),
        "rmse_mwh_per_mw": float(np.sqrt((error**2).mean())),
        "pearson_r": float(modelled.corr(observed)) if correlations_defined else float("nan"),
        "spearman_rho": (
            float(modelled.rank(method="average").corr(observed.rank(method="average")))
            if correlations_defined
            else float("nan")
        ),
    }


def _capacity_weighted_validation_aggregate(
    frame: pd.DataFrame,
    group_columns: list[str],
) -> pd.DataFrame:
    """Aggregate modelled and observed FLH with observed capacity weights."""

    weighted = frame.copy()
    weighted["modelled_generation_mwh"] = (
        weighted["modelled_mwh_per_mw"] * weighted["installed_capacity_mw"]
    )
    grouped = weighted.groupby(group_columns, as_index=False).agg(
        installed_capacity_mw=("installed_capacity_mw", "sum"),
        modelled_generation_mwh=("modelled_generation_mwh", "sum"),
        observed_generation_mwh=("observed_generation_mwh", "sum"),
    )
    grouped["modelled_mwh_per_mw"] = (
        grouped["modelled_generation_mwh"] / grouped["installed_capacity_mw"]
    )
    grouped["observed_mwh_per_mw"] = (
        grouped["observed_generation_mwh"] / grouped["installed_capacity_mw"]
    )
    return grouped


def _build_regional_proxy_validation_summary(annual: pd.DataFrame) -> pd.DataFrame:
    """Summarise regional, historical-zonal, national, and pooled validation."""

    populations = (
        ("all_observed_capacity", annual.index.to_series().notna()),
        ("positive_observed_production", annual["observed_production_positive"]),
        (
            "positive_observed_production_and_capacity_gte_10_mw",
            annual["observed_production_positive"] & annual["capacity_gte_10_mw"],
        ),
    )
    rows: list[dict[str, object]] = []
    for population, mask in populations:
        source = annual.loc[mask].copy()
        for region, frame in source.groupby("region", sort=True):
            rows.append(
                {
                    "geographic_level": "region",
                    "geographic_unit": region,
                    "analysis_population": population,
                    **_validation_metrics(frame),
                }
            )
        zonal = _capacity_weighted_validation_aggregate(source, ["year", "zone"])
        for zone, frame in zonal.groupby("zone", sort=True):
            rows.append(
                {
                    "geographic_level": "historical_zone",
                    "geographic_unit": zone,
                    "analysis_population": population,
                    **_validation_metrics(frame),
                }
            )
        national = _capacity_weighted_validation_aggregate(source, ["year"])
        rows.append(
            {
                "geographic_level": "national",
                "geographic_unit": "Italy",
                "analysis_population": population,
                **_validation_metrics(national),
            }
        )
        rows.append(
            {
                "geographic_level": "pooled_region_year",
                "geographic_unit": "Italy",
                "analysis_population": population,
                **_validation_metrics(source),
            }
        )
    return pd.DataFrame(rows).sort_values(
        ["geographic_level", "geographic_unit", "analysis_population"]
    ).reset_index(drop=True)


def _build_zonal_concentration_annual(
    panel: pd.DataFrame,
    *,
    annualized_cost_real_2024_eur_per_mw: float,
    yardstick_strike_real_2024_eur_per_mwh: float,
) -> pd.DataFrame:
    """Calculate general historical-zone inclusive and leave-one-out revenue."""

    source = _add_leave_one_out_benchmark(panel)
    weights = source[["year", "zone", "region", "own_capacity_share"]].drop_duplicates()
    hhi = weights.groupby(["year", "zone"], as_index=False).agg(
        zonal_hhi=("own_capacity_share", lambda values: float((values**2).sum()))
    )
    source = source.merge(hhi, on=["year", "zone"], how="left", validate="many_to_one")
    source = source.loc[source["leave_one_out_defined"]].copy()
    hours_per_year = source.groupby("year")["timestamp_utc"].transform("nunique")
    price = source["price_real_2024_eur_per_mwh"]
    quantity = source["quantity_mwh_per_mw"]
    benchmark = source["benchmark_mwh_per_mw"]
    leave_one_out = source["leave_one_out_benchmark_mwh_per_mw"]
    source["financial_inclusive"] = (
        price * quantity + annualized_cost_real_2024_eur_per_mw / hours_per_year
        - price.clip(lower=0) * benchmark
    )
    source["financial_leave_one_out"] = (
        price * quantity + annualized_cost_real_2024_eur_per_mw / hours_per_year
        - price.clip(lower=0) * leave_one_out
    )
    source["yardstick_inclusive"] = (
        price * quantity + (yardstick_strike_real_2024_eur_per_mwh - price) * benchmark
    )
    source["yardstick_leave_one_out"] = (
        price * quantity + (yardstick_strike_real_2024_eur_per_mwh - price) * leave_one_out
    )
    annual = source.groupby(["year", "region", "zone"], as_index=False).agg(
        installed_capacity_mw=("installed_capacity_mw", "first"),
        zone_installed_capacity_mw=("zone_installed_capacity_mw", "first"),
        own_capacity_share=("own_capacity_share", "first"),
        zonal_hhi=("zonal_hhi", "first"),
        inclusive_benchmark_generation_mwh_per_mw=("benchmark_mwh_per_mw", "sum"),
        leave_one_out_benchmark_generation_mwh_per_mw=("leave_one_out_benchmark_mwh_per_mw", "sum"),
        financial_inclusive=("financial_inclusive", "sum"),
        financial_leave_one_out=("financial_leave_one_out", "sum"),
        yardstick_inclusive=("yardstick_inclusive", "sum"),
        yardstick_leave_one_out=("yardstick_leave_one_out", "sum"),
    )
    frames: list[pd.DataFrame] = []
    for mechanism, strike_label, inclusive, leave_one_out_column in (
        ("schlecht_fcfd", "not_applicable", "financial_inclusive", "financial_leave_one_out"),
        ("zonal_yardstick_cfd", "K_P50", "yardstick_inclusive", "yardstick_leave_one_out"),
    ):
        output = annual.drop(columns=[
            "financial_inclusive", "financial_leave_one_out", "yardstick_inclusive", "yardstick_leave_one_out"
        ]).copy()
        output["mechanism"] = mechanism
        output["strike_label"] = strike_label
        output["inclusive_meaningful_revenue_real_2024_eur_per_mw"] = annual[inclusive]
        output["leave_one_out_revenue_real_2024_eur_per_mw"] = annual[leave_one_out_column]
        output["leave_one_out_defined"] = True
        frames.append(output)
    result = pd.concat(frames, ignore_index=True)
    return result.sort_values(["mechanism", "year", "region"]).reset_index(drop=True)


def _build_zonal_concentration_summary(annual: pd.DataFrame) -> pd.DataFrame:
    """Summarise concentration and risk compression without causal inference."""

    rows: list[dict[str, object]] = []
    for (region, mechanism, strike_label), frame in annual.groupby(
        ["region", "mechanism", "strike_label"], sort=True
    ):
        inclusive = frame["inclusive_meaningful_revenue_real_2024_eur_per_mw"]
        leave_one_out = frame["leave_one_out_revenue_real_2024_eur_per_mw"]
        leave_one_out_sd = float(leave_one_out.std(ddof=1))
        zones = sorted(frame["zone"].unique())
        rows.append(
            {
                "region": region,
                "historical_zone": " / ".join(zones),
                "mechanism": mechanism,
                "strike_label": strike_label,
                "eligible_years": int(frame["year"].nunique()),
                "first_year": int(frame["year"].min()),
                "last_year": int(frame["year"].max()),
                "mean_own_capacity_share": float(frame["own_capacity_share"].mean()),
                "min_own_capacity_share": float(frame["own_capacity_share"].min()),
                "max_own_capacity_share": float(frame["own_capacity_share"].max()),
                "mean_zonal_hhi": float(frame["zonal_hhi"].mean()),
                "inclusive_mean_annual_revenue_real_2024_eur_per_mw": float(inclusive.mean()),
                "leave_one_out_mean_annual_revenue_real_2024_eur_per_mw": float(leave_one_out.mean()),
                "inclusive_std_annual_revenue_real_2024_eur_per_mw": float(inclusive.std(ddof=1)),
                "leave_one_out_std_annual_revenue_real_2024_eur_per_mw": leave_one_out_sd,
                "inclusive_to_leave_one_out_sd_ratio": (
                    float(inclusive.std(ddof=1) / leave_one_out_sd)
                    if leave_one_out_sd > 0
                    else float("nan")
                ),
            }
        )
    output = pd.DataFrame(rows)
    return output.sort_values(["mechanism", "region"]).reset_index(drop=True)


def _normalise_financial_presentation(frame: pd.DataFrame) -> pd.DataFrame:
    """Collapse identical Financial-CfD strike duplicates for presentation only."""

    financial = frame.loc[frame["mechanism"].eq("schlecht_fcfd")].copy()
    non_financial = frame.loc[~frame["mechanism"].eq("schlecht_fcfd")].copy()
    comparison_columns = [
        column for column in financial.columns
        if column not in {"strike_label", "strike_real_2024_eur_per_mwh"}
    ]
    grouped = financial.groupby(comparison_columns, dropna=False)["strike_label"].nunique()
    if not grouped.eq(2).all():
        raise ValueError("Financial CfD strike rows are not identical presentation duplicates")
    financial = financial.loc[financial["strike_label"].eq("K_P50")].copy()
    financial["strike_label"] = "not_applicable"
    if "strike_real_2024_eur_per_mwh" in financial:
        financial["strike_real_2024_eur_per_mwh"] = np.nan
    return pd.concat([non_financial, financial], ignore_index=True)


def _build_zonal_public_settlement_annual(
    annual_region: pd.DataFrame,
    national_annual: pd.DataFrame,
) -> pd.DataFrame:
    """Build historical-zone and national public settlement views."""

    metrics = (
        "top_up_real_2024_eur_per_mw",
        "clawback_real_2024_eur_per_mw",
        "net_public_cost_real_2024_eur_per_mw",
    )
    source = _normalise_financial_presentation(annual_region)
    source = source.loc[source["mechanism"].ne("market_only")].copy()
    advanced = source["mechanism"].isin(["zonal_yardstick_cfd", "schlecht_fcfd"])
    for _, frame in source.loc[advanced].groupby(["year", "zone", "mechanism", "strike_label"]):
        if any(float(frame[column].max() - frame[column].min()) > 1e-8 for column in metrics):
            raise ValueError("Advanced public settlement must be equal within a zone-year")
    for metric in metrics:
        source[f"{metric}_capacity_scaled_total"] = source[metric] * source["installed_capacity_mw"]
    total_columns = [f"{metric}_capacity_scaled_total" for metric in metrics]
    zones = source.groupby(["year", "zone", "mechanism", "strike_label"], as_index=False).agg(
        observed_installed_capacity_mw=("installed_capacity_mw", "sum"),
        **{column: (column, "sum") for column in total_columns},
    )
    for metric, total in zip(metrics, total_columns, strict=True):
        zones[metric] = zones[total] / zones["observed_installed_capacity_mw"]
    zones["geographic_level"] = "historical_zone"
    zones["settlement_granularity"] = np.where(
        zones["mechanism"].eq("conventional_cfd"),
        "regional_proxy_capacity_weighted",
        "zonal_per_contracted_proxy_mw",
    )
    national = _normalise_financial_presentation(national_annual)
    national = national.loc[national["mechanism"].ne("market_only")].copy()
    national = national.rename(columns={
        "installed_capacity_mw": "observed_installed_capacity_mw",
        "top_up_real_2024_eur_national_total": "top_up_real_2024_eur_per_mw_capacity_scaled_total",
        "clawback_real_2024_eur_national_total": "clawback_real_2024_eur_per_mw_capacity_scaled_total",
        "net_public_cost_real_2024_eur_national_total": "net_public_cost_real_2024_eur_per_mw_capacity_scaled_total",
    })
    for metric in metrics:
        national[f"{metric}_capacity_scaled_total"] = national.pop(
            f"{metric}_capacity_scaled_total"
        )
    national = national[[
        "year", "mechanism", "strike_label", "observed_installed_capacity_mw", *metrics, *total_columns
    ]].copy()
    national["zone"] = "Italy"
    national["geographic_level"] = "national"
    national["settlement_granularity"] = "national_capacity_scaled_counterfactual"
    columns = [
        "year", "geographic_level", "zone", "mechanism", "strike_label",
        "observed_installed_capacity_mw", "settlement_granularity", *metrics, *total_columns,
    ]
    return pd.concat([zones[columns], national[columns]], ignore_index=True).sort_values(
        ["geographic_level", "mechanism", "strike_label", "year", "zone"]
    ).reset_index(drop=True)


def _build_zonal_public_settlement_summary(annual: pd.DataFrame) -> pd.DataFrame:
    """Provide full-sample, median, and crisis-exclusion public-flow summaries."""

    metrics = (
        "top_up_real_2024_eur_per_mw",
        "clawback_real_2024_eur_per_mw",
        "net_public_cost_real_2024_eur_per_mw",
    )
    rules = (
        ("full_sample_annual_mean", lambda frame: frame),
        ("full_sample_annual_median", lambda frame: frame),
        ("excluding_2021_2022_annual_mean", lambda frame: frame.loc[~frame["year"].isin([2021, 2022])]),
    )
    rows: list[dict[str, object]] = []
    for keys, frame in annual.groupby(
        ["geographic_level", "zone", "mechanism", "strike_label", "settlement_granularity"],
        sort=True,
    ):
        for label, selector in rules:
            selected = selector(frame)
            reducer = "median" if label == "full_sample_annual_median" else "mean"
            rows.append({
                "geographic_level": keys[0], "zone": keys[1], "mechanism": keys[2],
                "strike_label": keys[3], "settlement_granularity": keys[4],
                "summary_statistic": label, "observed_years": int(selected["year"].nunique()),
                **{metric: float(getattr(selected[metric], reducer)()) for metric in metrics},
            })
    return pd.DataFrame(rows).sort_values(
        ["geographic_level", "mechanism", "strike_label", "summary_statistic", "zone"]
    ).reset_index(drop=True)


def _annual_revenue_sharpe(revenue: pd.Series) -> float:
    """Return the zero-risk-free annual revenue ratio without divide warnings."""

    mean = float(revenue.mean())
    standard_deviation = float(revenue.std(ddof=1))
    if standard_deviation == 0:
        return float("inf") if mean > 0 else float("nan")
    return mean / standard_deviation


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
    centro_sud_annual: pd.DataFrame,
    centro_sud_summary: pd.DataFrame,
    regional_proxy_validation_annual: pd.DataFrame,
    regional_proxy_validation: pd.DataFrame,
    zonal_concentration_annual: pd.DataFrame,
    zonal_concentration_summary: pd.DataFrame,
    zonal_public_settlement_annual: pd.DataFrame,
    zonal_public_settlement_summary: pd.DataFrame,
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
        "centro_sud_leave_one_out_annual.csv": centro_sud_annual,
        "centro_sud_leave_one_out_summary.csv": centro_sud_summary,
        "regional_proxy_validation_annual.csv": regional_proxy_validation_annual,
        "regional_proxy_validation.csv": regional_proxy_validation,
        "zonal_concentration_annual.csv": zonal_concentration_annual,
        "zonal_concentration_summary.csv": zonal_concentration_summary,
        "zonal_public_settlement_annual.csv": zonal_public_settlement_annual,
        "zonal_public_settlement_summary.csv": zonal_public_settlement_summary,
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
    centro_sud_summary: pd.DataFrame,
    zonal_concentration_summary: pd.DataFrame,
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
            "linear",
            cfd_p50,
        ),
        (
            "producer_std_annual_revenue_real_2024_eur_per_mw",
            "magma",
            "Annual revenue SD [kEUR/MW-year, real 2024]",
            "cfd_comparison_revenue_sd_k_p50.png",
            False,
            "linear",
            cfd_p50,
        ),
        (
            "mean_annual_net_public_cost_real_2024_eur_per_mw",
            "RdBu_r",
            "Mean annual net public cost [kEUR/MW-year, real 2024]",
            "cfd_comparison_net_public_cost_k_p50.png",
            True,
            "symlog",
            cfd_p50,
        ),
        (
            "producer_mean_annual_revenue_real_2024_eur_per_mw",
            "viridis",
            "Mean annual producer revenue [kEUR/MW-year, real 2024]",
            "cfd_comparison_mean_revenue_k_p25.png",
            False,
            "linear",
            cfd_p25,
        ),
        (
            "producer_std_annual_revenue_real_2024_eur_per_mw",
            "magma",
            "Annual revenue SD [kEUR/MW-year, real 2024]",
            "cfd_comparison_revenue_sd_k_p25.png",
            False,
            "linear",
            cfd_p25,
        ),
        (
            "mean_annual_net_public_cost_real_2024_eur_per_mw",
            "RdBu_r",
            "Mean annual net public cost [kEUR/MW-year, real 2024]",
            "cfd_comparison_net_public_cost_k_p25.png",
            True,
            "symlog",
            cfd_p25,
        ),
    )
    for (
        value_column,
        colour_map,
        label,
        filename,
        centre_on_zero,
        colour_scale,
        source,
    ) in specifications:
        path = FIGURE_DIR / filename
        plot_regional_mechanism_comparison(
            geometries,
            source,
            value_column,
            colour_map,
            label,
            path,
            centre_on_zero=centre_on_zero,
            colour_scale=colour_scale,
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
    diagnostic_path = FIGURE_DIR / "centro_sud_benchmark_self_influence.png"
    plot_centro_sud_benchmark_self_influence(
        geometries,
        centro_sud_summary,
        diagnostic_path,
    )
    paths.append(diagnostic_path)
    concentration_path = FIGURE_DIR / "benchmark_concentration_risk_compression.png"
    plot_benchmark_concentration_risk_compression(
        zonal_concentration_summary,
        concentration_path,
    )
    paths.append(concentration_path)
    return paths
