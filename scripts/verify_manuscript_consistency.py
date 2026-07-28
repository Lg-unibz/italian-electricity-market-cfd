"""Verify static manuscript tables, claims, and figures against result CSVs."""

from __future__ import annotations

import argparse
import math
import re
from pathlib import Path

import pandas as pd


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_RESULTS = (
    PACKAGE_ROOT / "results" / "historical_cfd_backtest_2015_2024"
)
MECHANISM_LABELS = {
    "market_only": "Market only",
    "conventional_cfd": "Conventional",
    "zonal_yardstick_cfd": "Zonal Yardstick",
    "schlecht_fcfd": "Financial CfD",
}
MECHANISM_ORDER = tuple(MECHANISM_LABELS)
EXPECTED_FIGURES = {
    "italy_regional_wind_capacity_factor.png",
    "italy_market_only_maps.png",
    "cfd_comparison_mean_revenue_k_p50.png",
    "cfd_comparison_sharpe_ratio_k_p50.png",
    "cfd_comparison_net_public_cost_k_p50.png",
    "cfd_comparison_mean_revenue_k_p25.png",
    "cfd_comparison_sharpe_ratio_k_p25.png",
    "cfd_comparison_net_public_cost_k_p25.png",
}


class Audit:
    """Collect exact manuscript-consistency failures."""

    def __init__(self) -> None:
        self.checks = 0
        self.failures: list[str] = []

    def require(self, condition: bool, message: str) -> None:
        """Record one condition and its failure message."""

        self.checks += 1
        if not condition:
            self.failures.append(message)

    def contains(self, text: str, fragment: str, label: str) -> None:
        """Require one exact fragment in a manuscript block."""

        self.require(fragment in text, f"{label}: missing `{fragment}`")


def table_block(text: str, label: str, end_marker: str) -> str:
    """Return the manuscript block starting at one LaTeX label."""

    start = text.find(label)
    if start < 0:
        raise ValueError(f"Missing manuscript label: {label}")
    end = text.find(end_marker, start)
    if end < 0:
        raise ValueError(f"Missing end marker after {label}: {end_marker}")
    return text[start : end + len(end_marker)]


def sharpe_cell(value: object) -> str:
    """Format one map-source Sharpe value exactly as the manuscript."""

    text = str(value)
    if "infty" in text or "inf" in text.lower():
        return r"$+\infty$"
    return f"{float(value):.2f}"


def map_row(row: pd.Series) -> str:
    """Format one complete K_P50 map-source manuscript row."""

    return (
        f"{row['region']} & {row['current_zone']} & "
        f"{MECHANISM_LABELS[str(row['mechanism'])]} & "
        f"{float(row['producer_mean_annual_revenue_real_2024_eur_per_mw']) / 1000:.1f} & "
        f"{float(row['producer_std_annual_revenue_real_2024_eur_per_mw']) / 1000:.1f} & "
        f"{sharpe_cell(row['producer_sharpe_ratio'])} & "
        f"{float(row['mean_annual_net_public_cost_real_2024_eur_per_mw']) / 1000:.1f}"
        r"\\"
    )


def regional_result_row(row: pd.Series, include_region: bool) -> str:
    """Format one complete regional-results appendix row."""

    prefix = str(row["region"]) if include_region else ""
    return (
        f"{prefix} & {MECHANISM_LABELS[str(row['mechanism'])]} & "
        f"{float(row['producer_mean_annual_revenue_real_2024_eur_per_mw']) / 1000:.1f} & "
        f"{float(row['producer_std_annual_revenue_real_2024_eur_per_mw']) / 1000:.1f} & "
        f"{sharpe_cell(row['producer_sharpe_ratio'])} & "
        f"{float(row['mean_annual_net_public_cost_real_2024_eur_per_mw']) / 1000:.1f} "
        r"\\"
    )


def verify_figures(
    audit: Audit,
    manuscript: str,
    figures_dir: Path,
) -> None:
    """Verify the exact eight paper figure references and files."""

    referenced = set(
        re.findall(r"\\includegraphics(?:\[[^\]]*\])?\{figures/([^}]+)\}", manuscript)
    )
    audit.require(
        referenced == EXPECTED_FIGURES,
        f"figure references differ: {sorted(referenced ^ EXPECTED_FIGURES)}",
    )
    for name in EXPECTED_FIGURES:
        audit.require((figures_dir / name).is_file(), f"missing figure: {name}")


