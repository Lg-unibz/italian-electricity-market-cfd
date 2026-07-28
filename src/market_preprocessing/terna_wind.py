"""Terna wind forecast and capacity preprocessing for the 2024 baseline."""

from __future__ import annotations

import csv
import json
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

from .config import (
    BASELINE_YEAR,
    CAPACITY_DATASET,
    EXPECTED_HOURS_2024,
    PRODUCTION_GRANULARITY,
    SESSION_PRIORITY,
    TERNA_CAPACITY_FILE,
    TERNA_ENDPOINT,
    TERNA_WIND_FORECAST_FILE,
    TERNA_ZONE_TO_ZONE,
    WIND_FORECAST_DATASET,
)
from .mapping import REGION_TO_ZONE, canonical_region, map_region_to_zone
from .preprocess_types import MarketSlot


WIND_SOURCE_LABEL = "Terna WindProductionForecast, highest available MSD session"
CAPACITY_SOURCE_LABEL = "Terna CapacityRenewableSources, wind gross capacity"


@dataclass(frozen=True)
class FillEvent:
    """One source-hour gap filled in the Terna wind forecast series."""

    year: int
    zone: str
    timestamp: str
    fill_method: str


@dataclass(frozen=True)
class ZonalWindRecord:
    """One hourly zonal wind capacity-factor observation.

    Units:
        wind_generation_mwh is forecast MW interpreted as MWh over one hour.
        installed_capacity_mw is MW.
    """

    year: int
    zone: str
    row_index: int
    timestamp: str
    date: str
    day_of_year: int
    hour_ending: int
    wind_generation_mwh: float
    installed_capacity_mw: float
    raw_capacity_factor: float
    capacity_factor: float
    normalized_generation_mwh_per_mw: float
    source_terna_zone: str
    source_session: str
    filled: bool
    fill_method: str
    wind_data_source: str
    capacity_data_source: str


@dataclass(frozen=True)
class RegionalWindRecord:
    """One hourly region-level proxy derived from zonal Terna wind data."""

    year: int
    region: str
    zone: str
    row_index: int
    timestamp: str
    date: str
    day_of_year: int
    hour_ending: int
    regional_generation_mwh_proxy: float
    regional_installed_capacity_mw: float
    zone_wind_generation_mwh: float
    zone_installed_capacity_mw: float
    capacity_share_of_zone: float
    raw_capacity_factor: float
    capacity_factor: float
    normalized_generation_mwh_per_mw: float
    production_granularity: str
    mapping_source: str
    filled: bool
    fill_method: str


def ensure_terna_wind_raw_data(year: int = BASELINE_YEAR) -> dict[str, Path]:
    """Ensure required 2024 Terna raw CSV files exist, downloading if missing."""

    wind_path = TERNA_WIND_FORECAST_FILE
    capacity_path = TERNA_CAPACITY_FILE
    wind_path.parent.mkdir(parents=True, exist_ok=True)

    if not wind_path.exists():
        _write_rows(wind_path, _fetch_dataset(WIND_FORECAST_DATASET, year))
    if not capacity_path.exists():
        _write_rows(capacity_path, _fetch_dataset(CAPACITY_DATASET, year))
    return {"wind_forecast": wind_path, "capacity": capacity_path}


def load_capacity_by_region(path: Path = TERNA_CAPACITY_FILE) -> dict[str, float]:
    """Load regional installed gross wind capacity from Terna."""

    if not path.exists():
        raise FileNotFoundError(f"Missing Terna capacity file: {path}")

    capacity_by_region: dict[str, float] = defaultdict(float)
    for row in read_normalized_csv(path):
        if row.get("fonti") != "Eolico":
            continue
        if row.get("tipo capacita") != "Lorda":
            continue
        value = row.get("potenza efficiente (mw)", "")
        if not value:
            continue
        region = canonical_region(row["regione"])
        map_region_to_zone(region)
        capacity_by_region[region] += float(value)

    missing_regions = sorted(set(REGION_TO_ZONE) - set(capacity_by_region))
    if missing_regions:
        raise ValueError(f"Missing Terna wind capacity for regions: {missing_regions}")
    return dict(capacity_by_region)


