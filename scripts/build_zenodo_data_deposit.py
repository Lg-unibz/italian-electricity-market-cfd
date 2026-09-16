"""Build the separate Zenodo dataset deposit for normalized input and outputs."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import shutil
import zipfile
from datetime import date
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
VERSION = "1.1.0"
COPERNICUS_RELATIVE = (
    Path("data")
    / "raw"
    / "copernicus"
    / "onshore_wind_capacity_factor_adm1_2015_2024.csv"
)
RESULTS_RELATIVE = Path("results") / "historical_cfd_backtest_2015_2024"
REFERENCE_MANIFEST = (
    PACKAGE_ROOT / "reproducibility" / "reference_manifest.json"
)


def sha256(path: Path) -> str:
    """Return the SHA-256 digest for one file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def gzip_deterministic(source: Path, target: Path) -> None:
    """Compress a file with a stable gzip timestamp and stream semantics."""

    with source.open("rb") as input_handle, target.open("wb") as output_handle:
        with gzip.GzipFile(
            filename="",
            mode="wb",
            fileobj=output_handle,
            mtime=0,
            compresslevel=9,
        ) as compressed:
            shutil.copyfileobj(input_handle, compressed, length=1024 * 1024)


def zip_results(source_root: Path, target: Path) -> int:
    """Create a deterministic ZIP containing every paper table and figure."""

    files = sorted(path for path in source_root.rglob("*") if path.is_file())
    with zipfile.ZipFile(
        target,
        mode="w",
        compression=zipfile.ZIP_DEFLATED,
        compresslevel=9,
    ) as archive:
        for path in files:
            relative = path.relative_to(source_root).as_posix()
            info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            archive.writestr(info, path.read_bytes(), compresslevel=9)
    return len(files)


def main() -> int:
    """Build a clean, checksum-documented Zenodo dataset staging directory."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--project-root",
        type=Path,
        default=PACKAGE_ROOT,
        help="Project root containing data/raw and reproduced results.",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=PACKAGE_ROOT / "release" / f"zenodo-data-v{VERSION}",
    )
    args = parser.parse_args()
    project_root = args.project_root.resolve()
    output_dir = args.output_dir.resolve()
    if output_dir.exists() and any(output_dir.iterdir()):
        raise FileExistsError(
            f"Output directory is not empty; choose a fresh path: {output_dir}"
        )
    output_dir.mkdir(parents=True, exist_ok=True)

    copernicus = project_root / COPERNICUS_RELATIVE
    results = project_root / RESULTS_RELATIVE
    if not copernicus.is_file():
        raise FileNotFoundError(f"Missing normalized Copernicus input: {copernicus}")
    if not results.is_dir():
        raise FileNotFoundError(f"Missing reproduced paper results: {results}")
    if not REFERENCE_MANIFEST.is_file():
        raise FileNotFoundError(
            f"Missing reference manifest: {REFERENCE_MANIFEST}"
        )

    compressed_input = output_dir / f"{copernicus.name}.gz"
    result_archive = output_dir / f"paper_outputs_2015_2024_v{VERSION}.zip"
    gzip_deterministic(copernicus, compressed_input)
    result_count = zip_results(results, result_archive)
    shutil.copy2(
        REFERENCE_MANIFEST,
        output_dir / REFERENCE_MANIFEST.name,
    )
    shutil.copy2(
        PACKAGE_ROOT / "data" / "source_manifest.csv",
        output_dir / "source_manifest.csv",
    )
    shutil.copy2(
        PACKAGE_ROOT / "DATA_LICENSE.md",
        output_dir / "DATA_LICENSE.md",
    )

    readme = output_dir / "README.md"
    readme.write_text(
        "\n".join(
            (
                "# Italian Electricity Market CfD Backtest data deposit",
                "",
                f"This dataset record accompanies software release v{VERSION}.",
                "",
                "Included:",
                "",
                "- normalized Copernicus ADM1 onshore-wind capacity factors, "
                "2015--2024, compressed with gzip;",
                f"- {result_count} reproduced paper tables and figures in one ZIP;",
                "- the exact input/output SHA-256 reference manifest;",
                "- source, access, and rights metadata.",
                "",
                "Not included: GME workbooks or Terna raw CSV files. Obtain these "
                "from the providers and verify them with reference_manifest.json.",
                "",
                "The normalized Copernicus input is derived from dataset "
                "sis-energy-global-reanalysis, DOI 10.24381/3bb607bd, under "
                "CC BY 4.0. Paper outputs are released under CC BY 4.0 with "
                "source attribution to GME, Terna, Copernicus C3S, Eurostat, "
                "ISTAT, and Natural Earth as documented in source_manifest.csv.",
                "",
            )
        ),
        encoding="utf-8",
    )

    metadata = {
        "upload_type": "dataset",
        "title": (
            "Italian Electricity Market CfD Backtest: normalized wind input "
            "and reproduced outputs"
        ),
        "version": VERSION,
        "publication_date": date.today().isoformat(),
        "creators": [{"name": "Gambadori, Lorenzo"}],
        "access_right": "open",
        "license": "cc-by-4.0",
        "keywords": [
            "electricity markets",
            "contracts for difference",
            "wind power",
            "Italy",
            "reproducible research",
        ],
        "description": (
            "Normalized Copernicus/ERA5-derived Italian regional wind capacity "
            "factors and the exact tables and figures reproduced by software "
            f"release v{VERSION} for the 2015-2024 historical CfD backtest."
        ),
        "notes": (
            "GME and Terna raw files are excluded. Their provider locations and "
            "validated SHA-256 checksums are documented in the included manifests."
        ),
    }
    (output_dir / "zenodo_dataset_metadata.json").write_text(
        json.dumps(metadata, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )

    checksum_targets = sorted(
        path
        for path in output_dir.iterdir()
        if path.is_file() and path.name != "checksums.sha256"
    )
    (output_dir / "checksums.sha256").write_text(
        "\n".join(f"{sha256(path)}  {path.name}" for path in checksum_targets)
        + "\n",
        encoding="utf-8",
    )
    print(f"Built Zenodo data deposit: {output_dir}")
    for path in sorted(output_dir.iterdir()):
        if path.is_file():
            print(f"  {path.name}: {path.stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
