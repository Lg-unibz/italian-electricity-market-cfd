"""Unit tests for historical Italian CfD settlement mechanics."""

from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from matplotlib.image import imread
import pandas as pd

from cfd_analysis.geography import (
    RegionGeometry,
    _select_mechanism_values,
    plot_market_only_metrics,
)
from cfd_analysis.copernicus_normalization import (
    aggregate_cds_admin1_frame,
    validate_admin1_weights,
)
from cfd_analysis.historical_inputs import local_delivery_slots, map_region_to_zone_for_year
from cfd_analysis.mechanisms import (
    MECHANISM_ORDER,
    WindCostAssumptions,
    build_annual_market_value_factor,
    build_decadal_market_value_factor,
    build_metric_summary,
    build_regional_value_factor_summary,
    build_regional_comparison_source,
    build_regional_distribution_summary,
    build_regional_metric_summary,
    build_zonal_heatmap_source,
    calculate_uniform_strikes,
    calculate_sharpe_ratio,
    settle_hourly,
)
from cfd_analysis.historical_backtest import _format_map_source_for_export
from market_preprocessing.mapping import REGION_TO_ZONE


class HistoricalMappingTests(unittest.TestCase):
    """Verify the two region-zone changes in the study decade."""

    def test_pre_2021_mapping(self) -> None:
        self.assertEqual(map_region_to_zone_for_year("Umbria", 2020), "Centro Nord")
        self.assertEqual(map_region_to_zone_for_year("Calabria", 2020), "Sud")

    def test_post_2021_mapping(self) -> None:
        self.assertEqual(map_region_to_zone_for_year("Umbria", 2021), "Centro Sud")
        self.assertEqual(map_region_to_zone_for_year("Calabria", 2021), "Calabria")

    def test_delivery_slots_preserve_leap_year_and_dst(self) -> None:
        self.assertEqual(len(local_delivery_slots(2019)), 8_760)
        self.assertEqual(len(local_delivery_slots(2020)), 8_784)
        slots = local_delivery_slots(2024)["timestamp_utc"]
        self.assertTrue(slots.is_unique)


class StrikeTests(unittest.TestCase):
    """Verify the CRF-based P50 and P25 uniform strike calculation."""

    def test_lower_flh_has_higher_strike(self) -> None:
        strikes = calculate_uniform_strikes(
            pd.Series([1_500.0, 1_700.0, 1_900.0, 2_100.0]),
            WindCostAssumptions(),
        ).set_index("strike_label")
        self.assertLess(
            strikes.loc["K_P50", "strike_real_2024_eur_per_mwh"],
            strikes.loc["K_P25", "strike_real_2024_eur_per_mwh"],
        )


