# GitHub and Zenodo release procedure

The GitHub repository and the Zenodo dataset are two linked records:

1. GitHub/Zenodo software record for source code release `v1.0.0`;
2. Zenodo dataset record for the normalized Copernicus input and reproduced
   paper outputs.

GME and Terna raw files are not uploaded to either record.

## 1. Create the GitHub repository

Create an empty public repository named `italian-electricity-market-cfd`.
Do not add a remote README, licence, or `.gitignore`, because they are already
present locally.

From this directory:

```powershell
git init
git add .
git status
git commit -m "Release reproducible Italian electricity market CfD backtest"
git branch -M main
git remote add origin https://github.com/<OWNER>/italian-electricity-market-cfd.git
git push -u origin main
```

The ignored `release/`, `data/raw/`, `data/processed/`, and `results/`
directories are not pushed. Verify this with `git status --ignored`.

## 2. Publish the companion Zenodo dataset

Run the complete pipelines and both verification scripts, then build:

```powershell
python -X utf8 scripts/build_zenodo_data_deposit.py
```

Create a new Zenodo record with resource type `Dataset`. Upload every file from
`release/zenodo-data-v1.0.0/`. Copy the fields from
`zenodo_dataset_metadata.json`, add ORCID and affiliation, reserve the DOI, and
publish the record.

## 3. Link the data DOI before the software release

The published companion dataset DOI is
[`10.5281/zenodo.22790673`](https://doi.org/10.5281/zenodo.22790673). It has
been added to `.zenodo.json` as:

```json
"related_identifiers": [
  {
    "identifier": "https://doi.org/10.5281/zenodo.22790673",
    "relation": "isSupplementedBy",
    "resource_type": "dataset"
  }
]
```

The same DOI is recorded in `CITATION.cff`. Add it to the manuscript Data
Availability statement, then commit and push these metadata changes.

## 4. Archive software release v1.0.0

Connect the GitHub repository in the Zenodo GitHub settings and enable it
before creating the release. Then:

```powershell
git tag -a v1.0.0 -m "Paper reproducibility release v1.0.0"
git push origin v1.0.0
```

Create the GitHub release from tag `v1.0.0`. Zenodo will archive it as a
software record and mint the version DOI.

## 5. Final paper substitutions

Use `docs/paper_integration.md` to replace the software and dataset DOI
placeholders. Add the software DOI to the Zenodo dataset's related identifiers
and add the final article DOI to both records when available.
