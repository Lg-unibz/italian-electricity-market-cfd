"""Download the official generalized ISTAT 2024 administrative boundaries."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import date
from pathlib import Path
from urllib.request import Request, urlopen
from zipfile import ZipFile


ROOT_DIR = Path(__file__).resolve().parents[1]
TARGET_DIR = ROOT_DIR / "data" / "raw" / "istat"
SOURCE_URL = (
    "https://www.istat.it/storage/cartografia/confini_amministrativi/"
    "generalizzati/2024/Limiti01012024_g.zip"
)
SOURCE_PAGE = (
    "https://www.istat.it/notizia/"
    "confini-delle-unita-amministrative-a-fini-statistici-al-1-gennaio-2018-2/"
)


def main() -> None:
    """Download, checksum, extract and document the local provenance input."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--force", action="store_true", help="Replace a previous local download.")
    args = parser.parse_args()
    archive = TARGET_DIR / "Limiti01012024_g.zip"
    extract_dir = TARGET_DIR / "Limiti01012024_g"
    TARGET_DIR.mkdir(parents=True, exist_ok=True)
    if archive.exists() and not args.force:
        print(f"Using existing archive: {archive}")
    else:
        request = Request(SOURCE_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=120) as response:
            archive.write_bytes(response.read())
        print(f"Downloaded: {archive}")
    extract_dir.mkdir(parents=True, exist_ok=True)
    with ZipFile(archive) as bundle:
        bundle.extractall(extract_dir)
    shapefiles = sorted(extract_dir.rglob("Reg01012024_g_WGS84.shp"))
    if not shapefiles:
        raise FileNotFoundError("The ISTAT archive does not contain Reg01012024_g_WGS84.shp")
    metadata = {
        "retrieval_date": date.today().isoformat(),
        "source": "ISTAT generalized administrative boundaries, 1 January 2024",
        "source_page": SOURCE_PAGE,
        "download_url": SOURCE_URL,
        "archive_sha256": hashlib.sha256(archive.read_bytes()).hexdigest(),
        "coordinate_reference_system": "WGS84",
        "selected_region_shapefile": str(shapefiles[0].relative_to(ROOT_DIR)),
        "repository_policy": "Local provenance input; not committed.",
    }
    (TARGET_DIR / "istat_2024_boundaries_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Region shapefile: {shapefiles[0]}")


if __name__ == "__main__":
    main()