class MechanismTests(unittest.TestCase):
    """Verify accounting and production independence of yardstick settlements."""

    def setUp(self) -> None:
        self.annualized_cost = 178_395.1046661212
        self.panel = pd.DataFrame(
            {
                "year": [2024, 2024],
                "timestamp_utc": pd.to_datetime(
                    ["2024-01-01T00:00:00Z", "2024-01-01T01:00:00Z"], utc=True
                ),
                "region": ["Puglia", "Puglia"],
                "zone": ["Sud", "Sud"],
                "installed_capacity_mw": [1.0, 1.0],
                "price_real_2024_eur_per_mwh": [50.0, -10.0],
                "quantity_mwh_per_mw": pd.Series([0.2, 0.8], dtype="float32"),
                "benchmark_mwh_per_mw": pd.Series([0.4, 0.6], dtype="float32"),
            }
        )

    def test_conventional_cfd_equals_k_times_q(self) -> None:
        result = settle_hourly(self.panel, "conventional_cfd", 80.0)
        expected = 80.0 * self.panel["quantity_mwh_per_mw"].astype("float64")
        pd.testing.assert_series_equal(
            result["producer_revenue_real_2024_eur_per_mw"],
            expected,
            check_names=False,
        )

    def test_zonal_yardstick_settlement_is_independent_of_plant_output(self) -> None:
        first = settle_hourly(self.panel, "zonal_yardstick_cfd", 80.0)
        changed = self.panel.copy()
        changed["quantity_mwh_per_mw"] = [0.9, 0.1]
        second = settle_hourly(changed, "zonal_yardstick_cfd", 80.0)
        pd.testing.assert_series_equal(
            first["settlement_real_2024_eur_per_mw"],
            second["settlement_real_2024_eur_per_mw"],
        )

    def test_schlecht_settlement_is_independent_of_plant_output(self) -> None:
        first = settle_hourly(
            self.panel,
            "schlecht_fcfd",
            80.0,
            self.annualized_cost,
        )
        changed = self.panel.copy()
        changed["quantity_mwh_per_mw"] = [0.9, 0.1]
        second = settle_hourly(
            changed,
            "schlecht_fcfd",
            80.0,
            self.annualized_cost,
        )
        pd.testing.assert_series_equal(
            first["settlement_real_2024_eur_per_mw"],
            second["settlement_real_2024_eur_per_mw"],
        )
        self.assertAlmostEqual(
            first["fixed_payment_real_2024_eur_per_mw"].sum(),
            self.annualized_cost,
        )
        pd.testing.assert_series_equal(
            first["top_up_real_2024_eur_per_mw"],
            first["fixed_payment_real_2024_eur_per_mw"],
            check_names=False,
        )
        expected_clawback = pd.Series([20.0, 0.0])
        pd.testing.assert_series_equal(
            first["clawback_real_2024_eur_per_mw"],
            expected_clawback,
            check_names=False,
        )

    def test_schlecht_fixed_payment_is_independent_of_strike_scenario(self) -> None:
        p50 = settle_hourly(
            self.panel,
            "schlecht_fcfd",
            80.0,
            self.annualized_cost,
        )
        p25 = settle_hourly(
            self.panel,
            "schlecht_fcfd",
            100.0,
            self.annualized_cost,
        )
        for column in (
            "fixed_payment_real_2024_eur_per_mw",
            "settlement_real_2024_eur_per_mw",
            "producer_revenue_real_2024_eur_per_mw",
            "top_up_real_2024_eur_per_mw",
            "clawback_real_2024_eur_per_mw",
            "net_public_cost_real_2024_eur_per_mw",
        ):
            pd.testing.assert_series_equal(p50[column], p25[column])

    def test_schlecht_requires_positive_annualized_cost(self) -> None:
        with self.assertRaises(ValueError):
            settle_hourly(self.panel, "schlecht_fcfd", 80.0)

    def test_public_cost_identity(self) -> None:
        result = settle_hourly(self.panel, "zonal_yardstick_cfd", 80.0)
        identity = (
            result["top_up_real_2024_eur_per_mw"]
            - result["clawback_real_2024_eur_per_mw"]
            - result["net_public_cost_real_2024_eur_per_mw"]
        )
        self.assertLess(identity.abs().max(), 1e-9)

    def test_sharpe_ratio_uses_zero_risk_free_rate_and_infinity_for_zero_risk(self) -> None:
        result = calculate_sharpe_ratio(
            pd.Series([10.0, 20.0]),
            pd.Series([5.0, 0.0]),
        )
        self.assertAlmostEqual(result.iloc[0], 2.0)
        self.assertTrue(result.iloc[1] == float("inf"))

    def test_annual_market_value_factor_uses_production_weighted_price(self) -> None:
        rows = []
        for region, zone in REGION_TO_ZONE.items():
            rows.extend(
                {
                    "year": 2024,
                    "timestamp_utc": timestamp,
                    "region": region,
                    "zone": zone,
                    "price_real_2024_eur_per_mwh": price,
                    "quantity_mwh_per_mw": quantity,
                }
                for timestamp, price, quantity in zip(
                    pd.to_datetime(
                        ["2024-01-01T00:00:00Z", "2024-01-01T01:00:00Z"],
                        utc=True,
                    ),
                    [10.0, 20.0],
                    [1.0, 3.0],
                    strict=True,
                )
            )
        result = build_annual_market_value_factor(pd.DataFrame(rows))
        self.assertEqual(len(result), 20)
        self.assertTrue(result["value_factor"].sub(17.5 / 15.0).abs().lt(1e-12).all())

    def test_decadal_market_value_factor_averages_ten_years_for_twenty_regions(
        self,
    ) -> None:
        rows = [
            {
                "year": year,
                "region": region,
                "value_factor": float(year - 2010 + index),
            }
            for index, region in enumerate(REGION_TO_ZONE)
            for year in range(2015, 2025)
        ]
        result = build_decadal_market_value_factor(pd.DataFrame(rows))
        self.assertEqual(len(result), 20)
        self.assertTrue(result["observed_years"].eq(10).all())
        self.assertAlmostEqual(
            result.loc[result["region"] == "Abruzzo", "ten_year_mean_value_factor"].iloc[0],
            21.5,
        )

        with self.assertRaises(ValueError):
            build_decadal_market_value_factor(pd.DataFrame(rows[:-1]))
        with self.assertRaises(ValueError):
            build_decadal_market_value_factor(
                pd.concat([pd.DataFrame(rows), pd.DataFrame([rows[0]])])
            )

    def test_regional_value_factor_summary_has_requested_statistics(self) -> None:
        rows = [
            {
                "year": year,
                "region": region,
                "value_factor": float(year - 2010 + index),
            }
            for index, region in enumerate(REGION_TO_ZONE)
            for year in range(2015, 2025)
        ]
        result = build_regional_value_factor_summary(pd.DataFrame(rows))
        self.assertEqual(
            list(result.columns),
            ["Region", "Mean_VF", "Std_Dev_VF", "Min_VF", "Max_VF"],
        )
        self.assertEqual(len(result), 20)
        abruzzo = result.loc[result["Region"] == "Abruzzo"].iloc[0]
        self.assertAlmostEqual(abruzzo["Mean_VF"], 21.5)
        self.assertAlmostEqual(
            abruzzo["Std_Dev_VF"], pd.Series(range(17, 27), dtype=float).std()
        )
        self.assertEqual(abruzzo["Min_VF"], 17.0)
        self.assertEqual(abruzzo["Max_VF"], 26.0)

    def test_map_source_formats_infinite_sharpe_as_latex_string(self) -> None:
        source = pd.DataFrame(
            {
                "region": ["Sardegna", "Sicilia", "Abruzzo"],
                "producer_sharpe_ratio": [float("inf"), float("-inf"), 1.25],
            }
        )
        result = _format_map_source_for_export(source)
        self.assertEqual(result.loc[0, "producer_sharpe_ratio"], r"+\infty")
        self.assertEqual(result.loc[1, "producer_sharpe_ratio"], r"-\infty")
        self.assertEqual(result.loc[2, "producer_sharpe_ratio"], 1.25)

    def test_market_only_map_renderer_writes_a_three_panel_figure(self) -> None:
        geometries = {
            region: RegionGeometry(
                region=region,
                rings=(
                    (
                        (float(index), 0.0),
                        (float(index) + 0.8, 0.0),
                        (float(index) + 0.8, 0.8),
                        (float(index), 0.8),
                        (float(index), 0.0),
                    ),
                ),
            )
            for index, region in enumerate(REGION_TO_ZONE)
        }
        source = pd.DataFrame(
            {
                "region": list(REGION_TO_ZONE),
                "producer_mean_annual_revenue_real_2024_eur_per_mw": range(100, 120),
                "producer_sharpe_ratio": [float(value) for value in range(1, 21)],
            }
        )
        decadal = pd.DataFrame(
            {
                "region": list(REGION_TO_ZONE),
                "ten_year_mean_value_factor": [0.9 + index / 100 for index in range(20)],
            }
        )
        with self.subTest("rendered figure"):
            with TemporaryDirectory() as directory:
                path = Path(directory) / "market_only.png"
                plot_market_only_metrics(geometries, source, decadal, path)
                self.assertTrue(path.exists())
                image = imread(path)
                self.assertGreater(image.shape[1], image.shape[0] * 1.8)

    def test_yardstick_differs_by_plant_but_matches_capacity_weighted_portfolio(
        self,
    ) -> None:
        panel = pd.DataFrame(
            {
                "year": [2024, 2024],
                "timestamp_utc": pd.to_datetime(
                    ["2024-01-01T00:00:00Z", "2024-01-01T00:00:00Z"],
                    utc=True,
                ),
                "region": ["Basilicata", "Puglia"],
                "zone": ["Sud", "Sud"],
                "installed_capacity_mw": [1.0, 3.0],
                "price_real_2024_eur_per_mwh": [50.0, 50.0],
                "quantity_mwh_per_mw": [0.2, 0.6],
                "benchmark_mwh_per_mw": [0.5, 0.5],
            }
        )
        conventional = settle_hourly(panel, "conventional_cfd", 80.0)
        yardstick = settle_hourly(panel, "zonal_yardstick_cfd", 80.0)
        self.assertFalse(
            conventional["producer_revenue_real_2024_eur_per_mw"].equals(
                yardstick["producer_revenue_real_2024_eur_per_mw"]
            )
        )
        for column in (
            "producer_revenue_real_2024_eur_per_mw",
            "top_up_real_2024_eur_per_mw",
            "clawback_real_2024_eur_per_mw",
            "net_public_cost_real_2024_eur_per_mw",
        ):
            conventional_total = (
                conventional[column] * conventional["installed_capacity_mw"]
            ).sum()
            yardstick_total = (
                yardstick[column] * yardstick["installed_capacity_mw"]
            ).sum()
            self.assertAlmostEqual(conventional_total, yardstick_total)

    def test_mechanism_ids_use_zonal_yardstick_name(self) -> None:
        self.assertIn("zonal_yardstick_cfd", MECHANISM_ORDER)
        self.assertNotIn("newbery_pcfd", MECHANISM_ORDER)


