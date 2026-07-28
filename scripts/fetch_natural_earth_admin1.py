"""Fetch the Natural Earth Admin-1 layer used to decode Copernicus columns."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import date
from pathlib import Path
from urllib.request import urlopen
from zipfile import ZipFile


ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "data" / "raw" / "copernicus" / "natural_earth_admin1"
ARCHIVE_PATH = OUTPUT_DIR / "ne_10m_admin_1_states_provinces.zip"
METADATA_PATH = OUTPUT_DIR / "download_metadata.json"
SOURCE_URL = (
    "https://naturalearth.s3.amazonaws.com/10m_cultural/"
    "ne_10m_admin_1_states_provinces.zip"
)


def main() -> None:
    """Download, checksum, and extract Natural Earth 10m Admin-1 version 5.1.1."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-dir", type=Path, default=OUTPUT_DIR)
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    archive_path = args.output_dir / ARCHIVE_PATH.name
    metadata_path = args.output_dir / METADATA_PATH.name
    shp_path = args.output_dir / "ne_10m_admin_1_states_provinces.shp"
    if shp_path.exists() and not args.force:
        raise FileExistsError(f"Natural Earth layer already exists: {shp_path}")
    args.output_dir.mkdir(parents=True, exist_ok=True)
    with urlopen(SOURCE_URL, timeout=120) as response, archive_path.open("wb") as output:
        shutil.copyfileobj(response, output)
    checksum = hashlib.sha256(archive_path.read_bytes()).hexdigest()
    with ZipFile(archive_path) as bundle:
        bundle.extractall(args.output_dir)
    if not shp_path.exists() or not shp_path.with_suffix(".dbf").exists():
        raise FileNotFoundError("Downloaded Natural Earth archive lacks SHP/DBF files")
    metadata = {
        "source_url": SOURCE_URL,
        "retrieval_date": date.today().isoformat(),
        "dataset": "Natural Earth Admin 1 - States, Provinces, 1:10m",
        "version": "5.1.1",
        "licence": "Public domain",
        "archive_sha256": checksum,
        "selected_shapefile": str(shp_path.relative_to(ROOT_DIR)),
        "purpose": "Map coded Copernicus Italian ADM1 columns to 20 regions.",
    }
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Downloaded Natural Earth Admin-1 layer: {shp_path}")


if __name__ == "__main__":
    main()
