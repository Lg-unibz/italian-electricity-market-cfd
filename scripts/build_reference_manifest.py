"""Build the SHA-256 manifest for the validated paper reproduction."""

from __future__ import annotations

import argparse
import hashlib
import importlib.metadata
import json
import platform
from datetime import date
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = PACKAGE_ROOT / "reproducibility" / "reference_manifest.json"
YEARS = tuple(range(2015, 2025))
LOCKED_PACKAGES = (
    "cdsapi",
    "matplotlib",
    "numpy",
    "pandas",
    "pyproj",
    "seaborn",
)


def file_record(path: Path, relative_to: Path) -> dict[str, object]:
    """Return a stable path, size, and SHA-256 record for one file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    record: dict[str, object] = {
        "path": path.relative_to(relative_to).as_posix(),
        "size_bytes": path.stat().st_size,
        "sha256": digest.hexdigest(),
    }
    normalized = path.as_posix().lower()
    if "/data/raw/terna/" in normalized and path.suffix.lower() == ".csv":
        record["row_order_insensitive_sha256"] = row_order_insensitive_sha256(
            path
        )
    return record


def row_order_insensitive_sha256(path: Path) -> str:
    """Hash a provider CSV after sorting complete data rows."""

    lines = path.read_bytes().splitlines()
    if not lines:
        return hashlib.sha256(b"").hexdigest()
    canonical = b"\n".join([lines[0], *sorted(lines[1:])]) + b"\n"
    return hashlib.sha256(canonical).hexdigest()


def required_runtime_inputs(project_root: Path) -> list[Path]:
    """Return every local input directly consumed by the two pipelines."""

    paths = [
        *(
            project_root
            / "data"
            / "raw"
            / "xlsx"
            / f"{year}0101_{year}1231_MGP_PrezziZonali.xlsx"
            for year in YEARS
        ),
        *(
            project_root
            / "data"
            / "raw"
            / "terna"
            / f"terna_capacity_renewable_sources_{year}.csv"
            for year in YEARS
        ),
        *(
            project_root
            / "data"
            / "raw"
            / "terna"
            / f"terna_production_renewable_sources_{year}.csv"
            for year in YEARS
        ),
        project_root
        / "data"
        / "raw"
        / "terna"
        / "terna_wind_production_forecast_2024.csv",
        project_root
        / "data"
        / "raw"
        / "copernicus"
        / "onshore_wind_capacity_factor_adm1_2015_2024.csv",
    ]
    istat = sorted(
        (project_root / "data" / "raw" / "istat").rglob(
            "Reg01012024_g_WGS84.*"
        )
    )
    paths.extend(path for path in istat if path.suffix.lower() in {
        ".cpg",
        ".dbf",
        ".prj",
        ".shp",
        ".shx",
    })
    return paths


def provenance_inputs(project_root: Path) -> list[Path]:
    """Return source archives and spatial mapping files used for normalization."""

    paths = sorted(
        (
            project_root / "data" / "raw" / "copernicus" / "cds_archives"
        ).glob("global_admin1_onshore_wind_*.zip")
    )
    paths.extend(
        sorted(
            path
            for path in (
                project_root
                / "data"
                / "raw"
                / "copernicus"
                / "natural_earth_admin1"
            ).glob("*")
            if path.is_file()
        )
    )
    return paths


def scientific_software_files(package_root: Path) -> list[Path]:
    """Return scientific code, tests, and environment declarations."""

    paths: list[Path] = []
    for directory in ("src", "scripts", "tests"):
        paths.extend(sorted((package_root / directory).rglob("*.py")))
    paths.extend(
        package_root / name
        for name in (
            "requirements.txt",
            "requirements-lock.txt",
            "pyproject.toml",
            ".python-version",
        )
    )
    return paths


def output_files(project_root: Path, relative_root: str) -> list[Path]:
    """Return all generated files below one validated output directory."""

    root = project_root / relative_root
    return sorted(path for path in root.rglob("*") if path.is_file())


def checked_records(paths: list[Path], relative_to: Path) -> list[dict[str, object]]:
    """Build records and fail explicitly when an expected file is absent."""

    missing = [path for path in paths if not path.is_file()]
    if missing:
        raise FileNotFoundError(
            "Missing files required for the reference manifest:\n"
            + "\n".join(str(path) for path in missing)
        )
    return [file_record(path, relative_to) for path in paths]


def main() -> int:
    """Build the reference manifest from a validated local project root."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--reference-project-root",
        type=Path,
        default=PACKAGE_ROOT,
        help="Project root containing the validated data/processed and results trees.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--manuscript",
        type=Path,
        default=None,
        help="Optional manuscript source whose checksum anchors the paper audit.",
    )
    args = parser.parse_args()
    reference_root = args.reference_project_root.resolve()
    package_root = PACKAGE_ROOT.resolve()

    payload: dict[str, object] = {
        "schema_version": 1,
        "release_version": "1.1.0",
        "study_period": "2015-2024",
        "generated_on": date.today().isoformat(),
        "reference_environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
            "packages": {
                name: importlib.metadata.version(name)
                for name in LOCKED_PACKAGES
            },
        },
        "scientific_software": checked_records(
            scientific_software_files(package_root),
            package_root,
        ),
        "runtime_inputs": checked_records(
            required_runtime_inputs(reference_root),
            reference_root,
        ),
        "normalization_provenance": checked_records(
            provenance_inputs(reference_root),
            reference_root,
        ),
        "preprocessing_outputs": checked_records(
            output_files(reference_root, "data/processed"),
            reference_root,
        ),
        "historical_backtest_outputs": checked_records(
            output_files(
                reference_root,
                "results/historical_cfd_backtest_2015_2024",
            ),
            reference_root,
        ),
    }
    if args.manuscript is not None:
        manuscript = args.manuscript.resolve()
        payload["manuscript"] = file_record(manuscript, manuscript.parent)

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote reference manifest: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
