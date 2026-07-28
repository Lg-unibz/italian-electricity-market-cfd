"""Run the 2024 preprocessing-only pipeline."""

from __future__ import annotations

import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from market_preprocessing.preprocess import run_preprocessing_pipeline  # noqa: E402


def main() -> int:
    outputs = run_preprocessing_pipeline()
    print("Processed CSV files:")
    for path in outputs["processed"].values():  # type: ignore[union-attr]
        print(f"  {path}")
    print("Figures:")
    for path in outputs["figures"]:  # type: ignore[union-attr]
        print(f"  {path}")
    print("Result tables/figures: not touched by Phase 1")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
