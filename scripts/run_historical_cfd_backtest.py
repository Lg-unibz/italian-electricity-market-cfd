"""Command-line runner for the 2015-2024 historical Italian CfD backtest."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))

from cfd_analysis.historical_backtest import run_historical_cfd_backtest
from cfd_analysis.historical_inputs import COPERNICUS_WIND_FILE


def main() -> None:
    """Parse CLI options and run the complete historical comparison."""

    parser = argparse.ArgumentParser(
        description="Backtest market-only and wind CfDs on Italian 2015-2024 hourly data."
    )
    parser.add_argument(
        "--copernicus-file",
        type=Path,
        default=COPERNICUS_WIND_FILE,
        help="Canonical long-form Copernicus ADM1 hourly wind CSV.",
    )
    parser.add_argument(
        "--istat-shapefile",
        type=Path,
        default=None,
        help="Optional explicit path to Reg01012024_g_WGS84.shp.",
    )
    parser.add_argument(
        "--skip-maps",
        action="store_true",
        help="Run all economic tables without requiring the local ISTAT shapefile.",
    )
    args = parser.parse_args()
    try:
        outputs = run_historical_cfd_backtest(
            copernicus_path=args.copernicus_file,
            istat_shapefile=args.istat_shapefile,
            generate_maps=not args.skip_maps,
        )
    except FileNotFoundError as error:
        raise SystemExit(str(error)) from None
    print(f"Selected Copernicus technology: {outputs.selected_copernicus_technology}")
    for label, value in outputs.strikes_real_2024_eur_per_mwh.items():
        print(f"{label}: {value:.2f} real-2024 EUR/MWh")
    print(f"Generated {len(outputs.tables)} tables and {len(outputs.figures)} figures")


if __name__ == "__main__":
    main()