class CopernicusNormalizationTests(unittest.TestCase):
    """Verify the 110-unit mapping and deterministic area aggregation."""

    def setUp(self) -> None:
        regions = list(REGION_TO_ZONE)
        rows = [
            {
                "admin1_code": f"ITA-{index:04d}",
                "province": f"Unit {index}",
                "region": regions[index % len(regions)],
                "geodesic_area_sq_km": 1.0,
            }
            for index in range(110)
        ]
        self.weights = pd.DataFrame(rows)
        counts = self.weights.groupby("region")["admin1_code"].transform("count")
        self.weights["regional_area_weight"] = 1.0 / counts

    def test_exact_mapping_contract(self) -> None:
        validate_admin1_weights(self.weights)

    def test_area_weighted_regional_aggregation(self) -> None:
        regions = list(REGION_TO_ZONE)
        region_value = {region: index / 20 for index, region in enumerate(regions)}
        values = {
            row.admin1_code: [region_value[row.region]]
            for row in self.weights.itertuples(index=False)
        }
        frame = pd.DataFrame({"Date": ["2024-01-01 00:00:00"], **values})
        output = aggregate_cds_admin1_frame(
            frame,
            "Date",
            "ic2_5hh100",
            self.weights,
        ).set_index("region")
        for region, expected in region_value.items():
            self.assertAlmostEqual(output.loc[region, "capacity_factor"], expected)


