"""Download annual Terna wind capacity and production files for 2015-2024."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from urllib.request import Request, urlopen


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from market_preprocessing.config import RAW_TERNA_DIR, TERNA_ENDPOINT  # noqa: E402
from market_preprocessing.terna_wind import (  # noqa: E402
    _normalize_response_rows,
    _write_rows,
)


DATASETS = {
    "CapacityRenewableSources": "terna_capacity_renewable_sources_{year}.csv",
    "ProductionRenewableSources": "terna_production_renewable_sources_{year}.csv",
}


def fetch_annual_dataset(dataset: str, year: int) -> list[dict[str, object]]:
    """Fetch one annual Terna dataset with the ordering required by the API."""

    page_size = 5000
    rows: list[dict[str, object]] = []
    page_index = 0
    while True:
        payload = {
            "filterDataset": dataset,
            "filterYear": str(year),
            "pageSize": str(page_size),
            "pageIndex": str(page_index),
            "db": "dati",
            "orderByColumn": "Anno",
            "orderByDir": "desc",
        }
        request = Request(
            TERNA_ENDPOINT,
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0",
            },
            method="POST",
        )
        with urlopen(request, timeout=90) as response:
            result = json.loads(response.read().decode("utf-8"))
        page_rows = _normalize_response_rows(result)
        rows.extend(page_rows)
        count = int(result.get("Count", len(rows)))
        if len(rows) >= count:
            return rows
        page_index += 1


def main() -> int:
    """Download the annual Terna files required by the historical backtest."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--years",
        nargs="+",
        type=int,
        default=list(range(2015, 2025)),
    )
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    years = sorted(set(args.years))
    invalid = [year for year in years if year < 2015 or year > 2024]
    if invalid:
        raise ValueError(f"Years outside the validated study window: {invalid}")

    RAW_TERNA_DIR.mkdir(parents=True, exist_ok=True)
    for year in years:
        for dataset, filename in DATASETS.items():
            path = RAW_TERNA_DIR / filename.format(year=year)
            if path.exists() and not args.force:
                print(f"Using existing file: {path}")
                continue
            rows = fetch_annual_dataset(dataset, year)
            _write_rows(path, rows)
            print(f"Downloaded {dataset} {year}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
