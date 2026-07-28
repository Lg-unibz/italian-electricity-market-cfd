"""Check that the public release contains code and metadata but no local data."""

from __future__ import annotations

from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    "README.md",
    "CITATION.cff",
    ".zenodo.json",
    "LICENSE",
    "DATA_LICENSE.md",
    "requirements.txt",
    "requirements-lock.txt",
    "pyproject.toml",
    ".python-version",
    "data/README.md",
    "data/source_manifest.csv",
    "docs/reproducibility.md",
    "docs/reproduction_audit.md",
    "docs/paper_integration.md",
    "docs/github_zenodo_release.md",
    "reproducibility/reference_manifest.json",
    "scripts/build_zenodo_data_deposit.py",
    "scripts/fetch_terna_historical_wind.py",
    "scripts/run_pipeline.py",
    "scripts/run_historical_cfd_backtest.py",
    "scripts/verify_reproduction.py",
    "scripts/verify_manuscript_consistency.py",
    "src/cfd_analysis/historical_backtest.py",
    "src/market_preprocessing/preprocess.py",
    "tests/test_historical_cfd.py",
)
FORBIDDEN_DIRS = ("data/raw", "data/processed", "results")
MAX_GITHUB_FILE_BYTES = 100 * 1024 * 1024
LOCAL_RELEASE_DIRS = {"release"}


def main() -> int:
    """Validate the release structure and return a shell-friendly status code."""

    missing = [path for path in REQUIRED_FILES if not (ROOT_DIR / path).is_file()]
    forbidden = [path for path in FORBIDDEN_DIRS if (ROOT_DIR / path).exists()]
    oversized = [
        path.relative_to(ROOT_DIR)
        for path in ROOT_DIR.rglob("*")
        if path.is_file()
        and path.relative_to(ROOT_DIR).parts[0] not in LOCAL_RELEASE_DIRS
        and path.stat().st_size >= MAX_GITHUB_FILE_BYTES
    ]
    if missing or forbidden or oversized:
        if missing:
            print("Missing required files:")
            print("\n".join(f"  {path}" for path in missing))
        if forbidden:
            print("Forbidden local-data directories present:")
            print("\n".join(f"  {path}" for path in forbidden))
        if oversized:
            print("Files at or above GitHub's 100 MiB limit:")
            print("\n".join(f"  {path.as_posix()}" for path in oversized))
        return 1
    print(f"Publication package check passed: {ROOT_DIR}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
