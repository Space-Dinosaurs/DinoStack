"""
Purpose: Append rows to a per-component TSV ledger with a fixed 10-column schema,
         creating the file with a header on first write.

Public API: TSV_HEADER (tuple[str, ...]), append_row(component: str, row: dict) -> Path,
            read_rows(component: str) -> list[dict], tsv_path(component: str) -> Path.

Upstream deps: stdlib csv, pathlib, json (diagnostic_json is serialized by the caller
               or, for dict values, by append_row itself).

Downstream consumers: evals.runner.cli, evals.runner.aggregator.

Failure modes: raises ValueError if the row has unknown or missing columns.
               Raises ValueError on header-width mismatch between an existing file's
               on-disk header and TSV_HEADER - run `python -m evals.auto.migrate_tsv`
               to migrate old files to the current 10-column schema (columns: commit,
               component_content_hash, fixture_hash, fixture_id, primary_score_median,
               primary_score_stdev, n_runs, status, diagnostic_json, description).
               Not safe for concurrent writers; serialize at the process level.

Performance: standard; append-only, small rows.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path

_RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"

TSV_HEADER: tuple[str, ...] = (
    "commit",
    "component_content_hash",
    "fixture_hash",
    "fixture_id",
    "primary_score_median",
    "primary_score_stdev",
    "n_runs",
    "status",
    "diagnostic_json",
    "description",
)


def tsv_path(component: str) -> Path:
    _RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    return _RESULTS_DIR / f"{component}.tsv"


def _ondisk_header(path: Path) -> tuple[str, ...] | None:
    """Read the first line of an existing TSV and return it as a tuple of column names.

    Returns None if the file does not exist, is empty, or its first line is empty.
    """
    if not path.exists() or path.stat().st_size == 0:
        return None
    with path.open("r", encoding="utf-8", newline="") as fh:
        first_line = fh.readline()
    stripped = first_line.rstrip("\r\n")
    if not stripped:
        return None
    return tuple(stripped.split("\t"))


def _normalize_row(row: dict) -> list[str]:
    extra = set(row) - set(TSV_HEADER)
    missing = set(TSV_HEADER) - set(row)
    if extra:
        raise ValueError(f"Unexpected TSV columns: {sorted(extra)}")
    if missing:
        raise ValueError(f"Missing TSV columns: {sorted(missing)}")
    out: list[str] = []
    for col in TSV_HEADER:
        val = row[col]
        if col == "diagnostic_json" and not isinstance(val, str):
            val = json.dumps(val, sort_keys=True, separators=(",", ":"))
        out.append(str(val))
    return out


def append_row(component: str, row: dict) -> Path:
    path = tsv_path(component)
    existing = _ondisk_header(path)
    if existing is None:
        # New file or empty file - write header then the row.
        with path.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
            writer.writerow(TSV_HEADER)
            writer.writerow(_normalize_row(row))
    else:
        if existing != TSV_HEADER:
            raise ValueError(
                f"TSV schema mismatch for '{component}': on-disk header has "
                f"{len(existing)} columns, expected {len(TSV_HEADER)}. "
                f"Run `python -m evals.auto.migrate_tsv` to migrate the file."
            )
        with path.open("a", encoding="utf-8", newline="") as fh:
            writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
            writer.writerow(_normalize_row(row))
    return path


def read_rows(component: str) -> list[dict]:
    path = tsv_path(component)
    if not path.exists():
        return []
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        return [dict(r) for r in reader]