def verify_calibration_and_technology(
    audit: Audit,
    manuscript: str,
    tables_dir: Path,
) -> None:
    """Verify calibration and technology-selection appendix tables."""

    strikes = pd.read_csv(tables_dir / "uniform_strike_calibration.csv").set_index(
        "strike_label"
    )
    technology = pd.read_csv(
        tables_dir / "copernicus_technology_selection.csv"
    )
    block = table_block(manuscript, r"\label{tab:calibration}", r"\end{table}")
    p50 = strikes.loc["K_P50"]
    p25 = strikes.loc["K_P25"]
    audit.contains(
        block,
        (
            "Annualised cost [kEUR/MW-year] & "
            f"{p50['annualized_cost_real_2024_eur_per_mw'] / 1000:.1f} & "
            f"{p25['annualized_cost_real_2024_eur_per_mw'] / 1000:.1f}"
        ),
        "calibration",
    )
    audit.contains(
        block,
        (
            "Reference FLH [MWh/MW] & "
            f"{p50['reference_flh_mwh_per_mw']:,.2f} & "
            f"{p25['reference_flh_mwh_per_mw']:,.2f}"
        ),
        "calibration",
    )
    audit.contains(
        block,
        (
            "Strike [real-2024 EUR/MWh] & "
            f"{p50['strike_real_2024_eur_per_mwh']:.2f} & "
            f"{p25['strike_real_2024_eur_per_mwh']:.2f}"
        ),
        "calibration",
    )
    tech_block = table_block(
        manuscript,
        r"\label{tab:technology_selection}",
        r"\end{table}",
    )
    for row in technology.itertuples(index=False):
        name = str(row.technology).replace("_", r"\_")
        selected = "Yes" if bool(row.selected_national_technology) else "No"
        expected = (
            rf"\texttt{{{name}}} & "
            f"{row.mean_absolute_error_mwh_per_mw:,.1f} & "
            f"{row.mean_bias_mwh_per_mw:,.1f} & {selected}"
        )
        audit.contains(tech_block, expected, f"technology {row.technology}")


def verify_value_factor_table(
    audit: Audit,
    manuscript: str,
    tables_dir: Path,
) -> None:
    """Verify all 20 annual Value Factor summary rows."""

    block = table_block(
        manuscript,
        r"\label{tab:regional_value_factor_summary}",
        r"\end{longtable}",
    )
    values = pd.read_csv(tables_dir / "regional_value_factor_summary.csv")
    for row in values.itertuples(index=False):
        expected = (
            f"{row.Region} & {row.Mean_VF:.3f} & {row.Std_Dev_VF:.3f} & "
            f"{row.Min_VF:.3f} & {row.Max_VF:.3f}"
            r"\\"
        )
        audit.contains(block, expected, f"Value Factor {row.Region}")


def verify_regional_tables(
    audit: Audit,
    manuscript: str,
    tables_dir: Path,
) -> pd.DataFrame:
    """Verify all 80 map rows and all 80 complete regional result rows."""

    source = pd.read_csv(
        tables_dir / "regional_comparison_map_source.csv",
        dtype={"producer_sharpe_ratio": str},
    )
    map_block = table_block(
        manuscript,
        r"\label{tab:regional_map_source_complete}",
        r"\end{longtable}",
    )
    results_block = table_block(
        manuscript,
        r"\label{tab:regional_results_full}",
        r"\end{longtable}",
    )
    for _, row in source.iterrows():
        audit.contains(
            map_block,
            map_row(row),
            f"map row {row['region']}/{row['mechanism']}",
        )
    for region, region_rows in source.groupby("region", sort=False):
        ordered = region_rows.set_index("mechanism").loc[list(MECHANISM_ORDER)]
        for mechanism, row in ordered.iterrows():
            row = row.copy()
            row["mechanism"] = mechanism
            audit.contains(
                results_block,
                regional_result_row(row, include_region=mechanism == "market_only"),
                f"regional row {region}/{mechanism}",
            )
    return source


