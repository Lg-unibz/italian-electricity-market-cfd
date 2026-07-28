"""Offline checks for the public-package metadata and data boundary."""

from __future__ import annotations

import csv
import json
import unittest
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]


class PackageManifestTests(unittest.TestCase):
    """Keep the release metadata and data contract present and parseable."""

    def test_metadata_files_are_parseable(self) -> None:
        metadata = json.loads((ROOT_DIR / ".zenodo.json").read_text(encoding="utf-8"))
        self.assertEqual(metadata["upload_type"], "software")
        self.assertEqual(metadata["version"], "1.0.0")
        self.assertTrue((ROOT_DIR / "CITATION.cff").read_text(encoding="utf-8").startswith("cff-version:"))

    def test_reference_manifest_has_complete_output_contract(self) -> None:
        manifest = json.loads(
            (ROOT_DIR / "reproducibility/reference_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(manifest["release_version"], "1.0.0")
        self.assertEqual(len(manifest["preprocessing_outputs"]), 21)
        self.assertEqual(len(manifest["historical_backtest_outputs"]), 28)

    def test_source_manifest_has_expected_columns_and_rows(self) -> None:
        with (ROOT_DIR / "data/source_manifest.csv").open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertGreaterEqual(len(rows), 8)
        self.assertEqual(
            set(rows[0]),
            {
                "dataset",
                "role",
                "expected_local_path",
                "provider",
                "source_locator",
                "licence_or_terms",
                "notes",
            },
        )
        self.assertIn("copernicus_wind", {row["dataset"] for row in rows})

    def test_local_data_directories_are_not_part_of_the_release(self) -> None:
        for relative in ("data/raw", "data/processed", "results"):
            self.assertFalse((ROOT_DIR / relative).exists())


if __name__ == "__main__":
    unittest.main()
