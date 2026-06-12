"""Tests for evals.auto.migrate_tsv (SC5 v2 migration).

Covers:
- 9-col component TSV -> archives old file, recreates with 10-col TSV_HEADER only
- 14-col auto-harness.tsv -> archives old file, recreates with 17-col LEDGER_HEADER
  (no fixture_id in ledger header)
- idempotency: second migrate() call skips already-v2 files, no new archive
- already-v2 component file -> skipped, not archived
- absent/empty file -> no-op, no crash
- archive-collision guard: monkeypatched timestamp forces collision; assert no
  silent overwrite (counter suffix prevents it, second archive is distinctly named)
"""
from __future__ import annotations

import csv
from pathlib import Path
from unittest.mock import patch

import pytest

from evals.auto.loop import LEDGER_HEADER
from evals.auto.migrate_tsv import _LEDGER_FILENAME, migrate
from evals.runner.tsv_writer import TSV_HEADER


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_OLD_9_COL = (
    "commit", "component_content_hash", "fixture_hash",
    "primary_score_median", "primary_score_stdev", "n_runs",
    "status", "diagnostic_json", "description",
)

_OLD_14_COL = (
    "timestamp_utc", "component", "branch", "iteration",
    "base_commit", "proposed_commit", "baseline_metric", "new_metric",
    "delta", "pooled_stdev", "decision", "reason",
    "overfitting_verdict", "cost_usd_cumulative",
)


def _write_tsv(path: Path, header: tuple[str, ...], rows: list[tuple[str, ...]] | None = None) -> None:
    """Write a TSV with the given header and optional data rows."""
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.writer(fh, delimiter="\t", lineterminator="\n")
        writer.writerow(header)
        for row in (rows or []):
            writer.writerow(row)


def _read_header(path: Path) -> tuple[str, ...]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        first_line = fh.readline().rstrip("\r\n")
    return tuple(first_line.split("\t"))


def _read_all_lines(path: Path) -> list[str]:
    return path.read_text(encoding="utf-8").splitlines()


# ---------------------------------------------------------------------------
# 9-col component TSV -> migrate to 10-col TSV_HEADER
# ---------------------------------------------------------------------------

def test_9col_component_migrated_to_10col(tmp_path: Path):
    """9-col component file is archived and replaced with a 10-col header-only file."""
    tsv = tmp_path / "skeptic.tsv"
    _write_tsv(tsv, _OLD_9_COL, rows=[("x",) * 9])
    old_content = tsv.read_text(encoding="utf-8")

    result = migrate(results_dir=tmp_path)

    assert ("skeptic.tsv", 9, 10) in result["migrated"]

    # Archive created with old content.
    archive_dir = tmp_path / "_archive"
    archives = list(archive_dir.glob("skeptic.*.tsv"))
    assert len(archives) == 1
    assert archives[0].read_text(encoding="utf-8") == old_content

    # New file has exactly the 10-col TSV_HEADER and no data rows.
    assert tsv.exists()
    lines = _read_all_lines(tsv)
    assert len(lines) == 1, f"Expected header-only file, got {len(lines)} lines"
    assert _read_header(tsv) == TSV_HEADER
    assert len(TSV_HEADER) == 10


# ---------------------------------------------------------------------------
# 14-col auto-harness.tsv -> migrate to 17-col LEDGER_HEADER
# ---------------------------------------------------------------------------

def test_14col_ledger_migrated_to_17col(tmp_path: Path):
    """14-col auto-harness.tsv is archived and replaced with a 17-col header-only file."""
    tsv = tmp_path / _LEDGER_FILENAME
    _write_tsv(tsv, _OLD_14_COL, rows=[("v",) * 14])
    old_content = tsv.read_text(encoding="utf-8")

    result = migrate(results_dir=tmp_path)

    assert (_LEDGER_FILENAME, 14, 17) in result["migrated"]

    archive_dir = tmp_path / "_archive"
    archives = list(archive_dir.glob("auto-harness.*.tsv"))
    assert len(archives) == 1
    assert archives[0].read_text(encoding="utf-8") == old_content

    assert tsv.exists()
    lines = _read_all_lines(tsv)
    assert len(lines) == 1
    assert _read_header(tsv) == LEDGER_HEADER
    assert len(LEDGER_HEADER) == 17

    # Ledger must NOT have a fixture_id column.
    assert "fixture_id" not in LEDGER_HEADER


