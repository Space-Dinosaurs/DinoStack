"""Tests for the fixture_id TSV column (SC2) and header-width guard (SC5).

Covers:
- aggregate() includes fixture_id in both the empty-runs and populated-runs branches
- round-trip: append_row -> read_rows preserves fixture_id; file has 10-col header
- header guard: appending to a 9-col file raises ValueError
- fresh append: nonexistent path gets 10-col header and succeeds
"""
from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from evals.runner.aggregator import aggregate
from evals.runner.tsv_writer import TSV_HEADER, append_row, read_rows


# ---------------------------------------------------------------------------
# Stub helpers
# ---------------------------------------------------------------------------

def _make_fixture(fixture_id: str = "sk-001") -> SimpleNamespace:
    """Minimal stub that satisfies aggregator's fixture.id and fixture.path usage."""
    return SimpleNamespace(
        id=fixture_id,
        description="stub fixture",
        path=Path("/nonexistent/fixture.yaml"),
    )


def _make_manifest() -> SimpleNamespace:
    return SimpleNamespace()


def _per_run_scores(n: int = 3, primary: float = 0.75) -> list[dict]:
    return [{"primary": primary, "status": "ok"} for _ in range(n)]


# ---------------------------------------------------------------------------
# aggregate() - fixture_id propagation
# ---------------------------------------------------------------------------

def test_aggregate_empty_runs_has_fixture_id():
    fixture = _make_fixture("sk-007")
    manifest = _make_manifest()

    with patch("evals.runner.aggregator.compute_fixture_hash", return_value="a" * 64):
        row = aggregate([], fixture, manifest, commit="abc123", component_content_hash="c" * 64)

    assert row["fixture_id"] == "sk-007"
    assert row["status"] == "no_runs"


def test_aggregate_populated_runs_has_fixture_id():
    fixture = _make_fixture("sk-003")
    manifest = _make_manifest()
    scores = _per_run_scores(3, primary=0.8)

    with patch("evals.runner.aggregator.compute_fixture_hash", return_value="b" * 64):
        row = aggregate(scores, fixture, manifest, commit="deadbeef", component_content_hash="d" * 64)

    assert row["fixture_id"] == "sk-003"
    assert row["status"] == "ok"
    assert abs(row["primary_score_median"] - 0.8) < 1e-9


# ---------------------------------------------------------------------------
# Round-trip: append_row -> read_rows
# ---------------------------------------------------------------------------

def _build_row(fixture_id: str, commit: str = "abc123") -> dict:
    return {
        "commit": commit,
        "component_content_hash": "c" * 64,
        "fixture_hash": "f" * 64,
        "fixture_id": fixture_id,
        "primary_score_median": 0.75,
        "primary_score_stdev": 0.05,
        "n_runs": 3,
        "status": "ok",
        "diagnostic_json": json.dumps({"n_runs": 3, "per_run": []}),
        "description": "round-trip test",
    }


def test_fixture_id_roundtrips_via_tsv(tmp_path: Path):
    """Write a row with fixture_id and read it back; verify value and 10-col header."""
    component = "test_component"

    with patch("evals.runner.tsv_writer._RESULTS_DIR", tmp_path):
        append_row(component, _build_row("sk-005"))
        rows = read_rows(component)

    assert len(rows) == 1
    assert rows[0]["fixture_id"] == "sk-005"

    # Verify the on-disk header is 10 columns.
    tsv = tmp_path / f"{component}.tsv"
    header_line = tsv.read_text(encoding="utf-8").splitlines()[0]
    cols = header_line.split("\t")
    assert len(cols) == 10
    assert cols == list(TSV_HEADER)


def test_multiple_rows_all_have_fixture_id(tmp_path: Path):
    component = "multi"
    with patch("evals.runner.tsv_writer._RESULTS_DIR", tmp_path):
        append_row(component, _build_row("sk-001"))
        append_row(component, _build_row("sk-002"))
        rows = read_rows(component)

    assert [r["fixture_id"] for r in rows] == ["sk-001", "sk-002"]


# ---------------------------------------------------------------------------
# Header guard
# ---------------------------------------------------------------------------

_OLD_9_COL_HEADER = "\t".join([
    "commit", "component_content_hash", "fixture_hash",
    "primary_score_median", "primary_score_stdev", "n_runs",
    "status", "diagnostic_json", "description",
])


def test_header_guard_raises_on_9col_file(tmp_path: Path):
    """Appending to a 9-col TSV must raise ValueError naming the column counts."""
    component = "old_schema"
    tsv = tmp_path / f"{component}.tsv"
    tsv.write_text(
        _OLD_9_COL_HEADER + "\n" + "\t".join(["x"] * 9) + "\n",
        encoding="utf-8",
    )

    with patch("evals.runner.tsv_writer._RESULTS_DIR", tmp_path):
        with pytest.raises(ValueError, match="schema mismatch"):
            append_row(component, _build_row("sk-001"))


def test_header_guard_raises_message_mentions_migrate(tmp_path: Path):
    """Error message must name migrate_tsv so the operator knows what to run."""
    component = "old2"
    tsv = tmp_path / f"{component}.tsv"
    tsv.write_text(_OLD_9_COL_HEADER + "\n", encoding="utf-8")

    with patch("evals.runner.tsv_writer._RESULTS_DIR", tmp_path):
        with pytest.raises(ValueError, match="migrate_tsv"):
            append_row(component, _build_row("sk-002"))


def test_fresh_path_writes_10col_header(tmp_path: Path):
    """Appending to a nonexistent path creates the file with the 10-col header."""
    component = "brand_new"
    with patch("evals.runner.tsv_writer._RESULTS_DIR", tmp_path):
        append_row(component, _build_row("sk-010"))
        rows = read_rows(component)

    assert len(rows) == 1
    assert rows[0]["fixture_id"] == "sk-010"
    tsv = tmp_path / f"{component}.tsv"
    header = tsv.read_text(encoding="utf-8").splitlines()[0].split("\t")
    assert len(header) == 10


def test_10col_existing_file_does_not_raise(tmp_path: Path):
    """Appending to an already-10-col file must succeed without raising."""
    component = "current_schema"
    with patch("evals.runner.tsv_writer._RESULTS_DIR", tmp_path):
        append_row(component, _build_row("sk-001"))
        # Second append to same file - must not raise.
        append_row(component, _build_row("sk-002"))
        rows = read_rows(component)

    assert len(rows) == 2
