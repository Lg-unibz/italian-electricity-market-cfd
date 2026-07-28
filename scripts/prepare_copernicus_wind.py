"""Normalize coded CDS ADM1 ZIP archives to 20 Italian wind profiles."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from zipfile import ZipFile

import pandas as pd


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from cfd_analysis.copernicus_normalization import (
    load_natural_earth_admin1_weights,
    normalize_cds_admin1_csv,
)
from cfd_analysis.historical_inputs import (
    COPERNICUS_ONSHORE_TECHNOLOGIES,
    COPERNICUS_WIND_FILE,
    load_copernicus_hourly_wind,
)


DEFAULT_ARCHIVE_DIR = ROOT_DIR / "data" / "raw" / "copernicus" / "cds_archives"
DEFAULT_NATURAL_EARTH_SHP = (
    ROOT_DIR
    / "data"
    / "raw"
    / "copernicus"
    / "natural_earth_admin1"
    / "ne_10m_admin_1_states_provinces.shp"
)
DEFAULT_WEIGHT_AUDIT = (
    ROOT_DIR
    / "data"
    / "raw"
    / "copernicus"
    / "natural_earth_italy_admin1_weights.csv"
)
FILENAME_TECHNOLOGY_CODES = {
    "WP001": "ic2_5hh100",
    "WP011": "ic2_5hh100e",
    "WP002": "ic3_3hh84",
    "WP004": "ic6hh135",
    "WP014": "ic6hh135e",
}
FIRST_REQUIRED_UTC = pd.Timestamp("2014-12-31T23:00:00Z")
END_REQUIRED_UTC_EXCLUSIVE = pd.Timestamp("2024-12-31T23:00:00Z")
EXPECTED_CANONICAL_ROWS = 8_767_200


def main() -> None:
    """Stream CDS archives, area-weight Italian units, and validate output."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--archive-dir", type=Path, default=DEFAULT_ARCHIVE_DIR)
    parser.add_argument(
        "--admin1-shapefile",
        type=Path,
        default=DEFAULT_NATURAL_EARTH_SHP,
        help="Natural Earth 10m Admin-1 shapefile whose adm1_code fields match CDS.",
    )
    parser.add_argument("--output", type=Path, default=COPERNICUS_WIND_FILE)
    parser.add_argument("--weight-audit", type=Path, default=DEFAULT_WEIGHT_AUDIT)
    parser.add_argument("--force", action="store_true", help="Replace existing output.")
    args = parser.parse_args()

    archives = sorted(args.archive_dir.glob("*.zip"))
    if not archives:
        raise FileNotFoundError(
            f"No CDS ZIP archives found in {args.archive_dir}. "
            "Run scripts/fetch_copernicus_wind_archives.py first."
        )
    if not args.admin1_shapefile.exists():
        raise FileNotFoundError(
            f"Missing Natural Earth Admin-1 shapefile: {args.admin1_shapefile}. "
            "Run scripts/fetch_natural_earth_admin1.py first."
        )
    if args.output.exists() and not args.force:
        raise FileExistsError(f"Output already exists; pass --force: {args.output}")

    weights = load_natural_earth_admin1_weights(args.admin1_shapefile)
    args.weight_audit.parent.mkdir(parents=True, exist_ok=True)
    weights.to_csv(args.weight_audit, index=False)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    temporary_output = args.output.with_suffix(".tmp.csv")
    temporary_output.unlink(missing_ok=True)
    wrote_header = False
    used_files = 0
    written_rows = 0
    technologies: set[str] = set()
    try:
        for archive in archives:
            archive_files = 0
            with ZipFile(archive) as bundle:
                for member in sorted(bundle.infolist(), key=lambda item: item.filename):
                    if member.is_dir() or not member.filename.lower().endswith(".csv"):
                        continue
                    technology = technology_from_filename(member.filename)
                    if technology is None:
                        raise ValueError(
                            f"Cannot infer wind technology from CDS member: {member.filename}"
                        )
                    with bundle.open(member) as source:
                        normalized = normalize_cds_admin1_csv(
                            source,
                            member.filename,
                            technology,
                            weights,
                        )
                    normalized = normalized[
                        normalized["timestamp_utc"].ge(FIRST_REQUIRED_UTC)
                        & normalized["timestamp_utc"].lt(END_REQUIRED_UTC_EXCLUSIVE)
                    ]
                    if normalized.empty:
                        continue
                    normalized.to_csv(
                        temporary_output,
                        mode="a" if wrote_header else "w",
                        header=not wrote_header,
                        index=False,
                    )
                    wrote_header = True
                    used_files += 1
                    archive_files += 1
                    written_rows += len(normalized)
                    technologies.add(technology)
            print(f"Processed {archive.name}: {archive_files} CDS members")
        if not wrote_header:
            raise ValueError("No required Italian Copernicus observations were written")
        if written_rows != EXPECTED_CANONICAL_ROWS:
            raise ValueError(
                f"Unexpected canonical row count: {written_rows:,} "
                f"!= {EXPECTED_CANONICAL_ROWS:,}"
            )
        expected_technologies = set(COPERNICUS_ONSHORE_TECHNOLOGIES)
        if technologies != expected_technologies:
            raise ValueError(
                "Incomplete Copernicus technology set; "
                f"missing={sorted(expected_technologies - technologies)}, "
                f"extra={sorted(technologies - expected_technologies)}"
            )
        validated = load_copernicus_hourly_wind(temporary_output)
        if len(validated) != EXPECTED_CANONICAL_ROWS:
            raise ValueError("Canonical Copernicus loader changed the validated row count")
        temporary_output.replace(args.output)
    except Exception:
        temporary_output.unlink(missing_ok=True)
        raise
    print(
        f"Prepared {written_rows:,} rows from {used_files} CDS files: {args.output}"
    )


def technology_from_filename(filename: str) -> str | None:
    """Infer the canonical five-technology label from a CDS filename."""

    upper = filename.upper()
    for code, technology in FILENAME_TECHNOLOGY_CODES.items():
        if code in upper:
            return technology
    lowered = filename.lower().replace(".", "_")
    return next(
        (
            technology
            for technology in COPERNICUS_ONSHORE_TECHNOLOGIES
            if technology in lowered
        ),
        None,
    )


if __name__ == "__main__":
    main()
