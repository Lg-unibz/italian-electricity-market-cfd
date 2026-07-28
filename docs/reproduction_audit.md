# Reproduction audit

Audit date: 2026-07-28

Reference environment:

- Windows 11;
- Python 3.14.0;
- NumPy 2.5.0;
- pandas 3.0.4;
- Matplotlib 3.11.0;
- seaborn 0.13.2;
- pyproj 3.7.2.

Verified evidence:

- 26 copied scientific source, runner, and research-document files were
  byte-identical to the internal research repository;
- the public package, using the same local raw inputs, regenerated all 21
  preprocessing files with identical SHA-256 hashes;
- it regenerated all 20 historical tables and 8 paper figures with identical
  SHA-256 hashes;
- the full reference verifier passed for 140 software, input, provenance, and
  output files;
- the manuscript consistency verifier passed 317 checks covering every paper
  figure reference, static quantitative table, regional row, robustness flow,
  and headline numerical claim.
- the historical Terna downloader reproduced all 20 annual capacity and
  production files semantically; 14 were byte-identical and six contained the
  same complete row set in a different provider-return order.

Reference results:

- selected Copernicus technology: `ic2_5hh100e`;
- `K_P50`: 91.63795919934368 real-2024 EUR/MWh;
- `K_P25`: 98.6846843409995 real-2024 EUR/MWh;
- annualized cost: 178395.1046661212 real-2024 EUR/MW-year.

The authoritative per-file evidence is stored in
`reproducibility/reference_manifest.json`. Re-run both verification scripts
after any change to scientific code, result tables, figures, or the manuscript.
