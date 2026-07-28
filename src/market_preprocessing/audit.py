"""Build a preprocessing data audit for the 2024 baseline."""

from __future__ import annotations

from dataclasses import dataclass

from .config import EXPECTED_HOURS_2024, MAPPING_SOURCE, PRODUCTION_GRANULARITY
from .gme_prices import PriceRecord
from .mapping import REGION_TO_ZONE
from .terna_wind import FillEvent, RegionalWindRecord, ZonalWindRecord


@dataclass(frozen=True)
class AuditRow:
    """One row in data/processed/data_audit.csv."""

    dataset: str
    year: int
    region: str
    zone: str
    expected_hours: int
    observed_hours: int
    missing_hours_before_fill: int
    filled_hours: int
    missing_hour_timestamps: str
    fill_method: str
    capped_cf_count: int
    raw_cf_max: float | str
    final_cf_min: float | str
    final_cf_max: float | str
    installed_capacity_mw: float | str
    production_granularity: str
    mapping_source: str
    note: str


def build_data_audit(
    price_records: list[PriceRecord],
    zonal_records: list[ZonalWindRecord],
    regional_records: list[RegionalWindRecord],
    fill_events: list[FillEvent],
) -> list[AuditRow]:
    """Create audit rows covering prices, wind CFs, fills, caps and mapping."""

    rows: list[AuditRow] = []
    rows.extend(_price_audit_rows(price_records))
    rows.extend(_zonal_wind_audit_rows(zonal_records, fill_events))
    rows.extend(_regional_wind_audit_rows(regional_records))
    rows.extend(_mapping_rows())
    return rows


def _price_audit_rows(price_records: list[PriceRecord]) -> list[AuditRow]:
    rows: list[AuditRow] = []
    for zone in sorted({record.zone for record in price_records}):
        zone_records = [record for record in price_records if record.zone == zone]
        observed = len(zone_records)
        rows.append(
            AuditRow(
                dataset="gme_zonal_prices",
                year=2024,
                region="",
                zone=zone,
                expected_hours=EXPECTED_HOURS_2024,
                observed_hours=observed,
                missing_hours_before_fill=max(EXPECTED_HOURS_2024 - observed, 0),
                filled_hours=0,
                missing_hour_timestamps="",
                fill_method="none",
                capped_cf_count=0,
                raw_cf_max="",
                final_cf_min="",
                final_cf_max="",
                installed_capacity_mw="",
                production_granularity="observed_zonal_price",
                mapping_source="GME MGP zonal price workbook",
                note="2024 baseline includes Calabria.",
            )
        )
    return rows


def _zonal_wind_audit_rows(
    zonal_records: list[ZonalWindRecord],
    fill_events: list[FillEvent],
) -> list[AuditRow]:
    rows: list[AuditRow] = []
    for zone in sorted({record.zone for record in zonal_records}):
        zone_records = [record for record in zonal_records if record.zone == zone]
        zone_fills = [event for event in fill_events if event.zone == zone]
        raw_values = [record.raw_capacity_factor for record in zone_records]
        final_values = [record.capacity_factor for record in zone_records]
        rows.append(
            AuditRow(
                dataset="zonal_wind_capacity_factor",
                year=2024,
                region="",
                zone=zone,
                expected_hours=EXPECTED_HOURS_2024,
                observed_hours=len(zone_records),
                missing_hours_before_fill=len(zone_fills),
                filled_hours=len(zone_fills),
                missing_hour_timestamps=_join_methods(event.timestamp for event in zone_fills),
                fill_method=_join_methods(event.fill_method for event in zone_fills),
                capped_cf_count=sum(value > 1 for value in raw_values),
                raw_cf_max=max(raw_values),
                final_cf_min=min(final_values),
                final_cf_max=max(final_values),
                installed_capacity_mw=zone_records[0].installed_capacity_mw,
                production_granularity="zonal_forecast",
                mapping_source=MAPPING_SOURCE,
                note="Terna forecast MW divided by mapped zonal installed wind capacity.",
            )
        )
    return rows


def _regional_wind_audit_rows(
    regional_records: list[RegionalWindRecord],
) -> list[AuditRow]:
    rows: list[AuditRow] = []
    for region in sorted({record.region for record in regional_records}):
        region_records = [record for record in regional_records if record.region == region]
        raw_values = [record.raw_capacity_factor for record in region_records]
        final_values = [record.capacity_factor for record in region_records]
        filled = [record for record in region_records if record.filled]
        rows.append(
            AuditRow(
                dataset="regional_wind_capacity_factor",
                year=2024,
                region=region,
                zone=region_records[0].zone,
                expected_hours=EXPECTED_HOURS_2024,
                observed_hours=len(region_records),
                missing_hours_before_fill=len(filled),
                filled_hours=len(filled),
                missing_hour_timestamps=_join_methods(record.timestamp for record in filled),
                fill_method=_join_methods(record.fill_method for record in filled),
                capped_cf_count=sum(value > 1 for value in raw_values),
                raw_cf_max=max(raw_values),
                final_cf_min=min(final_values),
                final_cf_max=max(final_values),
                installed_capacity_mw=region_records[0].regional_installed_capacity_mw,
                production_granularity=PRODUCTION_GRANULARITY,
                mapping_source=MAPPING_SOURCE,
                note=(
                    "Regional generation is a capacity-share allocation of "
                    "Terna zonal hourly wind forecast."
                ),
            )
        )
    return rows


def _mapping_rows() -> list[AuditRow]:
    rows: list[AuditRow] = []
    for region, zone in sorted(REGION_TO_ZONE.items()):
        rows.append(
            AuditRow(
                dataset="region_to_zone_mapping",
                year=2024,
                region=region,
                zone=zone,
                expected_hours=0,
                observed_hours=0,
                missing_hours_before_fill=0,
                filled_hours=0,
                missing_hour_timestamps="",
                fill_method="not_applicable",
                capped_cf_count=0,
                raw_cf_max="",
                final_cf_min="",
                final_cf_max="",
                installed_capacity_mw="",
                production_granularity=PRODUCTION_GRANULARITY,
                mapping_source=MAPPING_SOURCE,
                note="Administrative region assigned to GME bidding zone.",
            )
        )
    return rows


def _join_methods(methods: object) -> str:
    materialized = sorted({method for method in methods if method})  # type: ignore[arg-type]
    return ";".join(materialized) if materialized else "none"
