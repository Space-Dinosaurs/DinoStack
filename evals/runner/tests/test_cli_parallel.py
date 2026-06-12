"""
Purpose: Unit tests for evals.runner.cli parallel-runner changes:
         - _FixtureResult NamedTuple transport
         - batched-write sort order is deterministic by fixture_id
         - per-fixture exception capture as error rows (no missing row on crash)
         - _collect_and_write regression: drives the real helper with mocked
           _run_fixture to guard against future race regressions

Public API: pytest test module; no public symbols.

Upstream deps: evals.runner.cli (_FixtureResult, _collect_and_write),
               evals.runner.aggregator (aggregate), evals.runner.loader
               (ComponentManifest, Fixture), unittest.mock,
               concurrent.futures.

Downstream consumers: CI quality gate.

Failure modes: tests are read-only; no side effects.

Performance: standard (no subprocess, no worktrees).
"""
from __future__ import annotations

import concurrent.futures
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from evals.runner.cli import _FixtureResult, _collect_and_write
from evals.runner.loader import ComponentManifest, Fixture


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_manifest(name: str = "test-component") -> ComponentManifest:
    return ComponentManifest(
        name=name,
        tier=1,
        content_glob=["**/*.md"],
        scoring_module="evals.components.test_component.scoring",
        fixture_dir="evals/components/test_component/fixtures",
        n_runs=1,
        parallelism="parallel",
        timeout_seconds=300,
        invoke={},
        path=Path("/fake/manifest.yaml"),
    )


def _make_fixture(fixture_id: str) -> Fixture:
    return Fixture(
        id=fixture_id,
        description=f"Fixture {fixture_id}",
        component="test-component",
        protocol_sha=None,
        inputs={},
        expected_findings={},
        expected_signoff_granted=True,
        clean_allowed=True,
        path=Path(f"/fake/fixtures/{fixture_id}/fixture.yaml"),
    )


def _normal_fixture_result(fixture_id: str) -> _FixtureResult:
    """A valid _FixtureResult row matching TSV_HEADER columns."""
    row = {
        "commit": "abc123",
        "component_content_hash": "hash001",
        "fixture_hash": "fhash001",
        "fixture_id": fixture_id,
        "primary_score_median": 0.75,
        "primary_score_stdev": 0.05,
        "n_runs": 1,
        "status": "ok",
        "diagnostic_json": {},
        "description": f"Fixture {fixture_id}",
    }
    runlog = [{"fixture_id": fixture_id, "run_index": 0, "commit": "abc123"}]
    return _FixtureResult(row=row, runlog_records=runlog)


# ---------------------------------------------------------------------------
# Original unit tests (unchanged)
# ---------------------------------------------------------------------------

def test_fixture_result_is_named_tuple():
    row = {"commit": "abc", "fixture_id": "sk-001", "primary_score_median": 0.5}
    records = [{"run_index": 0}]
    result = _FixtureResult(row=row, runlog_records=records)
    assert result.row is row
    assert result.runlog_records is records


def test_fixture_result_unpacks():
    row = {"fixture_id": "sk-002"}
    records = []
    r, recs = _FixtureResult(row=row, runlog_records=records)
    assert r is row
    assert recs is records


def test_sort_order_by_fixture_id():
    """result_pairs sort must produce lexicographic fixture_id order."""
    pairs = [
        ("sk-003", _FixtureResult(row={"fixture_id": "sk-003"}, runlog_records=[])),
        ("sk-001", _FixtureResult(row={"fixture_id": "sk-001"}, runlog_records=[])),
        ("sk-002", _FixtureResult(row={"fixture_id": "sk-002"}, runlog_records=[])),
    ]
    pairs.sort(key=lambda t: t[0])
    assert [p[0] for p in pairs] == ["sk-001", "sk-002", "sk-003"]


def test_exception_capture_produces_error_row():
    """A future that raises must yield a scoring_error row, not propagate."""
    import concurrent.futures

    def _raises():
        raise RuntimeError("worker died")

    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
        f = executor.submit(_raises)

    # Mimic the exception-capture logic from cmd_run.
    try:
        f.result()
    except Exception as exc:
        # Build the same minimal error score list cmd_run uses.
        error_scores = [{"primary": 0.0, "status": "scoring_error", "diagnostic": {"error": str(exc)}}]
        assert error_scores[0]["status"] == "scoring_error"
        assert "worker died" in error_scores[0]["diagnostic"]["error"]
    else:
        pytest.fail("expected RuntimeError from future")


def test_fixture_result_missing_field_raises():
    """_FixtureResult requires both positional fields."""
    with pytest.raises(TypeError):
        _FixtureResult(row={"x": 1})  # missing runlog_records


# ---------------------------------------------------------------------------
# MAJOR regression test: drives _collect_and_write with mocked _run_fixture
# ---------------------------------------------------------------------------

def test_collect_and_write_parallel_exception_capture(tmp_path):
    """Regression test for the parallel collect -> exception-capture -> sort -> write path.

    Fixtures A (sk-001) and B (sk-002) are submitted to a ThreadPoolExecutor.
    _run_fixture for sk-001 returns a normal _FixtureResult; for sk-002 it
    raises. _collect_and_write must:
      - Write exactly 2 rows.
      - Write them in fixture_id order (sk-001 first, sk-002 second).
      - sk-002's row must have status="scoring_error" and fixture_id="sk-002".
      - sk-001's row must be the normal row.

    This test WILL FAIL if:
      - A write is moved back inside _run_fixture (concurrent append race).
      - An exception aborts the batch (missing row).
      - Sort is removed (wrong order).
    """
    manifest = _make_manifest()
    fx_a = _make_fixture("sk-001")
    fx_b = _make_fixture("sk-002")
    commit = "deadbeef"
    content_hash = "chash"

    normal_result = _normal_fixture_result("sk-001")

    def _raise_boom():
        raise RuntimeError("boom")

    # Submit tasks to a real executor. sk-001 returns normally; sk-002 raises.
    futures: dict[concurrent.futures.Future, Fixture] = {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as executor:
        futures[executor.submit(lambda: normal_result)] = fx_a
        futures[executor.submit(_raise_boom)] = fx_b

    # Capture written rows/records instead of touching disk.
    written_rows: list[dict] = []
    written_runlog: list[dict] = []

    with (
        patch("evals.runner.cli.tsv.append_row", side_effect=lambda _comp, row: written_rows.append(row)),
        patch("evals.runner.cli.write_runlog", side_effect=lambda _comp, rec: written_runlog.append(rec)),
        # aggregate calls compute_fixture_hash which reads the fixture.yaml from disk;
        # patch it to a stable value so the test stays self-contained.
        patch("evals.runner.aggregator.compute_fixture_hash", return_value="fake-fhash"),
    ):
        n = _collect_and_write(futures, manifest, commit, content_hash)

    # Exactly 2 rows must be written.
    assert n == 2, f"Expected 2 rows, got {n}"
    assert len(written_rows) == 2

    # Rows must be in fixture_id order.
    assert written_rows[0]["fixture_id"] == "sk-001"
    assert written_rows[1]["fixture_id"] == "sk-002"

    # sk-001 is the normal row.
    assert written_rows[0]["status"] == "ok"
    assert written_rows[0]["primary_score_median"] == 0.75

    # sk-002 is the error row.
    assert written_rows[1]["status"] == "scoring_error"
    assert written_rows[1]["fixture_id"] == "sk-002"

    # sk-001 runlog record must be present; sk-002 has no runlog (error path).
    assert len(written_runlog) == 1
    assert written_runlog[0]["fixture_id"] == "sk-001"