class OutputContractTests(unittest.TestCase):
    """Verify the strict five-metric and fixed-zone output contracts."""

    def _annual_region(self) -> pd.DataFrame:
        combinations = [
            ("market_only", "not_applicable"),
            ("conventional_cfd", "K_P50"),
            ("conventional_cfd", "K_P25"),
            ("zonal_yardstick_cfd", "K_P50"),
            ("zonal_yardstick_cfd", "K_P25"),
            ("schlecht_fcfd", "K_P50"),
            ("schlecht_fcfd", "K_P25"),
        ]
        rows = []
        for year in range(2015, 2025):
            for region_index, region in enumerate(REGION_TO_ZONE, start=1):
                for mechanism, strike_label in combinations:
                    is_market = mechanism == "market_only"
                    top_up = 0.0 if is_market else 100.0 + region_index
                    clawback = 0.0 if is_market else 20.0
                    rows.append(
                        {
                            "year": year,
                            "region": region,
                            "zone": map_region_to_zone_for_year(region, year),
                            "mechanism": mechanism,
                            "strike_label": strike_label,
                            "installed_capacity_mw": float(region_index),
                            "producer_revenue_real_2024_eur_per_mw": (
                                1_000.0 + year + region_index
                            ),
                            "top_up_real_2024_eur_per_mw": top_up,
                            "clawback_real_2024_eur_per_mw": clawback,
                            "net_public_cost_real_2024_eur_per_mw": top_up - clawback,
                        }
                    )
        return pd.DataFrame(rows)

    def test_zonal_heatmap_source_has_49_complete_rows(self) -> None:
        source = build_zonal_heatmap_source(self._annual_region())
        self.assertEqual(len(source), 49)
        self.assertEqual(set(source["zone_2024"]), set(REGION_TO_ZONE.values()))
        self.assertTrue(source["observed_years"].eq(10).all())

    def test_five_metric_summary_has_only_authorized_metrics(self) -> None:
        annual_region = self._annual_region()
        national = (
            annual_region.groupby(
                ["year", "mechanism", "strike_label"],
                as_index=False,
            )
            .agg(
                producer_revenue_real_2024_eur_per_mw=(
                    "producer_revenue_real_2024_eur_per_mw",
                    "mean",
                ),
                top_up_real_2024_eur_per_mw=("top_up_real_2024_eur_per_mw", "mean"),
                clawback_real_2024_eur_per_mw=(
                    "clawback_real_2024_eur_per_mw",
                    "mean",
                ),
                net_public_cost_real_2024_eur_per_mw=(
                    "net_public_cost_real_2024_eur_per_mw",
                    "mean",
                ),
            )
        )
        summary = build_metric_summary(national)
        self.assertEqual(len(summary), 7)
        self.assertEqual(
            list(summary.columns),
            [
                "mechanism",
                "strike_label",
                "producer_mean_annual_revenue_real_2024_eur_per_mw",
                "producer_std_annual_revenue_real_2024_eur_per_mw",
                "mean_annual_top_up_real_2024_eur_per_mw",
                "mean_annual_clawback_real_2024_eur_per_mw",
                "mean_annual_net_public_cost_real_2024_eur_per_mw",
                "producer_sharpe_ratio",
            ],
        )

    def test_regional_summary_has_140_asset_level_rows(self) -> None:
        annual_region = self._annual_region()
        summary = build_regional_metric_summary(annual_region)
        self.assertEqual(len(summary), 140)
        self.assertEqual(summary["region"].nunique(), 20)
        self.assertEqual(
            list(summary.columns),
            [
                "region",
                "zone_2024",
                "mechanism",
                "strike_label",
                "producer_mean_annual_revenue_real_2024_eur_per_mw",
                "producer_std_annual_revenue_real_2024_eur_per_mw",
                "mean_annual_top_up_real_2024_eur_per_mw",
                "mean_annual_clawback_real_2024_eur_per_mw",
                "mean_annual_net_public_cost_real_2024_eur_per_mw",
                "producer_sharpe_ratio",
            ],
        )
        expected_std = pd.Series(range(2015, 2025), dtype=float).std()
        self.assertTrue(
            summary[
                "producer_std_annual_revenue_real_2024_eur_per_mw"
            ].sub(expected_std).abs().lt(1e-9).all()
        )

    def test_regional_comparison_has_four_complete_k_p50_panels(self) -> None:
        regional = build_regional_metric_summary(self._annual_region())
        comparison = build_regional_comparison_source(regional)
        self.assertEqual(len(comparison), 80)
        self.assertEqual(comparison["region"].nunique(), 20)
        self.assertNotIn("zone_2024", comparison.columns)
        self.assertIn("current_zone", comparison.columns)
        counts = comparison.groupby("mechanism")["region"].nunique()
        self.assertTrue(counts.eq(20).all())
        self.assertEqual(
            set(comparison.loc[comparison["mechanism"] == "market_only", "strike_label"]),
            {"not_applicable"},
        )
        self.assertEqual(
            set(comparison.loc[comparison["mechanism"] != "market_only", "strike_label"]),
            {"K_P50"},
        )

    def test_regional_comparison_can_select_complete_k_p25_panels(self) -> None:
        regional = build_regional_metric_summary(self._annual_region())
        comparison = build_regional_comparison_source(regional, strike_label="K_P25")
        self.assertEqual(len(comparison), 80)
        self.assertEqual(comparison["region"].nunique(), 20)
        self.assertEqual(
            set(comparison.loc[comparison["mechanism"] != "market_only", "strike_label"]),
            {"K_P25"},
        )

    def test_regional_distribution_summarizes_mapped_values(self) -> None:
        regional = build_regional_metric_summary(self._annual_region())
        comparison = build_regional_comparison_source(regional)
        distribution = build_regional_distribution_summary(comparison)
        self.assertEqual(len(distribution), 12)
        self.assertEqual(distribution["metric"].nunique(), 3)
        self.assertEqual(distribution["mechanism"].nunique(), 4)
        revenue = distribution[
            (distribution["metric"] == "Mean annual producer revenue")
            & (distribution["mechanism"] == "market_only")
        ].iloc[0]
        expected = comparison.loc[
            comparison["mechanism"] == "market_only",
            "producer_mean_annual_revenue_real_2024_eur_per_mw",
        ]
        self.assertAlmostEqual(
            revenue["regional_mean_real_2024_eur_per_mw_year"],
            expected.mean(),
        )
        self.assertAlmostEqual(
            revenue["regional_p25_real_2024_eur_per_mw_year"],
            expected.quantile(0.25),
        )

    def test_map_panel_selection_does_not_leak_values_between_mechanisms(self) -> None:
        source = pd.DataFrame(
            [
                {
                    "region": region,
                    "mechanism": mechanism,
                    "metric": float(index + offset),
                }
                for offset, mechanism in enumerate(
                    ("conventional_cfd", "zonal_yardstick_cfd", "schlecht_fcfd")
                )
                for index, region in enumerate(REGION_TO_ZONE)
            ]
        )
        conventional = _select_mechanism_values(
            source, "conventional_cfd", "metric"
        )
        financial = _select_mechanism_values(source, "schlecht_fcfd", "metric")
        self.assertEqual(conventional.iloc[0], 0.0)
        self.assertEqual(financial.iloc[0], 2.0)
        self.assertFalse(conventional.equals(financial))


if __name__ == "__main__":
    unittest.main()