def parse_distribution_rows(block: str) -> dict[tuple[str, str], list[str]]:
    """Parse the compact distribution table into metric-mechanism cells."""

    rows: dict[tuple[str, str], list[str]] = {}
    current_metric = ""
    for raw_line in block.splitlines():
        if "&" not in raw_line or not raw_line.rstrip().endswith(r"\\"):
            continue
        cells = [cell.strip() for cell in raw_line.rstrip()[:-2].split("&")]
        if len(cells) != 8:
            continue
        if cells[0]:
            current_metric = cells[0]
        rows[(current_metric, cells[1])] = cells[2:]
    return rows


def normalized_cell(value: str) -> str:
    """Remove LaTeX math delimiters for stable numeric comparison."""

    return value.replace("$", "").replace(r"\,", "").strip()


def verify_distribution_table(
    audit: Audit,
    manuscript: str,
    tables_dir: Path,
    source: pd.DataFrame,
) -> None:
    """Verify distribution rows, including finite-only Financial Sharpe moments."""

    block = table_block(
        manuscript,
        r"\label{tab:regional_distribution}",
        r"\end{table}",
    )
    parsed = parse_distribution_rows(block)
    distribution = pd.read_csv(
        tables_dir / "regional_metric_distribution_summary.csv"
    )
    metric_labels = {
        "Mean annual producer revenue": "Mean revenue",
        "Annual producer revenue SD": "Revenue SD",
        "Mean annual net public cost": "Net public cost",
    }
    columns = (
        "regional_mean_real_2024_eur_per_mw_year",
        "regional_std_real_2024_eur_per_mw_year",
        "regional_p25_real_2024_eur_per_mw_year",
        "regional_median_real_2024_eur_per_mw_year",
        "regional_p75_real_2024_eur_per_mw_year",
    )
    for row in distribution.itertuples(index=False):
        key = (metric_labels[row.metric], MECHANISM_LABELS[row.mechanism])
        actual = parsed.get(key)
        audit.require(actual is not None, f"missing distribution row {key}")
        if actual is None:
            continue
        expected_values = [
            f"{getattr(row, column) / 1000:.1f}" for column in columns
        ]
        expected_range = (
            f"{row.regional_min_real_2024_eur_per_mw_year / 1000:.1f}--"
            f"{row.regional_max_real_2024_eur_per_mw_year / 1000:.1f}"
        )
        normalized = [normalized_cell(value) for value in actual]
        for expected, observed in zip(expected_values, normalized[:5], strict=True):
            audit.require(
                observed == expected,
                f"distribution {key}: {observed} != {expected}",
            )
        audit.require(
            normalized_cell(actual[5]) == expected_range,
            f"distribution range {key}: {actual[5]} != {expected_range}",
        )

    numeric_sharpe = pd.to_numeric(
        source["producer_sharpe_ratio"].str.replace(r"\infty", "inf", regex=False),
        errors="coerce",
    )
    source = source.assign(_sharpe=numeric_sharpe)
    for mechanism in MECHANISM_ORDER:
        values = source.loc[source["mechanism"].eq(mechanism), "_sharpe"]
        finite = values[values.map(math.isfinite)]
        key = ("Sharpe Ratio", MECHANISM_LABELS[mechanism])
        actual = parsed.get(key)
        audit.require(actual is not None, f"missing distribution row {key}")
        if actual is None:
            continue
        expected_values = [
            finite.mean(),
            finite.std(),
            finite.quantile(0.25),
            finite.median(),
            finite.quantile(0.75),
        ]
        for expected, observed in zip(expected_values, actual[:5], strict=True):
            audit.require(
                normalized_cell(observed) == f"{expected:.2f}",
                f"Sharpe distribution {key}: {observed} != {expected:.2f}",
            )
        expected_max = r"+\infty" if len(finite) < len(values) else f"{finite.max():.2f}"
        expected_range = f"{finite.min():.2f}--{expected_max}"
        audit.require(
            normalized_cell(actual[5]) == expected_range,
            f"Sharpe range {key}: {actual[5]} != {expected_range}",
        )


