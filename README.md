# Italian Electricity Market CfD Backtest

Reproducible code package for the historical Italian wind CfD comparison
covering 2015--2024 and the validated 2024 preprocessing baseline.

The package evaluates market-only revenue, a conventional two-sided CfD, a
Newbery-inspired Zonal Yardstick CfD, and a Schlecht-inspired Financial CfD
for stylised 1 MW regional wind profiles. It is research software, not a
financial model for a specific plant or an investment recommendation.

## Scope

- hourly GME day-ahead zonal prices for 2015--2024;
- homogeneous Copernicus/ERA5-derived regional wind capacity factors;
- Terna annual installed-capacity weights and production validation;
- cost-based `K_P50` and `K_P25` strike calibration;
- producer revenue risk, top-up, clawback, and net public cost;
- auditable preprocessing and historical backtest outputs.

Future-price scenarios, stochastic extensions, NPV/ROI, financing, welfare,
and a new hybrid mechanism are outside this release.

## Data availability

GME and Terna raw files are intentionally not bundled because their provider
terms do not establish an unrestricted redistribution licence. The normalized
Copernicus input is about 584 MB uncompressed and therefore exceeds GitHub's
regular 100 MB per-file limit.
The companion Zenodo dataset is available at
[10.5281/zenodo.21640789](https://doi.org/10.5281/zenodo.21640789). The
acquisition, normalization, and data-release workflow is documented in
[`data/README.md`](data/README.md),
[`data/source_manifest.csv`](data/source_manifest.csv), and
[`docs/reproducibility.md`](docs/reproducibility.md).

The scripts create the local `data/raw`, `data/processed`, and `results`
directories when they run. These directories are excluded by `.gitignore`.

## Quick start

For exact reference-environment reproduction, use Python 3.14 and the lock file:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements-lock.txt
```

Run the unit tests without downloading data:

```powershell
$env:PYTHONPATH = "src"
python -m unittest discover -s tests -v
```

After placing the required official inputs locally, run the 2024 baseline:

```powershell
python -X utf8 scripts/fetch_terna_wind_data.py
python -X utf8 scripts/run_pipeline.py
```

Download the 2015--2024 annual Terna inputs with:

```powershell
python -X utf8 scripts/fetch_terna_historical_wind.py
```

To run the complete historical backtest, first prepare the Copernicus input
and GME/Terna annual files as described in `docs/reproducibility.md`, then run:

```powershell
python -X utf8 scripts/run_historical_cfd_backtest.py
```

Use `--skip-maps` when the optional ISTAT boundary archive is not available.

Verify the regenerated files against the paper reference manifest:

```powershell
python -X utf8 scripts/verify_reproduction.py
```

When the manuscript source is available, verify every static result table,
numeric claim, and figure reference with:

```powershell
python -X utf8 scripts/verify_manuscript_consistency.py `
  --manuscript path/to/main.tex
```

## Repository layout

```text
src/       reusable preprocessing and CfD-analysis modules
scripts/   data acquisition, normalisation, and pipeline entry points
tests/     offline accounting and output-contract tests
data/      input contract and source manifest; local data are not committed
docs/      reproducibility, methods, and research-status documentation
```

## Reproducibility and citation

The exact research assumptions and output contracts are in
[`docs/historical_cfd_backtest.md`](docs/historical_cfd_backtest.md).
The completed end-to-end evidence is summarized in
[`docs/reproduction_audit.md`](docs/reproduction_audit.md).
Please cite this software using [`CITATION.cff`](CITATION.cff). Zenodo's GitHub
integration reads [`.zenodo.json`](.zenodo.json). Build the separate data
deposit containing the normalized Copernicus input and the exact paper outputs
with:

```powershell
python -X utf8 scripts/build_zenodo_data_deposit.py
```

The generated `release/` directory is ignored by Git and must be uploaded as a
separate Zenodo dataset record.

The exact publication sequence and commands are in
[`docs/github_zenodo_release.md`](docs/github_zenodo_release.md).

## Licence

Source code is released under the MIT Licence. Documentation and metadata are
released under CC BY 4.0; see [`LICENSE`](LICENSE) and
[`LICENSE-DOCS`](LICENSE-DOCS). Upstream data remain subject to their own
terms, listed in the data manifest.
