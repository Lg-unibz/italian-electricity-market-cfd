"""Fetch or verify Terna wind forecast and installed capacity inputs for 2024."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from market_preprocessing.terna_wind import ensure_terna_wind_raw_data  # noqa: E402


def main() -> int:
    outputs = ensure_terna_wind_raw_data()
    for dataset, path in outputs.items():
        print(f"{dataset}: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
