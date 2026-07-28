# GitHub and Zenodo publication checklist

Complete these items when the manuscript and repository identity are final:

Follow `docs/github_zenodo_release.md` in order.

- [ ] Choose the final GitHub owner and create the repository
      `italian-electricity-market-cfd`.
- [ ] Replace any repository-specific Zenodo metadata and add the GitHub URL to
      `CITATION.cff`.
- [ ] Add ORCID and affiliation to `CITATION.cff` and `.zenodo.json`.
- [ ] Keep GME and Terna raw files out of GitHub and Zenodo.
- [ ] Build the separate Zenodo dataset deposit with
      `scripts/build_zenodo_data_deposit.py`.
- [ ] Run the complete data acquisition, preprocessing, and historical
      backtest workflow on a clean environment.
- [ ] Run `scripts/verify_reproduction.py` with no mismatches.
- [ ] Run `scripts/verify_manuscript_consistency.py --manuscript <main.tex>`.
- [ ] Archive the exact source manifest, retrieval metadata, software version,
      and commit hash used for the Zenodo release.
- [ ] Publish the Zenodo dataset record and insert its DOI in the paper.
- [ ] Add the final article DOI and journal citation to `CITATION.cff` and
      `.zenodo.json` when available.
- [ ] Tag the GitHub release as `v1.0.0` and let Zenodo archive the software.
