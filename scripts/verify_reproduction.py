"""Verify local inputs and outputs against the validated SHA-256 manifest."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PACKAGE_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_MANIFEST = (
    PACKAGE_ROOT / "reproducibility" / "reference_manifest.json"
)


def sha256(path: Path) -> str:
    """Return the SHA-256 digest for one file."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def row_order_insensitive_sha256(path: Path) -> str:
    """Hash a provider CSV after sorting complete data rows."""

    lines = path.read_bytes().splitlines()
    if not lines:
        return hashlib.sha256(b"").hexdigest()
    canonical = b"\n".join([lines[0], *sorted(lines[1:])]) + b"\n"
    return hashlib.sha256(canonical).hexdigest()


def verify_records(
    records: list[dict[str, object]],
    root: Path,
    category: str,
) -> list[str]:
    """Return human-readable failures for one manifest category."""

    failures: list[str] = []
    for record in records:
        relative = Path(str(record["path"]))
        path = root / relative
        if not path.is_file():
            failures.append(f"{category}: missing {relative.as_posix()}")
            continue
        expected_size = int(record["size_bytes"])
        if path.stat().st_size != expected_size:
            failures.append(
                f"{category}: size mismatch {relative.as_posix()} "
                f"({path.stat().st_size} != {expected_size})"
            )
            continue
        expected_hash = str(record["sha256"])
        actual_hash = sha256(path)
        if actual_hash != expected_hash:
            semantic_hash = record.get("row_order_insensitive_sha256")
            if semantic_hash is not None and (
                row_order_insensitive_sha256(path) == str(semantic_hash)
            ):
                continue
            failures.append(
                f"{category}: SHA-256 mismatch {relative.as_posix()}"
            )
    return failures


def main() -> int:
    """Verify the current project tree and return nonzero on any mismatch."""

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=PACKAGE_ROOT)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--inputs-only", action="store_true")
    mode.add_argument("--outputs-only", action="store_true")
    args = parser.parse_args()

    project_root = args.project_root.resolve()
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    categories: list[tuple[str, Path]] = []
    if not args.outputs_only:
        categories.extend(
            (
                ("scientific_software", PACKAGE_ROOT),
                ("runtime_inputs", project_root),
                ("normalization_provenance", project_root),
            )
        )
    if not args.inputs_only:
        categories.extend(
            (
                ("preprocessing_outputs", project_root),
                ("historical_backtest_outputs", project_root),
            )
        )

    failures: list[str] = []
    checked = 0
    for category, root in categories:
        records = list(manifest[category])
        checked += len(records)
        failures.extend(verify_records(records, root, category))
    if failures:
        print("Reproduction verification failed:")
        print("\n".join(f"  {failure}" for failure in failures))
        return 1
    print(
        f"Reproduction verification passed: {checked} files across "
        f"{len(categories)} categories."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
