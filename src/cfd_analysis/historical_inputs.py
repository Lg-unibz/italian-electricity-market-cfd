"""Historical inputs for the 2015-2024 Italian CfD backtest.

The module keeps the hourly wind resource homogeneous: Copernicus/ERA5 is the
only source used for hourly capacity factors. Terna annual data are used only
for capacity weights and validation against observed annual MWh/MW.
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from pathlib import Path

import pandas as pd

from market_preprocessing.config import RAW_TERNA_DIR, RAW_XLSX_DIR
from market_preprocessing.mapping import REGION_TO_ZONE, canonical_region
from market_preprocessing.terna_wind import read_normalized_csv
from market_preprocessing.xlsx_io import read_sheet_rows


HISTORICAL_YEARS = tuple(range(2015, 2025))
COPERNICUS_ONSHORE_TECHNOLOGIES = (
    "ic2_5hh100",
    "ic2_5hh100e",
    "ic3_3hh84",
    "ic6hh135",
    "ic6hh135e",
)
COPERNICUS_WIND_FILE = (
    Path(__file__).resolve().parents[2]
    / "data"
    / "raw"
    / "copernicus"
    / "onshore_wind_capacity_factor_adm1_2015_2024.csv"
)

# Eurostat prc_hicp_aind, IT, CP00, INX_A_AVG, retrieved 2026-07-13.
# The 2024 index is the common real-price base. DOI: 10.2908/PRC_HICP_AIND.
ITALY_HICP_ANNUAL_AVERAGE = {
    2015: 100.0,
    2016: 99.9,
    2017: 101.3,
    2018: 102.5,
    2019: 103.2,
    2020: 103.0,
    2021: 105.0,
    2022: 114.2,
    2023: 120.9,
    2024: 122.3,
}

COPERNICUS_REGION_ALIASES = {
    "Piedmont": "Piemonte",
    "Aosta Valley": "Valle d'Aosta",
    "Valle D'Aosta": "Valle d'Aosta",
    "Lombardy": "Lombardia",
    "Trentino-South Tyrol": "Trentino-Alto Adige",
    "Trentino Alto Adige": "Trentino-Alto Adige",
    "Friuli Venezia Giulia": "Friuli-Venezia Giulia",
    "Emilia Romagna": "Emilia-Romagna",
    "Tuscany": "Toscana",
    "The Marches": "Marche",
    "Latium": "Lazio",
    "Apulia": "Puglia",
    "Sicily": "Sicilia",
    "Sardinia": "Sardegna",
}


def map_region_to_zone_for_year(region: str, year: int) -> str:
    """Map an Italian region to the bidding-zone configuration valid that year.

    Terna's 2021 revision moved Umbria from Centro Nord to Centro Sud and
    Calabria from Sud to the new Calabria zone. Other region-zone assignments
    remain unchanged over the study period.
    """

    canonical = canonicalize_region(region)
    if canonical not in REGION_TO_ZONE:
        raise ValueError(f"Region not mapped to a GME bidding zone: {region}")
    if year < 2021 and canonical == "Umbria":
        return "Centro Nord"
    if year < 2021 and canonical == "Calabria":
        return "Sud"
    return REGION_TO_ZONE[canonical]


def canonicalize_region(region: str) -> str:
    """Normalize Italian and English ADM1 labels to repository region names."""

    cleaned = " ".join(str(region).strip().split())
    cleaned = COPERNICUS_REGION_ALIASES.get(cleaned, cleaned)
    return canonical_region(cleaned)


def load_gme_hourly_prices(
    years: tuple[int, ...] = HISTORICAL_YEARS,
    raw_dir: Path = RAW_XLSX_DIR,
) -> pd.DataFrame:
    """Load GME hourly zonal prices and express them in real 2024 EUR/MWh."""

    frames: list[pd.DataFrame] = []
    for year in years:
        path = raw_dir / f"{year}0101_{year}1231_MGP_PrezziZonali.xlsx"
        if not path.exists():
            raise FileNotFoundError(f"Missing GME zonal-price workbook: {path}")
        rows = read_sheet_rows(path)
        if not rows:
            raise ValueError(f"Empty GME zonal-price workbook: {path}")
        headers = [str(value).strip() if value is not None else "" for value in rows[0]]
        header_index = {header: index for index, header in enumerate(headers)}
        active_zones = sorted(
            {map_region_to_zone_for_year(region, year) for region in REGION_TO_ZONE}
        )
        required = {"Data", "Ora", *active_zones}
        missing = sorted(required - set(header_index))
        if missing:
            raise ValueError(f"Missing GME columns in {path.name}: {missing}")

        market_rows = [
            row
            for row in rows[1:]
            if _cell(row, header_index["Data"]) is not None
            and _cell(row, header_index["Ora"]) is not None
        ]
        slots = local_delivery_slots(year)
        if len(market_rows) != len(slots):
            raise ValueError(
                f"Unexpected GME rows for {year}: {len(market_rows)}, "
                f"expected {len(slots)} from Europe/Rome delivery hours"
            )

        source_dates = [
            datetime.strptime(str(_cell(row, header_index["Data"])), "%d/%m/%Y").date()
            for row in market_rows
        ]
        delivery_dates = [
            timestamp.tz_convert("Europe/Rome").date()
            for timestamp in slots["timestamp_utc"]
        ]
        if source_dates != delivery_dates:
            first = next(
                index
                for index, (source, delivery) in enumerate(
                    zip(source_dates, delivery_dates, strict=True),
                    start=1,
                )
                if source != delivery
            )
            raise ValueError(
                f"GME delivery-date sequence mismatch in {path.name}, row {first}"
            )

        nominal_to_real = ITALY_HICP_ANNUAL_AVERAGE[2024] / ITALY_HICP_ANNUAL_AVERAGE[year]
        values: list[dict[str, object]] = []
        for slot, row in zip(slots.itertuples(index=False), market_rows, strict=True):
            for zone in active_zones:
                raw_price = _cell(row, header_index[zone])
                if raw_price is None:
                    raise ValueError(f"Missing {zone} price in {path.name}, row {slot.slot_index}")
                nominal_price = _parse_number(raw_price)
                values.append(
                    {
                        "year": year,
                        "timestamp_utc": slot.timestamp_utc,
                        "slot_index": slot.slot_index,
                        "zone": zone,
                        "price_nominal_eur_per_mwh": nominal_price,
                        "hicp_2024_factor": nominal_to_real,
                        "price_real_2024_eur_per_mwh": nominal_price * nominal_to_real,
                        "gme_source_file": path.name,
                    }
                )
        frames.append(pd.DataFrame(values))
    output = pd.concat(frames, ignore_index=True)
    if output.duplicated(["timestamp_utc", "zone"]).any():
        raise ValueError("Duplicate GME timestamp-zone observations")
    return output


def local_delivery_slots(year: int) -> pd.DataFrame:
    """Return the UTC starts of all Europe/Rome market delivery hours."""

    local = pd.date_range(
        start=f"{year}-01-01 00:00",
        end=f"{year + 1}-01-01 00:00",
        inclusive="left",
        freq="h",
        tz="Europe/Rome",
    )
    utc = local.tz_convert("UTC")
    return pd.DataFrame(
        {
            "year": year,
            "slot_index": range(1, len(utc) + 1),
            "timestamp_utc": utc,
        }
    )


def load_copernicus_hourly_wind(
    path: Path = COPERNICUS_WIND_FILE,
    years: tuple[int, ...] = HISTORICAL_YEARS,
) -> pd.DataFrame:
    """Load normalized Copernicus ADM1 hourly onshore capacity factors.

    The canonical CSV is long-form with columns ``timestamp_utc``, ``region``,
    ``technology`` and ``capacity_factor``. A wide file is also accepted when
    technology columns start with ``capacity_factor_`` or ``cf_``.
    """

    if not path.exists():
        raise FileNotFoundError(
            "Missing homogeneous Copernicus hourly wind input: "
            f"{path}. Provide the CDS ADM1 hourly onshore-wind export in the "
            "canonical format documented in README.md; no Terna hourly fallback "
            "is used for the historical backtest."
        )
    aliases = {
        "time": "timestamp_utc",
        "timestamp": "timestamp_utc",
        "valid_time": "timestamp_utc",
        "datetime": "timestamp_utc",
        "adm1": "region",
        "adm1_name": "region",
        "admin_name": "region",
        "name_1": "region",
        "turbine": "technology",
        "turbine_type": "technology",
        "technology_code": "technology",
        "cf": "capacity_factor",
        "wind_capacity_factor": "capacity_factor",
    }
    required = ["timestamp_utc", "region", "technology", "capacity_factor"]
    chunks: list[pd.DataFrame] = []
    for frame in pd.read_csv(path, chunksize=500_000):
        frame.columns = [_normalized_column(column) for column in frame.columns]
        frame = frame.rename(
            columns={key: value for key, value in aliases.items() if key in frame}
        )
        if "capacity_factor" not in frame:
            id_columns = [
                column for column in ("timestamp_utc", "region") if column in frame
            ]
            value_columns = [
                column
                for column in frame
                if column.startswith("capacity_factor_") or column.startswith("cf_")
            ]
            if len(id_columns) != 2 or not value_columns:
                raise ValueError(
                    "Copernicus CSV must contain timestamp_utc, region, technology, "
                    "capacity_factor, or wide capacity_factor_<technology> columns"
                )
            frame = frame.melt(
                id_vars=id_columns,
                value_vars=value_columns,
                var_name="technology",
                value_name="capacity_factor",
            )
            frame["technology"] = frame["technology"].str.replace(
                r"^(capacity_factor_|cf_)", "", regex=True
            )
        missing = sorted(set(required) - set(frame.columns))
        if missing:
            raise ValueError(f"Missing Copernicus columns: {missing}")
        chunks.append(frame[required].copy())
    if not chunks:
        raise ValueError(f"Empty Copernicus hourly wind CSV: {path}")
    output = pd.concat(chunks, ignore_index=True)
    output["timestamp_utc"] = pd.to_datetime(output["timestamp_utc"], utc=True, errors="raise")
    output["region"] = output["region"].map(canonicalize_region)
    output["technology"] = (
        output["technology"]
        .astype(str)
        .str.strip()
        .str.lower()
        .str.replace(".", "_", regex=False)
    )
    output["capacity_factor"] = pd.to_numeric(
        output["capacity_factor"], errors="raise", downcast="float"
    )
    output["delivery_year"] = output["timestamp_utc"].dt.tz_convert("Europe/Rome").dt.year
    output = output[output["delivery_year"].isin(years)].drop(columns="delivery_year")

    unknown_regions = sorted(set(output["region"]) - set(REGION_TO_ZONE))
    if unknown_regions:
        raise ValueError(f"Unknown Copernicus ADM1 regions: {unknown_regions}")
    observed_regions = set(output["region"])
    missing_regions = sorted(set(REGION_TO_ZONE) - observed_regions)
    if missing_regions:
        raise ValueError(f"Missing Copernicus regions: {missing_regions}")
    if output["capacity_factor"].isna().any():
        raise ValueError("Missing Copernicus capacity-factor values")
    technologies = set(output["technology"].unique())
    expected_technologies = set(COPERNICUS_ONSHORE_TECHNOLOGIES)
    if technologies != expected_technologies:
        raise ValueError(
            "The national selection must compare all five Copernicus onshore "
            "technical specifications (three turbine designs, including the "
            "alternative wind-input variants); "
            f"missing={sorted(expected_technologies - technologies)}, "
            f"extra={sorted(technologies - expected_technologies)}"
        )
    outside = output.loc[~output["capacity_factor"].between(0, 1)]
    if not outside.empty:
        raise ValueError(
            "Copernicus capacity factors outside [0, 1]; first rows: "
            f"{outside.head().to_dict(orient='records')}"
        )
    keys = ["timestamp_utc", "region", "technology"]
    if output.duplicated(keys).any():
        raise ValueError("Duplicate Copernicus timestamp-region-technology observations")
    _validate_copernicus_hour_coverage(output, years)
    output["region"] = output["region"].astype("category")
    output["technology"] = output["technology"].astype("category")
    return output.sort_values(keys).reset_index(drop=True)


def load_terna_annual_wind(
    years: tuple[int, ...] = HISTORICAL_YEARS,
    raw_dir: Path = RAW_TERNA_DIR,
) -> pd.DataFrame:
    """Load annual gross wind capacity and production by Italian region."""

    rows: list[dict[str, object]] = []
    for year in years:
        capacity_path = raw_dir / f"terna_capacity_renewable_sources_{year}.csv"
        production_path = raw_dir / f"terna_production_renewable_sources_{year}.csv"
        if not capacity_path.exists() or not production_path.exists():
            raise FileNotFoundError(
                f"Missing Terna annual wind input for {year}: "
                f"{capacity_path.name} / {production_path.name}"
            )
        capacity: dict[str, float] = defaultdict(float)
        for row in read_normalized_csv(capacity_path):
            if row.get("fonti") != "Eolico" or row.get("tipo capacita") != "Lorda":
                continue
            value = row.get("potenza efficiente (mw)", "")
            if value:
                capacity[canonicalize_region(row["regione"])] += float(value)
        production: dict[str, float] = defaultdict(float)
        for row in read_normalized_csv(production_path):
            if row.get("fonte rinnovabile") != "Eolico" or row.get("tipo produzione") != "Lorda":
                continue
            value = row.get("produzione (gwh)", "")
            if value:
                production[canonicalize_region(row["regione"])] += float(value) * 1_000
        for region in REGION_TO_ZONE:
            capacity_mw = capacity.get(region, 0.0)
            production_mwh = production.get(region, 0.0)
            rows.append(
                {
                    "year": year,
                    "region": region,
                    "zone": map_region_to_zone_for_year(region, year),
                    "installed_capacity_mw": capacity_mw,
                    "observed_generation_mwh": production_mwh,
                    "observed_mwh_per_mw": (
                        production_mwh / capacity_mw if capacity_mw > 0 else pd.NA
                    ),
                }
            )
    output = pd.DataFrame(rows)
    if len(output) != len(years) * len(REGION_TO_ZONE):
        raise ValueError("Terna annual panel is not a complete year-region grid")
    return output


def select_copernicus_technology(
    wind: pd.DataFrame,
    terna: pd.DataFrame,
) -> tuple[str, pd.DataFrame, pd.DataFrame]:
    """Select one national technology by decade annual MWh/MW validation MAE."""

    hourly = wind.copy()
    hourly["year"] = hourly["timestamp_utc"].dt.tz_convert("Europe/Rome").dt.year
    annual_region = (
        hourly.groupby(
            ["technology", "year", "region"],
            as_index=False,
            observed=True,
        )
        .agg(copernicus_mwh_per_mw=("capacity_factor", "sum"))
    )
    comparison = annual_region.merge(
        terna[
            [
                "year",
                "region",
                "installed_capacity_mw",
                "observed_generation_mwh",
            ]
        ],
        on=["year", "region"],
        how="left",
        validate="many_to_one",
    )
    comparison["modelled_generation_mwh"] = (
        comparison["copernicus_mwh_per_mw"] * comparison["installed_capacity_mw"]
    )
    national = (
        comparison.groupby(["technology", "year"], as_index=False, observed=True)
        .agg(
            modelled_generation_mwh=("modelled_generation_mwh", "sum"),
            observed_generation_mwh=("observed_generation_mwh", "sum"),
            installed_capacity_mw=("installed_capacity_mw", "sum"),
        )
    )
    national["copernicus_mwh_per_mw"] = (
        national["modelled_generation_mwh"] / national["installed_capacity_mw"]
    )
    national["terna_mwh_per_mw"] = (
        national["observed_generation_mwh"] / national["installed_capacity_mw"]
    )
    national["error_mwh_per_mw"] = (
        national["copernicus_mwh_per_mw"] - national["terna_mwh_per_mw"]
    )
    diagnostics = (
        national.groupby("technology", as_index=False, observed=True)
        .agg(
            mean_absolute_error_mwh_per_mw=(
                "error_mwh_per_mw",
                lambda values: values.abs().mean(),
            ),
            mean_bias_mwh_per_mw=("error_mwh_per_mw", "mean"),
            compared_years=("year", "nunique"),
        )
        .sort_values(["mean_absolute_error_mwh_per_mw", "technology"])
        .reset_index(drop=True)
    )
    if diagnostics.empty:
        raise ValueError("No Copernicus technology could be validated")
    selected = str(diagnostics.iloc[0]["technology"])
    diagnostics["selected_national_technology"] = diagnostics["technology"].eq(selected)
    return selected, diagnostics, national.sort_values(["technology", "year"])


def inflation_audit_table(years: tuple[int, ...] = HISTORICAL_YEARS) -> pd.DataFrame:
    """Return the HICP indices and nominal-to-real-2024 conversion factors."""

    return pd.DataFrame(
        [
            {
                "year": year,
                "italy_all_items_hicp_annual_average": ITALY_HICP_ANNUAL_AVERAGE[year],
                "nominal_to_real_2024_factor": (
                    ITALY_HICP_ANNUAL_AVERAGE[2024] / ITALY_HICP_ANNUAL_AVERAGE[year]
                ),
                "source": "Eurostat prc_hicp_aind, IT, CP00, INX_A_AVG",
                "source_doi": "10.2908/PRC_HICP_AIND",
            }
            for year in years
        ]
    )


def _validate_copernicus_hour_coverage(
    wind: pd.DataFrame,
    years: tuple[int, ...],
) -> None:
    expected = {year: len(local_delivery_slots(year)) for year in years}
    local_year = wind["timestamp_utc"].dt.tz_convert("Europe/Rome").dt.year
    counts = (
        wind.assign(year=local_year)
        .groupby(["technology", "region", "year"])
        .size()
    )
    failures: list[str] = []
    for technology in sorted(wind["technology"].unique()):
        for region in REGION_TO_ZONE:
            for year in years:
                count = int(counts.get((technology, region, year), 0))
                if count != expected[year]:
                    failures.append(f"{technology}/{region}/{year}: {count} != {expected[year]}")
    if failures:
        raise ValueError(
            "Incomplete Copernicus Europe/Rome delivery-hour coverage. The input "
            "must include the UTC boundary hours around 2015-2024. First failures: "
            + "; ".join(failures[:10])
        )


def _cell(row: list[str | None], index: int) -> str | None:
    if index >= len(row) or row[index] is None:
        return None
    value = str(row[index]).strip()
    return value or None


def _parse_number(value: str) -> float:
    text = str(value).strip()
    if "," in text:
        text = text.replace(".", "").replace(",", ".")
    return float(text)


def _normalized_column(value: object) -> str:
    return "_".join(str(value).strip().lower().replace("-", " ").split())
