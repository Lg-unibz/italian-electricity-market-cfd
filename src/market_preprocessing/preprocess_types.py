"""Shared dataclasses for preprocessing outputs."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MarketSlot:
    """One GME market-calendar row used to align prices and wind data."""

    row_index: int
    timestamp: str
    date: str
    day_of_year: int
    hour_ending: int


@dataclass(frozen=True)
class PreprocessingPanelRecord:
    """Joined 2024 hourly price, capacity factor and simple revenue record."""

    year: int
    zone: str
    row_index: int
    timestamp: str
    date: str
    day_of_year: int
    hour_ending: int
    price_eur_mwh: float
    capacity_factor: float
    normalized_generation_mwh_per_mw: float
    simple_market_revenue_eur_per_mw_hour: float
    wind_generation_mwh: float
    installed_capacity_mw: float
    price_source_file: str
    wind_data_source: str
    capacity_data_source: str


@dataclass(frozen=True)
class ZoneMarketValueSummary:
    """Annual zonal decomposition of wind market value per MW."""

    year: int
    zone: str
    installed_capacity_mw: float
    full_load_hours_mwh_per_mw_year: float
    mean_capacity_factor: float
    mean_zonal_price_eur_mwh: float
    capture_price_eur_mwh: float
    capture_discount_pct: float
    annual_market_revenue_eur_per_mw: float
