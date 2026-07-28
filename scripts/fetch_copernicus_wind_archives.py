"""Fetch official Copernicus ADM1 hourly onshore-wind archives via CDS API."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
TARGET_DIR = ROOT_DIR / "data" / "raw" / "copernicus" / "cds_archives"
DATASET = "sis-energy-global-reanalysis"
TECHNOLOGIES = [
    "ic2_5hh100",
    "ic2_5hh100e",
    "ic3_3hh84",
    "ic6hh135",
    "ic6hh135e",
]
ALL_MONTHS = [f"{month:02d}" for month in range(1, 13)]


def main() -> None:
    """Download yearly CDS archives after user authentication and licence acceptance."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=list(range(2015, 2025)),
        help="Local study years to retrieve; defaults to 2015 through 2024.",
    )
    parser.add_argument("--force", action="store_true", help="Replace existing archives.")
    parser.add_argument(
        "--include-boundary",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Also retrieve December before the first year for Europe/Rome alignment.",
    )
    args = parser.parse_args()
    try:
        import cdsapi
    except ImportError as error:
        raise RuntimeError(
            "cdsapi is required. Install requirements.txt in the project virtualenv."
        ) from error

    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    requests: list[tuple[int, list[str]]] = []
    years = sorted(set(args.years))
    if args.include_boundary:
        requests.append((years[0] - 1, ["12"]))
    requests.extend((year, ALL_MONTHS) for year in years)
    client = cdsapi.Client()
    metadata_rows: list[dict[str, object]] = []
    for year, months in requests:
        target = TARGET_DIR / f"global_admin1_onshore_wind_{year}.zip"
        request = {
            "spatial_coverage": "global",
            "variable": ["wind_power_onshore_capacity_factor"],
            "technological_specification": TECHNOLOGIES,
            "spatial_resolution": ["admin_1"],
            "temporal_resolution": ["1_hour"],
            "year": [str(year)],
            "month": months,
            "version": "1_00",
            "file_format": "csv",
        }
        if target.exists() and not args.force:
            print(f"Using existing archive: {target}")
        else:
            print(f"Requesting {year}, months={','.join(months)}")
            client.retrieve(DATASET, request, str(target))
        metadata_rows.append(
            {
                "year": year,
                "months": months,
                "request": request,
                "archive": str(target.relative_to(ROOT_DIR)),
                "archive_sha256": hashlib.sha256(target.read_bytes()).hexdigest(),
            }
        )
    metadata = {
        "retrieval_date": date.today().isoformat(),
        "dataset": DATASET,
        "title": "Global climate and energy indicators from 1950 to present derived from reanalysis",
        "doi": "10.24381/3bb607bd",
        "licence": "CC-BY-4.0",
        "requests": metadata_rows,
        "note": (
            "CDS ADM1 CSV outputs are global. Retain the 20 Italian ADM1 series "
            "and normalize them to timestamp_utc,region,technology,capacity_factor "
            "before running the backtest. Raw archives remain local and ignored."
        ),
    }
    (TARGET_DIR / "download_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