def build_zonal_wind_capacity_factors(
    year: int = BASELINE_YEAR,
    market_slots: list[MarketSlot] | None = None,
) -> tuple[list[ZonalWindRecord], list[FillEvent], dict[str, float], dict[str, float]]:
    """Build complete hourly zonal wind capacity factors for 2024."""

    ensure_terna_wind_raw_data(year)
    capacity_by_region = load_capacity_by_region()
    capacity_by_zone: dict[str, float] = defaultdict(float)
    for region, capacity_mw in capacity_by_region.items():
        capacity_by_zone[map_region_to_zone(region)] += capacity_mw

    selected = _select_highest_session_wind_rows(TERNA_WIND_FORECAST_FILE)
    records: list[ZonalWindRecord] = []
    fill_events: list[FillEvent] = []

    for zone in sorted(capacity_by_zone):
        zone_values = {
            timestamp: payload
            for (record_zone, timestamp), payload in selected.items()
            if record_zone == zone
        }
        slots = market_slots or _default_market_slots(year)
        complete_values, zone_fill_events = _fill_market_slot_values(zone, zone_values, slots)
        fill_events.extend(zone_fill_events)
        capacity_mw = capacity_by_zone[zone]
        for slot, payload in complete_values:
            timestamp = _timestamp_from_slot(slot)
            wind_generation_mwh = payload["wind_generation_mwh"]
            raw_capacity_factor = wind_generation_mwh / capacity_mw
            capacity_factor = min(max(raw_capacity_factor, 0.0), 1.0)
            records.append(
                ZonalWindRecord(
                    year=year,
                    zone=zone,
                    row_index=slot.row_index,
                    timestamp=slot.timestamp,
                    date=slot.date,
                    day_of_year=slot.day_of_year,
                    hour_ending=slot.hour_ending,
                    wind_generation_mwh=wind_generation_mwh,
                    installed_capacity_mw=capacity_mw,
                    raw_capacity_factor=raw_capacity_factor,
                    capacity_factor=capacity_factor,
                    normalized_generation_mwh_per_mw=capacity_factor,
                    source_terna_zone=payload["source_terna_zone"],
                    source_session=payload["source_session"],
                    filled=payload["filled"],
                    fill_method=payload["fill_method"],
                    wind_data_source=WIND_SOURCE_LABEL,
                    capacity_data_source=CAPACITY_SOURCE_LABEL,
                )
            )

    _validate_zonal_records(records)
    return records, fill_events, capacity_by_region, dict(capacity_by_zone)


def build_regional_wind_capacity_factors(
    zonal_records: list[ZonalWindRecord],
    capacity_by_region: dict[str, float],
    capacity_by_zone: dict[str, float],
    mapping_source: str,
) -> list[RegionalWindRecord]:
    """Allocate zonal wind forecasts to regions by installed-capacity share."""

    records: list[RegionalWindRecord] = []
    zonal_by_zone = defaultdict(list)
    for record in zonal_records:
        zonal_by_zone[record.zone].append(record)

    for region in sorted(capacity_by_region):
        zone = map_region_to_zone(region)
        regional_capacity = capacity_by_region[region]
        zone_capacity = capacity_by_zone[zone]
        capacity_share = regional_capacity / zone_capacity if zone_capacity else 0.0
        for zonal in zonal_by_zone[zone]:
            regional_generation = zonal.wind_generation_mwh * capacity_share
            raw_capacity_factor = (
                regional_generation / regional_capacity if regional_capacity else 0.0
            )
            records.append(
                RegionalWindRecord(
                    year=zonal.year,
                    region=region,
                    zone=zone,
                    row_index=zonal.row_index,
                    timestamp=zonal.timestamp,
                    date=zonal.date,
                    day_of_year=zonal.day_of_year,
                    hour_ending=zonal.hour_ending,
                    regional_generation_mwh_proxy=regional_generation,
                    regional_installed_capacity_mw=regional_capacity,
                    zone_wind_generation_mwh=zonal.wind_generation_mwh,
                    zone_installed_capacity_mw=zone_capacity,
                    capacity_share_of_zone=capacity_share,
                    raw_capacity_factor=raw_capacity_factor,
                    capacity_factor=zonal.capacity_factor,
                    normalized_generation_mwh_per_mw=zonal.capacity_factor,
                    production_granularity=PRODUCTION_GRANULARITY,
                    mapping_source=mapping_source,
                    filled=zonal.filled,
                    fill_method=zonal.fill_method,
                )
            )
    return records


def _select_highest_session_wind_rows(
    path: Path,
) -> dict[tuple[str, datetime], dict[str, object]]:
    if not path.exists():
        raise FileNotFoundError(f"Missing Terna wind forecast file: {path}")

    selected: dict[tuple[str, datetime], dict[str, object]] = {}
    for row in read_normalized_csv(path):
        terna_zone = row.get("zone", "")
        if terna_zone == "Italy":
            continue
        zone = TERNA_ZONE_TO_ZONE.get(terna_zone)
        if zone is None:
            continue
        timestamp = _parse_terna_datetime(row["date"])
        session = row.get("session", "")
        priority = SESSION_PRIORITY.get(session, 0)
        value = float(row["wind forecast [mw]"])
        key = (zone, timestamp)
        previous = selected.get(key)
        if previous is None or priority >= int(previous["session_priority"]):
            selected[key] = {
                "session_priority": priority,
                "wind_generation_mwh": value,
                "source_terna_zone": terna_zone,
                "source_session": session,
                "filled": False,
                "fill_method": "source",
            }
    return selected


