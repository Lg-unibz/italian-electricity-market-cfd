"""Build 2024 preprocessing datasets, audit files and plots."""

from __future__ import annotations

import csv
import json
from dataclasses import fields
from pathlib import Path

from .audit import AuditRow, build_data_audit
from .config import (
    EXPECTED_HOURS_2024,
    MAPPING_SOURCE,
    PREPROCESSING_FIGURES_DIR,
    PROCESSED_DIR,
    ZONE_ORDER,
    ensure_output_dirs,
)
from .gme_prices import PriceRecord, load_gme_zonal_prices_2024
from .mapping import regions_by_zone
from .preprocess_types import MarketSlot, PreprocessingPanelRecord, ZoneMarketValueSummary
from .terna_wind import (
    RegionalWindRecord,
    ZonalWindRecord,
    build_regional_wind_capacity_factors,
    build_zonal_wind_capacity_factors,
)
from .visualization import build_preprocessing_figures


def run_preprocessing_pipeline() -> dict[str, dict[str, Path] | list[Path]]:
    """Run the 2024 preprocessing-only pipeline end to end."""

    ensure_output_dirs()
    _clean_generated_outputs()

    price_records = load_gme_zonal_prices_2024()
    market_slots = _market_slots_from_prices(price_records)
    zonal_records, fill_events, capacity_by_region, capacity_by_zone = (
        build_zonal_wind_capacity_factors(market_slots=market_slots)
    )
    regional_records = build_regional_wind_capacity_factors(
        zonal_records,
        capacity_by_region,
        capacity_by_zone,
        MAPPING_SOURCE,
    )
    panel_records = build_preprocessing_panel(price_records, zonal_records)
    market_value_summary = build_zone_market_value_summary(panel_records)
    audit_rows = build_data_audit(price_records, zonal_records, regional_records, fill_events)

    processed_outputs = {
        "gme_zonal_prices": PROCESSED_DIR / "gme_zonal_prices_2024.csv",
        "regional_wind_capacity_factors": PROCESSED_DIR
        / "regional_wind_capacity_factors_2024.csv",
        "zonal_wind_capacity_factors": PROCESSED_DIR / "zonal_wind_capacity_factors_2024.csv",
        "preprocessing_panel": PROCESSED_DIR / "preprocessing_panel_2024.csv",
        "data_audit": PROCESSED_DIR / "data_audit.csv",
        "figure_capacity_factor_by_region": PROCESSED_DIR
        / "figure_capacity_factor_by_region_2024.csv",
        "figure_zonal_prices": PROCESSED_DIR / "figure_zonal_prices_2024.csv",
        "figure_simple_market_revenue": PROCESSED_DIR
        / "figure_simple_market_revenue_2024.csv",
        "figure_market_value_decomposition": PROCESSED_DIR
        / "figure_market_value_decomposition_2024.csv",
        "zone_region_mapping": PROCESSED_DIR / "zone_region_mapping_2024.json",
    }
    _write_dataclass_csv(processed_outputs["gme_zonal_prices"], price_records)
    _write_dataclass_csv(
        processed_outputs["regional_wind_capacity_factors"],
        regional_records,
    )
    _write_dataclass_csv(processed_outputs["zonal_wind_capacity_factors"], zonal_records)
    _write_dataclass_csv(processed_outputs["preprocessing_panel"], panel_records)
    _write_dataclass_csv(processed_outputs["data_audit"], audit_rows)
    _write_dataclass_csv(
        processed_outputs["figure_capacity_factor_by_region"],
        regional_records,
    )
    _write_dataclass_csv(processed_outputs["figure_zonal_prices"], price_records)
    _write_dataclass_csv(
        processed_outputs["figure_simple_market_revenue"],
        panel_records,
    )
    _write_dataclass_csv(
        processed_outputs["figure_market_value_decomposition"],
        market_value_summary,
    )
    _write_zone_region_mapping_json(processed_outputs["zone_region_mapping"])

    figure_outputs = build_preprocessing_figures(
        price_records,
        regional_records,
        panel_records,
        market_value_summary,
        PREPROCESSING_FIGURES_DIR,
    )
    _validate_outputs(processed_outputs, figure_outputs, zonal_records, regional_records, panel_records)
    return {"processed": processed_outputs, "figures": figure_outputs}


def build_preprocessing_panel(
    price_records: list[PriceRecord],
    zonal_records: list[ZonalWindRecord],
) -> list[PreprocessingPanelRecord]:
    """Join GME prices to zonal CFs and compute simple market revenue.

    Formula:
        revenue_z_t = CF_z_t * 1 MW * price_z_t

    With hourly observations, CF times 1 MW is MWh for the hour.
    """

    wind_by_key = {
        (record.zone, record.row_index): record
        for record in zonal_records
    }
    panel: list[PreprocessingPanelRecord] = []
    for price in price_records:
        wind = wind_by_key.get((price.zone, price.row_index))
        if wind is None:
            raise ValueError(f"Missing wind CF for {price.zone}, row {price.row_index}")
        panel.append(
            PreprocessingPanelRecord(
                year=price.year,
                zone=price.zone,
                row_index=price.row_index,
                timestamp=price.timestamp,
                date=price.date,
                day_of_year=price.day_of_year,
                hour_ending=price.hour_ending,
                price_eur_mwh=price.price_eur_mwh,
                capacity_factor=wind.capacity_factor,
                normalized_generation_mwh_per_mw=wind.normalized_generation_mwh_per_mw,
                simple_market_revenue_eur_per_mw_hour=(
                    wind.normalized_generation_mwh_per_mw * price.price_eur_mwh
                ),
                wind_generation_mwh=wind.wind_generation_mwh,
                installed_capacity_mw=wind.installed_capacity_mw,
                price_source_file=price.source_file,
                wind_data_source=wind.wind_data_source,
                capacity_data_source=wind.capacity_data_source,
            )
        )
    return panel


