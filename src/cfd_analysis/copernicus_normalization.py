"""Normalize coded Copernicus ADM1 wind series to Italian regions."""

from __future__ import annotations

from pathlib import Path
from typing import BinaryIO

import numpy as np
import pandas as pd
from pyproj import Geod

from market_preprocessing.mapping import REGION_TO_ZONE

from .geography import _read_dbf, _read_polygon_shapefile
from .historical_inputs import canonicalize_region


EXPECTED_ITALIAN_ADMIN1_UNITS = 110
_WGS84_GEOD = Geod(ellps="WGS84")
_TIME_COLUMN_NAMES = (
    "timestamp_utc",
    "time",
    "timestamp",
    "valid_time",
    "datetime",
    "date",
)


def load_natural_earth_admin1_weights(shp_path: Path) -> pd.DataFrame:
    """Build geodesic area weights for Italian Natural Earth ADM1 units."""

    dbf_path = shp_path.with_suffix(".dbf")
    if not shp_path.exists() or not dbf_path.exists():
        raise FileNotFoundError(
            f"Natural Earth ADM1 SHP/DBF not found: {shp_path} / {dbf_path}"
        )
    polygons = _read_polygon_shapefile(shp_path)
    attributes = _read_dbf(dbf_path)
    if len(polygons) != len(attributes):
        raise ValueError("Natural Earth SHP/DBF record count mismatch")

    rows: list[dict[str, object]] = []
    for rings, attributes_row in zip(polygons, attributes, strict=True):
        if _clean_text(attributes_row.get("adm0_a3", "")) != "ITA":
            continue
        admin1_code = _clean_text(attributes_row.get("adm1_code", ""))
        province = _clean_text(attributes_row.get("name", ""))
        region = canonicalize_region(_clean_text(attributes_row.get("region", "")))
        area_sq_km = _geodesic_area_sq_km(rings)
        rows.append(
            {
                "admin1_code": admin1_code,
                "province": province,
                "region": region,
                "geodesic_area_sq_km": area_sq_km,
            }
        )
    weights = pd.DataFrame(rows)
    validate_admin1_weights(weights, require_weights=False)
    region_area = weights.groupby("region")["geodesic_area_sq_km"].transform("sum")
    weights["regional_area_weight"] = weights["geodesic_area_sq_km"] / region_area
    validate_admin1_weights(weights, require_weights=True)
    return weights.sort_values(["region", "admin1_code"]).reset_index(drop=True)


def validate_admin1_weights(
    weights: pd.DataFrame,
    *,
    require_weights: bool = True,
) -> None:
    """Validate the exact 110-unit to 20-region Natural Earth mapping."""

    required = {"admin1_code", "region", "geodesic_area_sq_km"}
    if require_weights:
        required.add("regional_area_weight")
    missing_columns = sorted(required - set(weights.columns))
    if missing_columns:
        raise ValueError(f"Missing Natural Earth weight columns: {missing_columns}")
    if len(weights) != EXPECTED_ITALIAN_ADMIN1_UNITS:
        raise ValueError(
            "Natural Earth mapping must contain exactly "
            f"{EXPECTED_ITALIAN_ADMIN1_UNITS} Italian units, found {len(weights)}"
        )
    if weights["admin1_code"].duplicated().any():
        raise ValueError("Duplicate Natural Earth ADM1 codes")
    observed_regions = set(weights["region"])
    expected_regions = set(REGION_TO_ZONE)
    if observed_regions != expected_regions:
        raise ValueError(
            "Natural Earth mapping must cover exactly 20 Italian regions; "
            f"missing={sorted(expected_regions - observed_regions)}, "
            f"extra={sorted(observed_regions - expected_regions)}"
        )
    if (pd.to_numeric(weights["geodesic_area_sq_km"], errors="raise") <= 0).any():
        raise ValueError("Natural Earth ADM1 geodesic areas must be positive")
    if require_weights:
        sums = weights.groupby("region")["regional_area_weight"].sum()
        if not np.allclose(sums.to_numpy(dtype=float), 1.0, atol=1e-10):
            raise ValueError("Natural Earth regional area weights do not sum to one")


def normalize_cds_admin1_csv(
    source: BinaryIO,
    source_name: str,
    technology: str,
    weights: pd.DataFrame,
) -> pd.DataFrame:
    """Read one coded global CDS CSV and aggregate Italian units to regions."""

    codes = set(weights["admin1_code"])
    frame = pd.read_csv(
        source,
        comment="#",
        usecols=lambda column: str(column).strip() in codes
        or str(column).strip().lower() in _TIME_COLUMN_NAMES,
    )
    if frame.empty:
        raise ValueError(f"Empty CDS CSV member: {source_name}")
    frame.columns = [str(column).strip() for column in frame.columns]
    time_column = next(
        (column for column in frame if column.lower() in _TIME_COLUMN_NAMES),
        None,
    )
    if time_column is None:
        raise ValueError(f"No timestamp column in CDS CSV member: {source_name}")
    observed_codes = set(frame.columns) - {time_column}
    if observed_codes != codes:
        raise ValueError(
            f"Incomplete Italian ADM1 columns in {source_name}; "
            f"missing={sorted(codes - observed_codes)}, "
            f"extra={sorted(observed_codes - codes)}"
        )
    return aggregate_cds_admin1_frame(frame, time_column, technology, weights)


def aggregate_cds_admin1_frame(
    frame: pd.DataFrame,
    time_column: str,
    technology: str,
    weights: pd.DataFrame,
) -> pd.DataFrame:
    """Area-weight coded ADM1 columns into 20 regional hourly series."""

    ordered = weights.sort_values("admin1_code").reset_index(drop=True)
    codes = ordered["admin1_code"].tolist()
    missing = sorted(set(codes) - set(frame.columns))
    if missing:
        raise ValueError(f"Missing coded ADM1 columns: {missing}")
    values = frame[codes].apply(pd.to_numeric, errors="raise").to_numpy(dtype=np.float64)
    if not np.isfinite(values).all():
        raise ValueError("Missing or non-finite Copernicus ADM1 capacity factors")
    if np.any((values < 0) | (values > 1)):
        raise ValueError("Copernicus ADM1 capacity factors outside [0, 1]")

    regions = list(REGION_TO_ZONE)
    matrix = np.zeros((len(ordered), len(regions)), dtype=np.float64)
    region_index = {region: index for index, region in enumerate(regions)}
    for unit_index, row in enumerate(ordered.itertuples(index=False)):
        matrix[unit_index, region_index[row.region]] = float(row.regional_area_weight)
    regional_values = values @ matrix
    wide = pd.DataFrame(regional_values, columns=regions)
    wide.insert(
        0,
        "timestamp_utc",
        pd.to_datetime(frame[time_column], utc=True, errors="raise"),
    )
    output = wide.melt(
        id_vars="timestamp_utc",
        var_name="region",
        value_name="capacity_factor",
    )
    output["technology"] = technology
    return output[
        ["timestamp_utc", "region", "technology", "capacity_factor"]
    ]


def _geodesic_area_sq_km(
    rings: tuple[tuple[tuple[float, float], ...], ...],
) -> float:
    signed_area_sq_m = 0.0
    for ring in rings:
        if len(ring) < 3:
            continue
        longitudes, latitudes = zip(*ring, strict=True)
        area_sq_m, _ = _WGS84_GEOD.polygon_area_perimeter(longitudes, latitudes)
        signed_area_sq_m += area_sq_m
    return abs(signed_area_sq_m) / 1_000_000


def _clean_text(value: object) -> str:
    return str(value).replace("\x00", "").strip()
