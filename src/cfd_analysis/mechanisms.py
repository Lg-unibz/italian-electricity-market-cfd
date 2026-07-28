"""Pure strike-price and CfD settlement calculations."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from market_preprocessing.mapping import REGION_TO_ZONE


MECHANISM_ORDER = (
    "market_only",
    "conventional_cfd",
    "zonal_yardstick_cfd",
    "schlecht_fcfd",
)


@dataclass(frozen=True)
class WindCostAssumptions:
    """Real-2024 cost assumptions for a representative 1 MW wind plant."""

    capex_eur_per_mw: float = 1_580_000.0
    opex_eur_per_mw_year: float = 35_000.0
    wacc: float = 0.065
    useful_life_years: int = 20


def capital_recovery_factor(wacc: float, useful_life_years: int) -> float:
    """Return the standard annuity capital-recovery factor."""

    if wacc <= -1 or useful_life_years <= 0:
        raise ValueError("WACC must exceed -1 and useful life must be positive")
    if wacc == 0:
        return 1 / useful_life_years
    growth = (1 + wacc) ** useful_life_years
    return wacc * growth / (growth - 1)


def calculate_uniform_strikes(
    annual_national_flh: pd.Series,
    assumptions: WindCostAssumptions = WindCostAssumptions(),
) -> pd.DataFrame:
    """Calculate uniform P50 and lower-quartile P25 strike prices."""

    values = pd.to_numeric(annual_national_flh, errors="raise").dropna()
    if values.empty or (values <= 0).any():
        raise ValueError("Annual national full-load hours must be positive")
    flh = {
        "K_P50": float(values.quantile(0.50, interpolation="linear")),
        "K_P25": float(values.quantile(0.25, interpolation="linear")),
    }
    crf = capital_recovery_factor(assumptions.wacc, assumptions.useful_life_years)
    annualized_cost = (
        assumptions.capex_eur_per_mw * crf + assumptions.opex_eur_per_mw_year
    )
    rows = []
    for label in ("K_P50", "K_P25"):
        rows.append(
            {
                "strike_label": label,
                "strike_real_2024_eur_per_mwh": annualized_cost / flh[label],
                "reference_flh_mwh_per_mw": flh[label],
                "flh_p50_mwh_per_mw": flh["K_P50"],
                "capital_recovery_factor": crf,
                "annualized_cost_real_2024_eur_per_mw": annualized_cost,
                "capex_real_2024_eur_per_mw": assumptions.capex_eur_per_mw,
                "opex_real_2024_eur_per_mw_year": assumptions.opex_eur_per_mw_year,
                "wacc": assumptions.wacc,
                "useful_life_years": assumptions.useful_life_years,
                "cost_source": (
                    "ARERA Resolution 239/2025/R/efr supporting documentation, "
                    "onshore wind plant close to 1 MW"
                ),
                "cost_source_url": (
                    "https://www.arera.it/fileadmin/allegati/docs/25/"
                    "239-2025-R-efr.pdf"
                ),
            }
        )
    return pd.DataFrame(rows)


def calculate_sharpe_ratio(
    mean_annual_revenue: pd.Series,
    std_annual_revenue: pd.Series,
    risk_free_rate_real_2024_eur_per_mw_year: float = 0.0,
) -> pd.Series:
    """Calculate annual-revenue Sharpe ratios with a zero-risk baseline.

    The standard deviation is expected to be the sample standard deviation of
    annual observations. A positive return with zero variance is represented as
    positive infinity; a zero excess return with zero variance is undefined.
    """

    mean = pd.to_numeric(mean_annual_revenue, errors="raise")
    standard_deviation = pd.to_numeric(std_annual_revenue, errors="raise")
    if len(mean) != len(standard_deviation):
        raise ValueError("Mean and standard-deviation series must have equal length")
    if (standard_deviation < 0).any():
        raise ValueError("Revenue standard deviation cannot be negative")

    excess_return = mean - float(risk_free_rate_real_2024_eur_per_mw_year)
    ratio = excess_return / standard_deviation.replace(0, np.nan)
    zero_variance = standard_deviation.eq(0)
    ratio = ratio.mask(zero_variance & excess_return.gt(0), np.inf)
    ratio = ratio.mask(zero_variance & excess_return.lt(0), -np.inf)
    return ratio.mask(zero_variance & excess_return.eq(0), np.nan)


def build_annual_market_value_factor(panel: pd.DataFrame) -> pd.DataFrame:
    """Build annual regional market-only value factors.

    The numerator is the production-weighted regional price and the denominator
    is the arithmetic hourly price average of the historically valid zone.
    """

    required = {
        "year",
        "timestamp_utc",
        "region",
        "zone",
        "price_real_2024_eur_per_mwh",
        "quantity_mwh_per_mw",
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"Missing Value Factor columns: {missing}")

    frame = panel.copy()
    frame["price_real_2024_eur_per_mwh"] = pd.to_numeric(
        frame["price_real_2024_eur_per_mwh"], errors="raise"
    )
    frame["quantity_mwh_per_mw"] = pd.to_numeric(
        frame["quantity_mwh_per_mw"], errors="raise"
    )
    regional = (
        frame.assign(
            weighted_market_revenue_real_2024_eur_per_mw=(
                frame["price_real_2024_eur_per_mwh"]
                * frame["quantity_mwh_per_mw"]
            )
        )
        .groupby(["year", "region", "zone"], as_index=False)
        .agg(
            regional_generation_mwh_per_mw=("quantity_mwh_per_mw", "sum"),
            weighted_market_revenue_real_2024_eur_per_mw=(
                "weighted_market_revenue_real_2024_eur_per_mw",
                "sum",
            ),
        )
    )
    regional["wind_weighted_price_real_2024_eur_per_mwh"] = (
        regional["weighted_market_revenue_real_2024_eur_per_mw"]
        / regional["regional_generation_mwh_per_mw"]
    )

    zone_prices = frame[
        ["year", "timestamp_utc", "zone", "price_real_2024_eur_per_mwh"]
    ].drop_duplicates(["year", "timestamp_utc", "zone"])
    base_price = (
        zone_prices.groupby(["year", "zone"], as_index=False)
        .agg(
            base_price_real_2024_eur_per_mwh=(
                "price_real_2024_eur_per_mwh",
                "mean",
            ),
            observed_hours=("timestamp_utc", "nunique"),
        )
    )
    output = regional.merge(
        base_price,
        on=["year", "zone"],
        how="left",
        validate="many_to_one",
    )
    if (output["regional_generation_mwh_per_mw"] <= 0).any():
        raise ValueError("Value Factor requires positive annual regional generation")
    if output["base_price_real_2024_eur_per_mwh"].eq(0).any():
        raise ValueError("Value Factor is undefined for a zero annual base price")
    output["value_factor"] = (
        output["wind_weighted_price_real_2024_eur_per_mwh"]
        / output["base_price_real_2024_eur_per_mwh"]
    )
    columns = [
        "year",
        "region",
        "zone",
        "regional_generation_mwh_per_mw",
        "wind_weighted_price_real_2024_eur_per_mwh",
        "base_price_real_2024_eur_per_mwh",
        "value_factor",
        "observed_hours",
    ]
    output = output[columns].sort_values(["year", "region"]).reset_index(drop=True)
    expected_rows = output["year"].nunique() * len(REGION_TO_ZONE)
    if len(output) != expected_rows:
        raise ValueError(f"Value Factor must contain {expected_rows} rows")
    return output


def build_decadal_market_value_factor(
    annual_value_factor: pd.DataFrame,
) -> pd.DataFrame:
    """Calculate the ten-year regional mean market-only Value Factor."""

    required = {"year", "region", "value_factor"}
    missing = sorted(required - set(annual_value_factor.columns))
    if missing:
        raise ValueError(f"Missing decadal Value Factor columns: {missing}")

    frame = annual_value_factor[["year", "region", "value_factor"]].copy()
    frame["year"] = pd.to_numeric(frame["year"], errors="raise").astype(int)
    frame["value_factor"] = pd.to_numeric(frame["value_factor"], errors="raise")
    expected_years = set(range(2015, 2025))
    observed_years = set(frame["year"])
    if observed_years != expected_years:
        raise ValueError(
            "Decadal Value Factor must contain exactly the years 2015-2024"
        )
    if set(frame["region"]) != set(REGION_TO_ZONE):
        raise ValueError("Decadal Value Factor must contain all 20 regions")
    if frame.duplicated(["year", "region"]).any():
        raise ValueError("Decadal Value Factor has duplicate region-year rows")
    expected_rows = len(expected_years) * len(REGION_TO_ZONE)
    if len(frame) != expected_rows:
        raise ValueError(f"Decadal Value Factor must contain {expected_rows} rows")

    output = (
        frame.groupby("region", as_index=False)
        .agg(
            ten_year_mean_value_factor=("value_factor", "mean"),
            observed_years=("year", "nunique"),
        )
        .assign(zone_2024=lambda values: values["region"].map(REGION_TO_ZONE))
    )
    if not output["observed_years"].eq(10).all():
        raise ValueError("Each region must have ten annual Value Factor values")
    return output[
        ["region", "zone_2024", "ten_year_mean_value_factor", "observed_years"]
    ].sort_values("region").reset_index(drop=True)


def build_regional_value_factor_summary(
    annual_value_factor: pd.DataFrame,
) -> pd.DataFrame:
    """Summarise annual market-only Value Factors by region.

    The standard deviation is the sample standard deviation across the ten
    annual observations, matching the risk-summary convention used elsewhere
    in the historical backtest.
    """

    required = {"year", "region", "value_factor"}
    missing = sorted(required - set(annual_value_factor.columns))
    if missing:
        raise ValueError(f"Missing Value Factor summary columns: {missing}")

    frame = annual_value_factor[["year", "region", "value_factor"]].copy()
    frame["year"] = pd.to_numeric(frame["year"], errors="raise").astype(int)
    frame["value_factor"] = pd.to_numeric(frame["value_factor"], errors="raise")
    expected_years = set(range(2015, 2025))
    if set(frame["year"]) != expected_years:
        raise ValueError(
            "Value Factor summary must contain exactly the years 2015-2024"
        )
    if set(frame["region"]) != set(REGION_TO_ZONE):
        raise ValueError("Value Factor summary must contain all 20 regions")
    if frame.duplicated(["year", "region"]).any():
        raise ValueError("Value Factor summary has duplicate region-year rows")
    if len(frame) != len(expected_years) * len(REGION_TO_ZONE):
        raise ValueError("Value Factor summary must contain 200 rows")

    summary = (
        frame.groupby("region", as_index=False)
        .agg(
            Mean_VF=("value_factor", "mean"),
            Std_Dev_VF=("value_factor", "std"),
            Min_VF=("value_factor", "min"),
            Max_VF=("value_factor", "max"),
        )
        .rename(columns={"region": "Region"})
        .sort_values("Region")
        .reset_index(drop=True)
    )
    if len(summary) != len(REGION_TO_ZONE):
        raise ValueError("Value Factor summary must contain 20 regions")
    return summary[["Region", "Mean_VF", "Std_Dev_VF", "Min_VF", "Max_VF"]]


def settle_hourly(
    panel: pd.DataFrame,
    mechanism: str,
    strike_real_2024_eur_per_mwh: float | None,
    annualized_cost_real_2024_eur_per_mw: float | None = None,
) -> pd.DataFrame:
    """Settle one mechanism on a regional hourly panel for a 1 MW plant.

    Required panel units are real-2024 EUR/MWh for ``price`` and MWh/MW-hour
    for regional production ``quantity`` and zonal yardstick ``benchmark``.
    """

    required = {
        "year",
        "timestamp_utc",
        "region",
        "zone",
        "installed_capacity_mw",
        "price_real_2024_eur_per_mwh",
        "quantity_mwh_per_mw",
        "benchmark_mwh_per_mw",
    }
    missing = sorted(required - set(panel.columns))
    if missing:
        raise ValueError(f"Missing settlement-panel columns: {missing}")
    if mechanism not in MECHANISM_ORDER:
        raise ValueError(f"Unknown CfD mechanism: {mechanism}")
    if mechanism != "market_only" and strike_real_2024_eur_per_mwh is None:
        raise ValueError(f"Strike price required for {mechanism}")
    if mechanism == "schlecht_fcfd" and (
        annualized_cost_real_2024_eur_per_mw is None
        or annualized_cost_real_2024_eur_per_mw <= 0
    ):
        raise ValueError(
            "Positive annualized cost required for the Financial CfD fixed payment"
        )

    output = panel.copy()
    price = output["price_real_2024_eur_per_mwh"].to_numpy(dtype=float)
    quantity = output["quantity_mwh_per_mw"].to_numpy(dtype=float)
    benchmark = output["benchmark_mwh_per_mw"].to_numpy(dtype=float)
    market_revenue = price * quantity

    if mechanism == "market_only":
        settlement = np.zeros(len(output), dtype=float)
        fixed_payment = np.zeros(len(output), dtype=float)
        top_up = np.zeros(len(output), dtype=float)
        clawback = np.zeros(len(output), dtype=float)
    elif mechanism == "conventional_cfd":
        strike = float(strike_real_2024_eur_per_mwh)
        settlement = (strike - price) * quantity
        fixed_payment = np.zeros(len(output), dtype=float)
        top_up = np.maximum(settlement, 0.0)
        clawback = np.maximum(-settlement, 0.0)
    elif mechanism == "zonal_yardstick_cfd":
        strike = float(strike_real_2024_eur_per_mwh)
        settlement = (strike - price) * benchmark
        fixed_payment = np.zeros(len(output), dtype=float)
        top_up = np.maximum(settlement, 0.0)
        clawback = np.maximum(-settlement, 0.0)
    else:
        hours_by_year = output.groupby("year")["timestamp_utc"].transform("nunique")
        fixed_payment = (
            float(annualized_cost_real_2024_eur_per_mw) / hours_by_year
        ).to_numpy(dtype=float)
        top_up = fixed_payment
        clawback = np.maximum(price, 0.0) * benchmark
        settlement = top_up - clawback

    output["mechanism"] = mechanism
    output["strike_real_2024_eur_per_mwh"] = strike_real_2024_eur_per_mwh
    output["market_revenue_real_2024_eur_per_mw"] = market_revenue
    output["fixed_payment_real_2024_eur_per_mw"] = fixed_payment
    output["settlement_real_2024_eur_per_mw"] = settlement
    output["producer_revenue_real_2024_eur_per_mw"] = market_revenue + settlement
    output["top_up_real_2024_eur_per_mw"] = top_up
    output["clawback_real_2024_eur_per_mw"] = clawback
    output["net_public_cost_real_2024_eur_per_mw"] = settlement
    validate_hourly_accounting(output, mechanism, strike_real_2024_eur_per_mwh)
    return output


def aggregate_annual_regions(hourly: pd.DataFrame, strike_label: str) -> pd.DataFrame:
    """Aggregate hourly settlement rows to region-year observations."""

    annual = (
        hourly.groupby(["year", "region", "zone", "mechanism"], as_index=False)
        .agg(
            installed_capacity_mw=("installed_capacity_mw", "first"),
            plant_generation_mwh_per_mw=("quantity_mwh_per_mw", "sum"),
            benchmark_generation_mwh_per_mw=("benchmark_mwh_per_mw", "sum"),
            market_revenue_real_2024_eur_per_mw=(
                "market_revenue_real_2024_eur_per_mw",
                "sum",
            ),
            settlement_real_2024_eur_per_mw=(
                "settlement_real_2024_eur_per_mw",
                "sum",
            ),
            producer_revenue_real_2024_eur_per_mw=(
                "producer_revenue_real_2024_eur_per_mw",
                "sum",
            ),
            top_up_real_2024_eur_per_mw=("top_up_real_2024_eur_per_mw", "sum"),
            clawback_real_2024_eur_per_mw=("clawback_real_2024_eur_per_mw", "sum"),
            net_public_cost_real_2024_eur_per_mw=(
                "net_public_cost_real_2024_eur_per_mw",
                "sum",
            ),
            observed_hours=("timestamp_utc", "nunique"),
        )
    )
    annual["strike_label"] = strike_label
    validate_annual_accounting(annual)
    return annual


def aggregate_national_annual(annual_region: pd.DataFrame) -> pd.DataFrame:
    """Capacity-scale regional results into counterfactual national totals."""

    frame = annual_region.copy()
    flow_columns = [
        "market_revenue_real_2024_eur_per_mw",
        "settlement_real_2024_eur_per_mw",
        "producer_revenue_real_2024_eur_per_mw",
        "top_up_real_2024_eur_per_mw",
        "clawback_real_2024_eur_per_mw",
        "net_public_cost_real_2024_eur_per_mw",
    ]
    for column in flow_columns:
        frame[column.replace("_per_mw", "_national_total")] = (
            frame[column] * frame["installed_capacity_mw"]
        )
    frame["generation_national_total_mwh"] = (
        frame["plant_generation_mwh_per_mw"] * frame["installed_capacity_mw"]
    )
    total_columns = [column for column in frame if column.endswith("_national_total")]
    national = (
        frame.groupby(["year", "mechanism", "strike_label"], as_index=False)
        .agg(
            installed_capacity_mw=("installed_capacity_mw", "sum"),
            **{column: (column, "sum") for column in total_columns},
        )
    )
    for total_column in total_columns:
        per_mw_column = total_column.replace("_national_total", "_per_mw")
        national[per_mw_column] = (
            national[total_column] / national["installed_capacity_mw"]
        )
    validate_annual_accounting(national)
    return national


def build_metric_summary(national_annual: pd.DataFrame) -> pd.DataFrame:
    """Build five metrics for the capacity-weighted national portfolio."""

    summary = (
        national_annual.groupby(["mechanism", "strike_label"], as_index=False)
        .agg(
            producer_mean_annual_revenue_real_2024_eur_per_mw=(
                "producer_revenue_real_2024_eur_per_mw",
                "mean",
            ),
            producer_std_annual_revenue_real_2024_eur_per_mw=(
                "producer_revenue_real_2024_eur_per_mw",
                "std",
            ),
            mean_annual_top_up_real_2024_eur_per_mw=(
                "top_up_real_2024_eur_per_mw",
                "mean",
            ),
            mean_annual_clawback_real_2024_eur_per_mw=(
                "clawback_real_2024_eur_per_mw",
                "mean",
            ),
            mean_annual_net_public_cost_real_2024_eur_per_mw=(
                "net_public_cost_real_2024_eur_per_mw",
                "mean",
            ),
        )
    )
    summary["producer_sharpe_ratio"] = calculate_sharpe_ratio(
        summary["producer_mean_annual_revenue_real_2024_eur_per_mw"],
        summary["producer_std_annual_revenue_real_2024_eur_per_mw"],
    )
    return summary


def build_regional_metric_summary(annual_region: pd.DataFrame) -> pd.DataFrame:
    """Build the five metrics before aggregating representative regional plants."""

    required = {
        "year",
        "region",
        "mechanism",
        "strike_label",
        "producer_revenue_real_2024_eur_per_mw",
        "top_up_real_2024_eur_per_mw",
        "clawback_real_2024_eur_per_mw",
        "net_public_cost_real_2024_eur_per_mw",
    }
    missing = sorted(required - set(annual_region.columns))
    if missing:
        raise ValueError(f"Missing annual regional columns: {missing}")

    annual_counts = annual_region.groupby(
        ["region", "mechanism", "strike_label"],
        observed=True,
    )["year"].nunique()
    expected_years = annual_region["year"].nunique()
    if not annual_counts.eq(expected_years).all():
        raise ValueError("Regional metric summary has incomplete annual coverage")

    summary = (
        annual_region.groupby(
            ["region", "mechanism", "strike_label"],
            as_index=False,
            observed=True,
        )
        .agg(
            producer_mean_annual_revenue_real_2024_eur_per_mw=(
                "producer_revenue_real_2024_eur_per_mw",
                "mean",
            ),
            producer_std_annual_revenue_real_2024_eur_per_mw=(
                "producer_revenue_real_2024_eur_per_mw",
                "std",
            ),
            mean_annual_top_up_real_2024_eur_per_mw=(
                "top_up_real_2024_eur_per_mw",
                "mean",
            ),
            mean_annual_clawback_real_2024_eur_per_mw=(
                "clawback_real_2024_eur_per_mw",
                "mean",
            ),
            mean_annual_net_public_cost_real_2024_eur_per_mw=(
                "net_public_cost_real_2024_eur_per_mw",
                "mean",
            ),
        )
    )
    summary["producer_sharpe_ratio"] = calculate_sharpe_ratio(
        summary["producer_mean_annual_revenue_real_2024_eur_per_mw"],
        summary["producer_std_annual_revenue_real_2024_eur_per_mw"],
    )
    summary.insert(1, "zone_2024", summary["region"].map(REGION_TO_ZONE))
    expected_rows = len(REGION_TO_ZONE) * annual_region[
        ["mechanism", "strike_label"]
    ].drop_duplicates().shape[0]
    if len(summary) != expected_rows:
        raise ValueError(
            f"Incomplete regional metric summary: {len(summary)} != {expected_rows}"
        )
    if summary["zone_2024"].isna().any():
        raise ValueError("Regional metric summary has incomplete 2024-zone mapping")
    identity_error = (
        summary["mean_annual_top_up_real_2024_eur_per_mw"]
        - summary["mean_annual_clawback_real_2024_eur_per_mw"]
        - summary["mean_annual_net_public_cost_real_2024_eur_per_mw"]
    ).abs().max()
    if identity_error > 1e-5:
        raise ValueError("Regional public-cost identity failed")
    return summary.sort_values(
        ["mechanism", "strike_label", "region"]
    ).reset_index(drop=True)


def build_regional_comparison_source(
    regional_metrics: pd.DataFrame,
    strike_label: str = "K_P50",
) -> pd.DataFrame:
    """Select one complete 20-region comparison across all four mechanisms."""

    metric_columns = [
        "producer_mean_annual_revenue_real_2024_eur_per_mw",
        "producer_std_annual_revenue_real_2024_eur_per_mw",
        "producer_sharpe_ratio",
        "mean_annual_net_public_cost_real_2024_eur_per_mw",
    ]
    required = {
        "region",
        "zone_2024",
        "mechanism",
        "strike_label",
        *metric_columns,
    }
    missing = sorted(required - set(regional_metrics.columns))
    if missing:
        raise ValueError(f"Missing regional comparison columns: {missing}")

    selected = regional_metrics[
        (
            (regional_metrics["mechanism"] == "market_only")
            & (regional_metrics["strike_label"] == "not_applicable")
        )
        | (
            (regional_metrics["mechanism"] != "market_only")
            & (regional_metrics["strike_label"] == strike_label)
        )
    ][
        ["region", "zone_2024", "mechanism", "strike_label", *metric_columns]
    ].copy()
    selected = selected.rename(columns={"zone_2024": "current_zone"})

    expected_regions = set(REGION_TO_ZONE)
    for mechanism in MECHANISM_ORDER:
        mechanism_rows = selected[selected["mechanism"] == mechanism]
        if (
            len(mechanism_rows) != len(expected_regions)
            or mechanism_rows["region"].duplicated().any()
            or set(mechanism_rows["region"]) != expected_regions
        ):
            raise ValueError(
                f"Regional comparison requires 20 unique regions for {mechanism}"
            )
    if len(selected) != len(expected_regions) * len(MECHANISM_ORDER):
        raise ValueError("Regional comparison must contain exactly 80 rows")
    if selected[metric_columns].isna().any().any():
        raise ValueError("Regional comparison contains missing metric values")

    mechanism_order = {mechanism: index for index, mechanism in enumerate(MECHANISM_ORDER)}
    selected["mechanism_order"] = selected["mechanism"].map(mechanism_order)
    return (
        selected.sort_values(["mechanism_order", "region"])
        .drop(columns="mechanism_order")
        .reset_index(drop=True)
    )


def build_regional_distribution_summary(
    regional_comparison: pd.DataFrame,
) -> pd.DataFrame:
    """Summarize each mapped metric across the 20 unweighted regions."""

    metric_columns = {
        "Mean annual producer revenue": (
            "producer_mean_annual_revenue_real_2024_eur_per_mw"
        ),
        "Annual producer revenue SD": (
            "producer_std_annual_revenue_real_2024_eur_per_mw"
        ),
        "Mean annual net public cost": (
            "mean_annual_net_public_cost_real_2024_eur_per_mw"
        ),
    }
    required = {"region", "mechanism", *metric_columns.values()}
    missing = sorted(required - set(regional_comparison.columns))
    if missing:
        raise ValueError(f"Missing regional distribution columns: {missing}")

    rows: list[dict[str, object]] = []
    for metric, column in metric_columns.items():
        for mechanism in MECHANISM_ORDER:
            values = pd.to_numeric(
                regional_comparison.loc[
                    regional_comparison["mechanism"] == mechanism,
                    column,
                ],
                errors="raise",
            )
            if len(values) != len(REGION_TO_ZONE):
                raise ValueError(
                    f"Distribution summary requires 20 regions for {mechanism}/{metric}"
                )
            rows.append(
                {
                    "metric": metric,
                    "mechanism": mechanism,
                    "regional_mean_real_2024_eur_per_mw_year": float(values.mean()),
                    "regional_std_real_2024_eur_per_mw_year": float(values.std()),
                    "regional_p25_real_2024_eur_per_mw_year": float(
                        values.quantile(0.25, interpolation="linear")
                    ),
                    "regional_median_real_2024_eur_per_mw_year": float(
                        values.quantile(0.50, interpolation="linear")
                    ),
                    "regional_p75_real_2024_eur_per_mw_year": float(
                        values.quantile(0.75, interpolation="linear")
                    ),
                    "regional_min_real_2024_eur_per_mw_year": float(values.min()),
                    "regional_max_real_2024_eur_per_mw_year": float(values.max()),
                }
            )
    return pd.DataFrame(rows)


def build_zonal_heatmap_source(annual_region: pd.DataFrame) -> pd.DataFrame:
    """Build five capacity-weighted metrics on a fixed 2024 zone geography."""

    required = {
        "year",
        "region",
        "mechanism",
        "strike_label",
        "installed_capacity_mw",
        "producer_revenue_real_2024_eur_per_mw",
        "top_up_real_2024_eur_per_mw",
        "clawback_real_2024_eur_per_mw",
        "net_public_cost_real_2024_eur_per_mw",
    }
    missing = sorted(required - set(annual_region.columns))
    if missing:
        raise ValueError(f"Missing annual regional columns for zonal heatmaps: {missing}")
    frame = annual_region.copy()
    frame["zone_2024"] = frame["region"].map(REGION_TO_ZONE)
    if frame["zone_2024"].isna().any():
        raise ValueError("Incomplete fixed-2024 zone mapping for heatmaps")
    metrics = (
        "producer_revenue_real_2024_eur_per_mw",
        "top_up_real_2024_eur_per_mw",
        "clawback_real_2024_eur_per_mw",
        "net_public_cost_real_2024_eur_per_mw",
    )
    total_columns: list[str] = []
    for metric in metrics:
        total_column = metric.replace("_per_mw", "_capacity_weighted_total")
        frame[total_column] = frame[metric] * frame["installed_capacity_mw"]
        total_columns.append(total_column)
    annual_zone = (
        frame.groupby(
            ["year", "zone_2024", "mechanism", "strike_label"],
            as_index=False,
        )
        .agg(
            installed_capacity_mw=("installed_capacity_mw", "sum"),
            **{column: (column, "sum") for column in total_columns},
        )
    )
    for metric, total_column in zip(metrics, total_columns, strict=True):
        annual_zone[metric] = (
            annual_zone[total_column] / annual_zone["installed_capacity_mw"]
        )
    source = (
        annual_zone.groupby(
            ["zone_2024", "mechanism", "strike_label"],
            as_index=False,
        )
        .agg(
            producer_mean_annual_revenue_real_2024_eur_per_mw=(
                "producer_revenue_real_2024_eur_per_mw",
                "mean",
            ),
            producer_std_annual_revenue_real_2024_eur_per_mw=(
                "producer_revenue_real_2024_eur_per_mw",
                "std",
            ),
            mean_annual_top_up_real_2024_eur_per_mw=(
                "top_up_real_2024_eur_per_mw",
                "mean",
            ),
            mean_annual_clawback_real_2024_eur_per_mw=(
                "clawback_real_2024_eur_per_mw",
                "mean",
            ),
            mean_annual_net_public_cost_real_2024_eur_per_mw=(
                "net_public_cost_real_2024_eur_per_mw",
                "mean",
            ),
            observed_years=("year", "nunique"),
        )
    )
    expected_zones = set(REGION_TO_ZONE.values())
    combinations = source[["mechanism", "strike_label"]].drop_duplicates()
    expected_rows = len(combinations) * len(expected_zones)
    if len(source) != expected_rows:
        raise ValueError(
            f"Incomplete zonal heatmap source: {len(source)} != {expected_rows}"
        )
    if set(source["zone_2024"]) != expected_zones:
        raise ValueError("Zonal heatmap source does not cover all seven 2024 zones")
    if not source["observed_years"].eq(annual_region["year"].nunique()).all():
        raise ValueError("Zonal heatmap source has incomplete annual coverage")
    zonal_identity_error = (
        source["mean_annual_top_up_real_2024_eur_per_mw"]
        - source["mean_annual_clawback_real_2024_eur_per_mw"]
        - source["mean_annual_net_public_cost_real_2024_eur_per_mw"]
    ).abs().max()
    if zonal_identity_error > 1e-5:
        raise ValueError("Zonal public-cost identity failed")
    return source.sort_values(
        ["mechanism", "strike_label", "zone_2024"]
    ).reset_index(drop=True)


def validate_hourly_accounting(
    frame: pd.DataFrame,
    mechanism: str,
    strike_real_2024_eur_per_mwh: float | None,
) -> None:
    """Validate settlement identities at hourly resolution."""

    tolerance = 1e-8
    revenue_error = (
        frame["producer_revenue_real_2024_eur_per_mw"]
        - frame["market_revenue_real_2024_eur_per_mw"]
        - frame["settlement_real_2024_eur_per_mw"]
    ).abs().max()
    state_error = (
        frame["top_up_real_2024_eur_per_mw"]
        - frame["clawback_real_2024_eur_per_mw"]
        - frame["net_public_cost_real_2024_eur_per_mw"]
    ).abs().max()
    if revenue_error > tolerance or state_error > tolerance:
        raise ValueError("Hourly market/settlement or public-cost identity failed")
    if mechanism == "conventional_cfd":
        target = (
            float(strike_real_2024_eur_per_mwh)
            * frame["quantity_mwh_per_mw"].to_numpy(dtype=float)
        )
        observed = frame["producer_revenue_real_2024_eur_per_mw"].to_numpy(dtype=float)
        if float(np.max(np.abs(observed - target))) > tolerance:
            raise ValueError("Conventional two-sided CfD does not equal K times Q")


def validate_annual_accounting(frame: pd.DataFrame) -> None:
    """Validate top-up minus clawback equals net public cost after aggregation."""

    suffixes = ("_per_mw", "_national_total")
    for suffix in suffixes:
        top_up = f"top_up_real_2024_eur{suffix}"
        clawback = f"clawback_real_2024_eur{suffix}"
        net = f"net_public_cost_real_2024_eur{suffix}"
        if {top_up, clawback, net}.issubset(frame.columns):
            error = (frame[top_up] - frame[clawback] - frame[net]).abs().max()
            if error > 1e-5:
                raise ValueError(f"Annual public-cost identity failed for {suffix}")