def build_zone_market_value_summary(
    panel_records: list[PreprocessingPanelRecord],
) -> list[ZoneMarketValueSummary]:
    """Summarize annual production volume, capture price and market revenue by zone."""

    summaries: list[ZoneMarketValueSummary] = []
    for zone in ZONE_ORDER:
        zone_records = [record for record in panel_records if record.zone == zone]
        if not zone_records:
            continue
        full_load_hours = sum(
            record.normalized_generation_mwh_per_mw
            for record in zone_records
        )
        annual_revenue = sum(
            record.simple_market_revenue_eur_per_mw_hour
            for record in zone_records
        )
        mean_price = sum(record.price_eur_mwh for record in zone_records) / len(zone_records)
        capture_price = annual_revenue / full_load_hours if full_load_hours else 0.0
        summaries.append(
            ZoneMarketValueSummary(
                year=zone_records[0].year,
                zone=zone,
                installed_capacity_mw=zone_records[0].installed_capacity_mw,
                full_load_hours_mwh_per_mw_year=full_load_hours,
                mean_capacity_factor=full_load_hours / len(zone_records),
                mean_zonal_price_eur_mwh=mean_price,
                capture_price_eur_mwh=capture_price,
                capture_discount_pct=(capture_price / mean_price - 1) * 100,
                annual_market_revenue_eur_per_mw=annual_revenue,
            )
        )
    return summaries


def _market_slots_from_prices(price_records: list[PriceRecord]) -> list[MarketSlot]:
    zones = sorted({record.zone for record in price_records})
    if not zones:
        raise ValueError("No GME price records available for market slot extraction")
    anchor_zone = zones[0]
    anchor_records = sorted(
        [record for record in price_records if record.zone == anchor_zone],
        key=lambda record: record.row_index,
    )
    expected_row_indices = [record.row_index for record in anchor_records]
    for zone in zones:
        zone_indices = [
            record.row_index
            for record in sorted(
                [record for record in price_records if record.zone == zone],
                key=lambda record: record.row_index,
            )
        ]
        if zone_indices != expected_row_indices:
            raise ValueError(f"GME market calendar differs for zone {zone}")
    return [
        MarketSlot(
            row_index=record.row_index,
            timestamp=record.timestamp,
            date=record.date,
            day_of_year=record.day_of_year,
            hour_ending=record.hour_ending,
        )
        for record in anchor_records
    ]


def _clean_generated_outputs() -> None:
    PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    for path in PROCESSED_DIR.rglob("*"):
        if path.is_file():
            path.unlink()
    for path in sorted(PROCESSED_DIR.rglob("*"), reverse=True):
        if path.is_dir():
            path.rmdir()


def _validate_outputs(
    processed_outputs: dict[str, Path],
    figure_outputs: list[Path],
    zonal_records: list[ZonalWindRecord],
    regional_records: list[RegionalWindRecord],
    panel_records: list[PreprocessingPanelRecord],
) -> None:
    for name, path in processed_outputs.items():
        if not path.exists() or path.stat().st_size == 0:
            raise ValueError(f"Missing or empty processed output {name}: {path}")
    for path in figure_outputs:
        if not path.exists() or path.stat().st_size == 0:
            raise ValueError(f"Missing or empty figure: {path}")
    for record in zonal_records:
        if record.capacity_factor < 0 or record.capacity_factor > 1:
            raise ValueError(f"Zonal CF outside [0, 1]: {record}")
    for record in regional_records:
        if record.capacity_factor < 0 or record.capacity_factor > 1:
            raise ValueError(f"Regional CF outside [0, 1]: {record}")
    counts: dict[str, int] = {}
    for record in panel_records:
        counts[record.zone] = counts.get(record.zone, 0) + 1
    for zone, count in counts.items():
        if count != EXPECTED_HOURS_2024:
            raise ValueError(
                f"Unexpected panel row count for {zone}: "
                f"{count}, expected {EXPECTED_HOURS_2024}"
            )


def _write_dataclass_csv(path: Path, rows: list[object]) -> None:
    if not rows:
        raise ValueError(f"No rows to write for {path}")
    fieldnames = [field.name for field in fields(rows[0])]
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: getattr(row, field) for field in fieldnames})


def _write_zone_region_mapping_json(path: Path) -> None:
    payload = {
        zone: {
            "regions": regions,
            "region_count": len(regions),
        }
        for zone, regions in sorted(regions_by_zone().items())
    }
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
