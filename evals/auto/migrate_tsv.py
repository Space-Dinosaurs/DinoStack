"""
Purpose: One-time, idempotent migration that brings existing result TSVs to the
         v2 schema. Operator-run only; never imported or invoked by the loop or
         runner.

Public API:
    migrate(results_dir: Path | None = None) -> dict
        Migrate all *.tsv files under results_dir (default: evals/results/).
        Returns a summary dict with keys "migrated", "skipped_v2",
        "skipped_absent", listing filenames in each category.
    main() -> None
        CLI entry point; calls migrate() and prints per-file lines, then exits 0.

Upstream deps:
    stdlib: pathlib, csv, time, sys
    evals.runner.tsv_writer: TSV_HEADER, _ondisk_header
    evals.auto.loop: LEDGER_HEADER

Downstream consumers:
    Operator-run setup step only. Nothing imports this module at runtime.

Failure modes:
    Idempotent - already-v2 files are skipped with no writes.
    Archives before rewriting - existing content is always preserved first.
    Never replays old data rows - the new file starts header-only (v2 rows
    accumulate naturally on the next harness run).
    Never overwrites a populated archive - asserts uniqueness before writing.
    Side-effecting: moves/creates files. Safe to re-run; re-run is a no-op
    when all files are already v2.

Performance: standard; operates on a handful of small TSV files.
"""
from __future__ import annotations

import csv
import sys
import time
from pathlib import Path

from evals.auto.loop import LEDGER_HEADER
from evals.runner.tsv_writer import TSV_HEADER, _ondisk_header

_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"
_LEDGER_FILENAME = "auto-harness.tsv"


def _archive_path(results_dir: Path, filename: str) -> Path:
    """Return a collision-free archive path using a UTC timestamp."""
    archive_dir = results_dir / "_archive"
    archive_dir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    stem = Path(filename).stem
    candidate = archive_dir / f"{stem}.{ts}.tsv"
    # Guard: never overwrite an existing archive entry.
    if candidate.exists():
        # Append a sub-second counter to ensure uniqueness.
        counter = 0
        while True:
            counter += 1
            candidate = archive_dir / f"{stem}.{ts}.{counter:03d}.tsv"
            if not candidate.exists():
                break
    return candidate


def _target_header(filename: str) -> tuple[str, ...]:
    """Return the target header tuple for a given filename."""
    if filename == _LEDGER_FILENAME:
        return LEDGER_HEADER
    return TSV_HEADER


def _write_header_only(path: Path, header: tuple[str, ...]) -> None:
    """Write a new file containing only the header row."""
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
        writer.writerow(header)


def migrate(results_dir: Path | None = None) -> dict:
    """Migrate all *.tsv files in results_dir to their v2 schema.

    Returns a dict with keys:
        "migrated"       - list of (filename, old_ncols, new_ncols)
        "skipped_v2"     - list of filename strings already at target schema
        "skipped_absent" - list of filename strings missing or empty
    """
    if results_dir is None:
        results_dir = _RESULTS_DIR

    results_dir = Path(results_dir)

    summary: dict[str, list] = {
        "migrated": [],
        "skipped_v2": [],
        "skipped_absent": [],
    }

    tsv_files = sorted(results_dir.glob("*.tsv"))

    for tsv_file in tsv_files:
        filename = tsv_file.name
        ondisk = _ondisk_header(tsv_file)

        if ondisk is None:
            # Missing or empty - no-op; the first real run creates it fresh.
            print(f"skip {filename} (absent/empty)")
            summary["skipped_absent"].append(filename)
            continue

        target = _target_header(filename)

        if ondisk == target:
            print(f"skip {filename} (already v2)")
            summary["skipped_v2"].append(filename)
            continue

        # Migration needed: archive existing file then write a header-only v2 file.
        archive = _archive_path(results_dir, filename)
        assert not archive.exists(), f"archive collision: {archive}"
        tsv_file.rename(archive)
        _write_header_only(tsv_file, target)
        old_n = len(ondisk)
        new_n = len(target)
        print(f"migrated {filename} ({old_n}cols->{new_n}cols)")
        summary["migrated"].append((filename, old_n, new_n))

    return summary


def main() -> None:
    migrate()
    sys.exit(0)


if __name__ == "__main__":
    main()