# ---------------------------------------------------------------------------
# Idempotency: second run is a no-op
# ---------------------------------------------------------------------------

def test_idempotent_second_run_skips(tmp_path: Path):
    """Running migrate twice: second run skips all files, no new archive."""
    tsv = tmp_path / "conductor.tsv"
    _write_tsv(tsv, _OLD_9_COL, rows=[("y",) * 9])

    migrate(results_dir=tmp_path)
    archive_dir = tmp_path / "_archive"
    archives_after_first = set(archive_dir.glob("conductor.*.tsv"))
    assert len(archives_after_first) == 1

    result2 = migrate(results_dir=tmp_path)

    # Second run skips the now-v2 file.
    assert "conductor.tsv" in result2["skipped_v2"]
    assert result2["migrated"] == []

    # No additional archive was created.
    archives_after_second = set(archive_dir.glob("conductor.*.tsv"))
    assert archives_after_second == archives_after_first


# ---------------------------------------------------------------------------
# Already-v2 file -> skipped, not archived
# ---------------------------------------------------------------------------

def test_already_v2_component_not_archived(tmp_path: Path):
    """A file already at TSV_HEADER is skipped without creating an archive."""
    tsv = tmp_path / "debugger.tsv"
    _write_tsv(tsv, TSV_HEADER)

    result = migrate(results_dir=tmp_path)

    assert "debugger.tsv" in result["skipped_v2"]
    assert result["migrated"] == []
    archive_dir = tmp_path / "_archive"
    assert not archive_dir.exists() or not list(archive_dir.glob("debugger.*.tsv"))


def test_already_v2_ledger_not_archived(tmp_path: Path):
    """auto-harness.tsv at LEDGER_HEADER is skipped without creating an archive."""
    tsv = tmp_path / _LEDGER_FILENAME
    _write_tsv(tsv, LEDGER_HEADER)

    result = migrate(results_dir=tmp_path)

    assert _LEDGER_FILENAME in result["skipped_v2"]
    assert result["migrated"] == []


# ---------------------------------------------------------------------------
# Absent / empty file -> no-op, no crash
# ---------------------------------------------------------------------------

def test_absent_file_no_crash(tmp_path: Path):
    """Results dir with no TSVs returns empty summary without error."""
    result = migrate(results_dir=tmp_path)
    assert result == {"migrated": [], "skipped_v2": [], "skipped_absent": []}


def test_empty_file_skipped(tmp_path: Path):
    """A zero-byte TSV file is treated as absent/empty and skipped."""
    tsv = tmp_path / "empty.tsv"
    tsv.write_bytes(b"")

    result = migrate(results_dir=tmp_path)

    assert "empty.tsv" in result["skipped_absent"]
    assert result["migrated"] == []


# ---------------------------------------------------------------------------
# Archive-collision guard: monkeypatched timestamp forces collision
# ---------------------------------------------------------------------------

def test_archive_collision_guard_uniquifies(tmp_path: Path):
    """When the timestamp is fixed, a second migration file gets a counter suffix
    rather than silently overwriting the first archive."""
    # Freeze timestamp so both archives would get the same name without the guard.
    fixed_ts = "20240101T000000Z"

    with patch("evals.auto.migrate_tsv.time") as mock_time:
        mock_time.strftime.return_value = fixed_ts
        mock_time.gmtime.return_value = None  # value unused; strftime is mocked

        # First migration.
        tsv1 = tmp_path / "skeptic.tsv"
        _write_tsv(tsv1, _OLD_9_COL, rows=[("a",) * 9])
        migrate(results_dir=tmp_path)

        # Restore the file to old schema so a second migration is triggered.
        _write_tsv(tsv1, _OLD_9_COL, rows=[("b",) * 9])
        migrate(results_dir=tmp_path)

    archive_dir = tmp_path / "_archive"
    archives = sorted(archive_dir.glob("skeptic.*.tsv"))
    # Two distinct archives must exist; neither overwrote the other.
    assert len(archives) == 2, f"Expected 2 archives, found: {[a.name for a in archives]}"
    # One has the fixed timestamp; the other has a counter suffix.
    names = [a.name for a in archives]
    assert f"skeptic.{fixed_ts}.tsv" in names
    assert any(n != f"skeptic.{fixed_ts}.tsv" for n in names)
