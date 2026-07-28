"""Load and normalize 2024 GME zonal price data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .config import BASELINE_YEAR, EXPECTED_HOURS_2024, GME_PRICE_FILE, ZONES
from .xlsx_io import read_sheet_rows


@dataclass(frozen=True)
class PriceRecord:
    """One hourly GME zonal price observation.

    Units:
        price_eur_mwh is EUR/MWh.
    """

    year: int
    zone: str
    row_index: int
    timestamp: str
    date: str
    day_of_year: int
    hour_ending: int
    price_eur_mwh: float
    source_file: str


def load_gme_zonal_prices_2024(path: Path = GME_PRICE_FILE) -> list[PriceRecord]:
    """Read the 2024 GME MGP zonal price workbook."""

    if not path.exists():
        raise FileNotFoundError(f"Missing GME price workbook: {path}")

    rows = read_sheet_rows(path)
    if not rows:
        raise ValueError(f"Empty GME price workbook: {path}")
    headers = [str(value).strip() if value is not None else "" for value in rows[0]]
    header_index = {header: index for index, header in enumerate(headers)}
    date_index = header_index["Data"]
    hour_index = header_index["Ora"]

    records: list[PriceRecord] = []
    for row_index, row in enumerate(rows[1:], start=1):
        date_text = _cell(row, date_index)
        hour_text = _cell(row, hour_index)
        if date_text is None or hour_text is None:
            continue
        parsed_date = datetime.strptime(date_text, "%d/%m/%Y")
        hour_ending = int(float(hour_text))
        timestamp = parsed_date + timedelta(hours=hour_ending - 1)
        for zone_config in ZONES:
            zone_index = header_index.get(zone_config.gme_header)
            if zone_index is None:
                raise ValueError(f"Missing GME header {zone_config.gme_header!r}")
            raw_price = _cell(row, zone_index)
            if raw_price is None:
                raise ValueError(
                    f"Missing GME price for {zone_config.zone}, row {row_index}"
                )
            records.append(
                PriceRecord(
                    year=BASELINE_YEAR,
                    zone=zone_config.zone,
                    row_index=row_index,
                    timestamp=timestamp.isoformat(sep=" "),
                    date=parsed_date.date().isoformat(),
                    day_of_year=parsed_date.timetuple().tm_yday,
                    hour_ending=hour_ending,
                    price_eur_mwh=_parse_number(raw_price),
                    source_file=path.name,
                )
            )

    _validate_price_counts(records)
    return records


def _validate_price_counts(records: list[PriceRecord]) -> None:
    counts: dict[str, int] = {}
    for record in records:
        counts[record.zone] = counts.get(record.zone, 0) + 1
    for zone_config in ZONES:
        count = counts.get(zone_config.zone, 0)
        if count != EXPECTED_HOURS_2024:
            raise ValueError(
                f"Unexpected GME row count for {zone_config.zone}: "
                f"{count}, expected {EXPECTED_HOURS_2024}"
            )


def _cell(row: list[str | None], index: int) -> str | None:
    if index >= len(row):
        return None
    value = row[index]
    if value is None:
        return None
    stripped = str(value).strip()
    return stripped if stripped else None


def _parse_number(value: str) -> float:
    text = str(value).strip()
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    return float(text)
