# Paper integration after publication

Complete these substitutions only after the GitHub repository and Zenodo
records exist.

## Data Availability statement

```text
The source data are publicly available from GME, Terna, the Copernicus Climate
Data Store, Eurostat, ISTAT, and Natural Earth at the locations cited in this
article. Reproducible source code is archived on GitHub and Zenodo at
[SOFTWARE DOI]. The normalized Copernicus input, exact input checksums, result
tables, and figures are archived in the companion Zenodo dataset at
[DATASET DOI]. GME and Terna raw files are not redistributed; they can be
obtained from the providers and verified against the archived SHA-256 manifest.
```

## Repository metadata to update

- Add the GitHub repository URL to `CITATION.cff`.
- Add the dataset DOI to `.zenodo.json` as an `isSupplementedBy` related
  identifier.
- Add the article DOI later as an `isSupplementTo` related identifier.
- Replace `[SOFTWARE DOI]` and `[DATASET DOI]` in the manuscript.
- Use the version-specific software DOI in the reproducibility statement and
  the concept DOI where the paper refers to all future software versions.