def _fill_market_slot_values(
    zone: str,
    values: dict[datetime, dict[str, object]],
    market_slots: list[MarketSlot],
) -> tuple[list[tuple[MarketSlot, dict[str, object]]], list[FillEvent]]:
    output: list[tuple[MarketSlot, dict[str, object]]] = []
    fill_events: list[FillEvent] = []

    for slot in market_slots:
        timestamp = _timestamp_from_slot(slot)
        if timestamp in values:
            output.append((slot, values[timestamp]))
            continue
        previous = _nearest_value(values, timestamp, -1)
        following = _nearest_value(values, timestamp, 1)
        if previous is not None and following is not None:
            wind_value = (
                float(previous["wind_generation_mwh"])
                + float(following["wind_generation_mwh"])
            ) / 2
            method = "adjacent_hour_interpolation"
        elif previous is not None:
            wind_value = float(previous["wind_generation_mwh"])
            method = "previous_hour_fill"
        elif following is not None:
            wind_value = float(following["wind_generation_mwh"])
            method = "next_hour_fill"
        else:
            raise ValueError(f"No Terna wind values available for {zone} in {year}")
        payload = {
            "session_priority": 0,
            "wind_generation_mwh": wind_value,
            "source_terna_zone": zone,
            "source_session": "filled",
            "filled": True,
            "fill_method": method,
        }
        output.append((slot, payload))
        fill_events.append(
            FillEvent(
                year=BASELINE_YEAR,
                zone=zone,
                timestamp=slot.timestamp,
                fill_method=method,
            )
        )
    return output, fill_events


def _default_market_slots(year: int) -> list[MarketSlot]:
    start = datetime(year, 1, 1)
    slots: list[MarketSlot] = []
    for index in range(EXPECTED_HOURS_2024):
        timestamp = start + timedelta(hours=index)
        slots.append(
            MarketSlot(
                row_index=index + 1,
                timestamp=timestamp.isoformat(sep=" "),
                date=timestamp.date().isoformat(),
                day_of_year=timestamp.timetuple().tm_yday,
                hour_ending=timestamp.hour + 1,
            )
        )
    return slots


def _timestamp_from_slot(slot: MarketSlot) -> datetime:
    return datetime.fromisoformat(slot.timestamp)


def _nearest_value(
    values: dict[datetime, dict[str, object]],
    timestamp: datetime,
    direction: int,
) -> dict[str, object] | None:
    cursor = timestamp + timedelta(hours=direction)
    while abs((cursor - timestamp).total_seconds()) <= 48 * 3600:
        if cursor in values:
            return values[cursor]
        cursor += timedelta(hours=direction)
    return None


def _validate_zonal_records(records: list[ZonalWindRecord]) -> None:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.zone] = counts.get(record.zone, 0) + 1
        if record.capacity_factor < 0 or record.capacity_factor > 1:
            raise ValueError(f"Capacity factor outside [0, 1]: {record}")
    for zone, count in counts.items():
        if count != EXPECTED_HOURS_2024:
            raise ValueError(
                f"Unexpected Terna wind row count for {zone}: "
                f"{count}, expected {EXPECTED_HOURS_2024}"
            )


def _parse_terna_datetime(value: object) -> datetime:
    return datetime(1, 1, 1) + timedelta(milliseconds=int(float(value)))


def read_normalized_csv(path: Path) -> list[dict[str, str]]:
    """Read a CSV and normalize its header names for source adapters."""
    with path.open("r", newline="", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        return [
            {_normalize_key(key): value for key, value in row.items()}
            for row in reader
        ]


def _normalize_key(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_text = normalized.encode("ascii", "ignore").decode("ascii")
    return " ".join(ascii_text.strip().lower().split())


def _fetch_dataset(dataset: str, year: int) -> list[dict[str, object]]:
    page_size = 5000
    first = _request_page(dataset, year, page_size, 0)
    rows = _normalize_response_rows(first)
    count = int(first.get("Count", len(rows)))
    page_count = (count + page_size - 1) // page_size
    for page in range(1, page_count):
        rows.extend(_normalize_response_rows(_request_page(dataset, year, page_size, page)))
    return rows


def _request_page(dataset: str, year: int, page_size: int, page_index: int) -> dict[str, object]:
    payload = {
        "filterDataset": dataset,
        "filterYear": str(year),
        "pageSize": str(page_size),
        "pageIndex": str(page_index),
        "db": "dati",
    }
    if dataset == CAPACITY_DATASET:
        payload["orderByColumn"] = "Anno"
        payload["orderByDir"] = "desc"
    request = Request(
        TERNA_ENDPOINT,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "Mozilla/5.0"},
        method="POST",
    )
    with urlopen(request, timeout=90) as response:
        return json.loads(response.read().decode("utf-8"))


def _normalize_response_rows(response: dict[str, object]) -> list[dict[str, object]]:
    columns = list((response.get("Columns") or {}).keys())  # type: ignore[union-attr]
    rows = []
    for row in response.get("Data") or []:  # type: ignore[union-attr]
        values = row.get("value", row) if isinstance(row, dict) else row
        rows.append(dict(zip(columns, values, strict=True)))
    return rows


def _write_rows(path: Path, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise ValueError(f"No rows to write for {path}")
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)
