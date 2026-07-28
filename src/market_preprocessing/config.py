"""Project configuration for the 2024 preprocessing baseline."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = ROOT_DIR / "data"
RAW_DIR = DATA_DIR / "raw"
RAW_XLSX_DIR = RAW_DIR / "xlsx"
RAW_TERNA_DIR = RAW_DIR / "terna"
PROCESSED_DIR = DATA_DIR / "processed"
PROCESSED_FIGURES_DIR = PROCESSED_DIR / "figures"
PREPROCESSING_FIGURES_DIR = PROCESSED_FIGURES_DIR / "preprocessing"
RESULTS_DIR = ROOT_DIR / "results"
FIGURES_DIR = RESULTS_DIR / "figures"
TABLES_DIR = RESULTS_DIR / "tables"

BASELINE_YEAR = 2024
EXPECTED_HOURS_2024 = 8784
GME_PRICE_FILE = RAW_XLSX_DIR / "20240101_20241231_MGP_PrezziZonali.xlsx"
TERNA_WIND_FORECAST_FILE = RAW_TERNA_DIR / "terna_wind_production_forecast_2024.csv"
TERNA_CAPACITY_FILE = RAW_TERNA_DIR / "terna_capacity_renewable_sources_2024.csv"

WIND_FORECAST_DATASET = "WindProductionForecast"
CAPACITY_DATASET = "CapacityRenewableSources"
TERNA_ENDPOINT = "https://dati.terna.it/api/sitecore/dati/downloadcenter/recordsv2"


@dataclass(frozen=True)
class ZoneConfig:
    """GME and Terna labels for one Italian bidding zone."""

    zone: str
    gme_header: str
    terna_zone: str
    slug: str


ZONES: tuple[ZoneConfig, ...] = (
    ZoneConfig("Nord", "Nord", "North", "nord"),
    ZoneConfig("Centro Nord", "Centro Nord", "Centre-North", "centro_nord"),
    ZoneConfig("Centro Sud", "Centro Sud", "Centre-South", "centro_sud"),
    ZoneConfig("Sud", "Sud", "South", "sud"),
    ZoneConfig("Calabria", "Calabria", "Calabria", "calabria"),
    ZoneConfig("Sardegna", "Sardegna", "Sardinia", "sardegna"),
    ZoneConfig("Sicilia", "Sicilia", "Sicily", "sicilia"),
)

ZONE_ORDER = tuple(config.zone for config in ZONES)
GME_HEADER_TO_ZONE = {config.gme_header: config.zone for config in ZONES}
TERNA_ZONE_TO_ZONE = {config.terna_zone: config.zone for config in ZONES}
ZONE_TO_SLUG = {config.zone: config.slug for config in ZONES}

SESSION_PRIORITY = {f"MSD{index}": index for index in range(1, 7)}
MAPPING_SOURCE = "Sapio (2015, 2019), interpreted as Italian bidding-zone geography"
PRODUCTION_GRANULARITY = "zonal_forecast_capacity_share_proxy"


def ensure_output_dirs() -> None:
    """Create local output folders used by the preprocessing pipeline."""

    for path in (
        RAW_TERNA_DIR,
        PROCESSED_DIR,
        PREPROCESSING_FIGURES_DIR,
    ):
        path.mkdir(parents=True, exist_ok=True)