def verify_claims_and_flows(
    audit: Audit,
    manuscript: str,
    tables_dir: Path,
    source: pd.DataFrame,
) -> None:
    """Verify headline claims and the robustness-flow table."""

    limits = pd.read_csv(
        tables_dir / "zonal_yardstick_30000_mwh_limit.csv"
    ).set_index("region")
    audit.contains(
        manuscript,
        (
            f"approximately "
            f"{limits.loc['Molise', 'estimated_years_to_30000_mwh_per_mw']:.1f} "
            f"years in Molise, but only after "
            f"{limits.loc['Lombardia', 'estimated_years_to_30000_mwh_per_mw']:.1f} "
            "years in Lombardia"
        ),
        "volumetric-limit claim",
    )
    campania = source[
        source["region"].eq("Campania")
        & source["mechanism"].eq("schlecht_fcfd")
    ].iloc[0]
    audit.contains(
        manuscript,
        f"Sharpe\nRatio of {float(campania['producer_sharpe_ratio']):.2f}",
        "Campania Sharpe claim",
    )

    regional = pd.read_csv(tables_dir / "regional_five_metric_summary.csv")
    national = pd.read_csv(tables_dir / "five_metric_summary.csv")
    flow_block = table_block(
        manuscript,
        r"\label{tab:robustness_flows}",
        r"\end{table}",
    )
    for strike in ("K_P50", "K_P25"):
        subset = regional[regional["strike_label"].eq(strike)]
        std = subset.pivot(
            index="region",
            columns="mechanism",
            values="producer_std_annual_revenue_real_2024_eur_per_mw",
        )
        counts = {
            mechanism: int(
                std[mechanism].lt(std["conventional_cfd"]).sum()
            )
            for mechanism in ("zonal_yardstick_cfd", "schlecht_fcfd")
        }
        rows = national[national["strike_label"].eq(strike)].set_index("mechanism")
        conventional = rows.loc["conventional_cfd"]
        yardstick = rows.loc["zonal_yardstick_cfd"]
        financial = rows.loc["schlecht_fcfd"]
        strike_tex = rf"$K_{{{strike.split('_')[1]}}}$"
        audit.contains(
            flow_block,
            (
                f"{strike_tex} & Conventional & Reference & "
                f"{conventional['mean_annual_top_up_real_2024_eur_per_mw'] / 1000:.1f} & "
                f"{conventional['mean_annual_clawback_real_2024_eur_per_mw'] / 1000:.1f} & "
                f"{conventional['mean_annual_net_public_cost_real_2024_eur_per_mw'] / 1000:.1f}"
            ),
            f"{strike} conventional flows",
        )
        audit.contains(
            flow_block,
            (
                f"& Zonal Yardstick & {counts['zonal_yardstick_cfd']} & "
                f"{yardstick['mean_annual_top_up_real_2024_eur_per_mw'] / 1000:.1f} & "
                f"{yardstick['mean_annual_clawback_real_2024_eur_per_mw'] / 1000:.1f} & "
                f"{yardstick['mean_annual_net_public_cost_real_2024_eur_per_mw'] / 1000:.1f}"
            ),
            f"{strike} yardstick flows",
        )
        audit.contains(
            flow_block,
            (
                f"& Financial CfD & {counts['schlecht_fcfd']} & "
                f"{financial['mean_annual_top_up_real_2024_eur_per_mw'] / 1000:.1f} & "
                f"{financial['mean_annual_clawback_real_2024_eur_per_mw'] / 1000:.1f} & "
                f"{financial['mean_annual_net_public_cost_real_2024_eur_per_mw'] / 1000:.1f}"
            ),
            f"{strike} financial flows",
        )


def main() -> int:
    """Run every manuscript-output consistency check."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manuscript", type=Path, required=True)
    parser.add_argument("--results-dir", type=Path, default=DEFAULT_RESULTS)
    args = parser.parse_args()
    manuscript = args.manuscript.read_text(encoding="utf-8")
    results_dir = args.results_dir.resolve()
    tables_dir = results_dir / "tables"
    figures_dir = results_dir / "figures"

    audit = Audit()
    verify_figures(audit, manuscript, figures_dir)
    verify_calibration_and_technology(audit, manuscript, tables_dir)
    verify_value_factor_table(audit, manuscript, tables_dir)
    source = verify_regional_tables(audit, manuscript, tables_dir)
    verify_distribution_table(audit, manuscript, tables_dir, source)
    verify_claims_and_flows(audit, manuscript, tables_dir, source)

    if audit.failures:
        print(
            f"Manuscript consistency failed: {len(audit.failures)} of "
            f"{audit.checks} checks failed."
        )
        print("\n".join(f"  {failure}" for failure in audit.failures))
        return 1
    print(f"Manuscript consistency passed: {audit.checks} checks.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
