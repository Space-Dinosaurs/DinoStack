"""Unit tests for evals.auto.runner_shim - aggregation + TSV row parsing."""
from __future__ import annotations

import json
from pathlib import Path

from evals.auto.runner_shim import aggregate_latest


def _write_tsv(path: Path, rows):
    header = [
        "commit", "component_content_hash", "fixture_hash",
        "primary_score_median", "primary_score_stdev", "n_runs",
        "status", "diagnostic_json", "description",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write("\t".join(header) + "\n")
        for r in rows:
            fh.write("\t".join(str(r[c]) for c in header) + "\n")


def _row(median, stdev, cost_per_run=0.0):
    diag = {
        "n_runs": 3,
        "per_run": [
            {"diagnostic": {"cost_usd": cost_per_run}, "primary": median, "status": "ok"}
            for _ in range(3)
        ],
    }
    return {
        "commit": "deadbee",
        "component_content_hash": "x" * 64,
        "fixture_hash": "y" * 64,
        "primary_score_median": median,
        "primary_score_stdev": stdev,
        "n_runs": 3,
        "status": "ok",
        "diagnostic_json": json.dumps(diag, sort_keys=True, separators=(",", ":")),
        "description": "test",
    }


def test_mean_of_medians_and_pooled_stdev(tmp_path: Path):
    # Simulate a component with 3 fixtures and two full baseline runs worth of rows.
    # aggregate_latest should pick the last n_fixtures=3 and compute:
    #   mean of [0.5, 0.9, 0.7] = 0.7
    #   pooled_stdev = sqrt((0.1^2 + 0.0^2 + 0.05^2)/3) ~ 0.0645
    repo = tmp_path
    tsv = repo / "evals" / "results" / "fake.tsv"
    # Older rows (should be ignored because n_fixtures=3 selects the last 3).
    rows = [
        _row(0.0, 0.0),
        _row(0.0, 0.0),
        _row(0.0, 0.0),
        _row(0.5, 0.1),
        _row(0.9, 0.0),
        _row(0.7, 0.05),
    ]
    _write_tsv(tsv, rows)
    out = aggregate_latest(repo, "fake", n_fixtures=3)
    assert abs(out["metric"] - 0.7) < 1e-9
    # Pooled stdev: sqrt((0.01 + 0 + 0.0025) / 3) = sqrt(0.004166...) ~ 0.06455
    assert abs(out["pooled_stdev"] - 0.06454972) < 1e-5


def test_mean_differs_from_median_on_asymmetric_input(tmp_path: Path):
    # Asymmetric fixture scores: [0.5, 0.5, 1.0]
    # mean = (0.5 + 0.5 + 1.0) / 3 = 0.6667, median = 0.5
    # Verifies the aggregation uses mean, not median.
    repo = tmp_path
    tsv = repo / "evals" / "results" / "fake.tsv"
    rows = [_row(0.5, 0.0), _row(0.5, 0.0), _row(1.0, 0.0)]
    _write_tsv(tsv, rows)
    out = aggregate_latest(repo, "fake", n_fixtures=3)
    expected_mean = (0.5 + 0.5 + 1.0) / 3
    assert abs(out["metric"] - expected_mean) < 1e-9, f"expected mean ~{expected_mean}, got {out['metric']}"
    assert abs(out["metric"] - 0.5) > 1e-6, "metric should not equal the median (0.5)"


def test_cost_summed_from_per_run_diagnostics(tmp_path: Path):
    repo = tmp_path
    tsv = repo / "evals" / "results" / "fake.tsv"
    rows = [_row(0.5, 0.0, cost_per_run=0.1), _row(0.5, 0.0, cost_per_run=0.2)]
    _write_tsv(tsv, rows)
    out = aggregate_latest(repo, "fake", n_fixtures=2)
    # 3 runs per row * (0.1 + 0.2) = 0.9
    assert abs(out["cost_usd"] - 0.9) < 1e-9


def test_raises_if_tsv_too_short(tmp_path: Path):
    repo = tmp_path
    tsv = repo / "evals" / "results" / "fake.tsv"
    _write_tsv(tsv, [_row(0.5, 0.0)])
    try:
        aggregate_latest(repo, "fake", n_fixtures=3)
    except ValueError as e:
        assert "expected at least 3" in str(e)
    else:
        raise AssertionError("expected ValueError")


# ---------------------------------------------------------------------------
# New-path tests: expected_commit filter + assertions (10-col rows with fixture_id)
# ---------------------------------------------------------------------------

def _write_tsv_10col(path: Path, rows):
    """Write a 10-column TSV including fixture_id."""
    header = [
        "commit", "component_content_hash", "fixture_hash", "fixture_id",
        "primary_score_median", "primary_score_stdev", "n_runs",
        "status", "diagnostic_json", "description",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        fh.write("\t".join(header) + "\n")
        for r in rows:
            fh.write("\t".join(str(r[c]) for c in header) + "\n")


def _row10(median, stdev, commit="abc123", fixture_id="sk-001", cost_per_run=0.0):
    """Build a 10-col TSV row dict."""
    diag = {
        "n_runs": 3,
        "per_run": [
            {"diagnostic": {"cost_usd": cost_per_run}, "primary": median, "status": "ok"}
            for _ in range(3)
        ],
    }
    return {
        "commit": commit,
        "component_content_hash": "x" * 64,
        "fixture_hash": "y" * 64,
        "fixture_id": fixture_id,
        "primary_score_median": median,
        "primary_score_stdev": stdev,
        "n_runs": 3,
        "status": "ok",
        "diagnostic_json": json.dumps(diag, sort_keys=True, separators=(",", ":")),
        "description": "test",
    }


def test_expected_commit_happy_path(tmp_path: Path):
    """Happy path: n_fixtures rows sharing one commit with distinct fixture_ids.

    Interleaved rows from a second commit must be excluded by the filter.
    aggregate_latest(expected_commit=...) returns the correct aggregate over
    the target-commit rows only.
    """
    repo = tmp_path
    tsv = repo / "evals" / "results" / "fake.tsv"
    target_commit = "aaa111"
    other_commit = "bbb222"

    rows = [
        # Rows from an earlier run (other_commit) - must be excluded.
        _row10(0.0, 0.0, commit=other_commit, fixture_id="sk-001"),
        _row10(0.0, 0.0, commit=other_commit, fixture_id="sk-002"),
        _row10(0.0, 0.0, commit=other_commit, fixture_id="sk-003"),
        # Target-commit rows interleaved with older rows.
        _row10(0.5, 0.1, commit=target_commit, fixture_id="sk-001"),
        _row10(0.9, 0.0, commit=target_commit, fixture_id="sk-002"),
        _row10(0.7, 0.05, commit=target_commit, fixture_id="sk-003"),
    ]
    _write_tsv_10col(tsv, rows)

    out = aggregate_latest(repo, "fake", n_fixtures=3, expected_commit=target_commit)

    # Aggregation over the three target rows: mean([0.5, 0.9, 0.7]) = 0.7
    assert abs(out["metric"] - 0.7) < 1e-9, f"expected 0.7, got {out['metric']}"
    assert len(out["rows"]) == 3
    # All returned rows belong to the target commit.
    for r in out["rows"]:
        assert r["commit"] == target_commit


def test_expected_commit_wrong_count_too_few(tmp_path: Path):
    """Wrong count (n_fixtures - 1) raises ValueError."""
    repo = tmp_path
    tsv = repo / "evals" / "results" / "fake.tsv"
    target_commit = "aaa111"

    rows = [
        _row10(0.5, 0.0, commit=target_commit, fixture_id="sk-001"),
        _row10(0.9, 0.0, commit=target_commit, fixture_id="sk-002"),
        # Only 2 rows for target_commit; n_fixtures=3 should raise.
    ]
    _write_tsv_10col(tsv, rows)

    try:
        aggregate_latest(repo, "fake", n_fixtures=3, expected_commit=target_commit)
    except ValueError as e:
        msg = str(e)
        assert "expected exactly 3" in msg, f"unexpected error message: {msg}"
        assert "got 2" in msg, f"unexpected error message: {msg}"
    else:
        raise AssertionError("expected ValueError for wrong count (too few)")


def test_expected_commit_wrong_count_too_many(tmp_path: Path):
    """Wrong count (n_fixtures + 1) raises ValueError."""
    repo = tmp_path
    tsv = repo / "evals" / "results" / "fake.tsv"
    target_commit = "aaa111"

    rows = [
        _row10(0.5, 0.0, commit=target_commit, fixture_id="sk-001"),
        _row10(0.9, 0.0, commit=target_commit, fixture_id="sk-002"),
        _row10(0.7, 0.0, commit=target_commit, fixture_id="sk-003"),
        _row10(0.6, 0.0, commit=target_commit, fixture_id="sk-004"),
        # 4 rows for target_commit; n_fixtures=3 should raise.
    ]
    _write_tsv_10col(tsv, rows)

    try:
        aggregate_latest(repo, "fake", n_fixtures=3, expected_commit=target_commit)
    except ValueError as e:
        msg = str(e)
        assert "expected exactly 3" in msg, f"unexpected error message: {msg}"
        assert "got 4" in msg, f"unexpected error message: {msg}"
    else:
        raise AssertionError("expected ValueError for wrong count (too many)")


def test_expected_commit_duplicate_fixture_id(tmp_path: Path):
    """n_fixtures rows for the commit but one fixture_id repeated raises ValueError."""
    repo = tmp_path
    tsv = repo / "evals" / "results" / "fake.tsv"
    target_commit = "aaa111"

    rows = [
        _row10(0.5, 0.0, commit=target_commit, fixture_id="sk-001"),
        _row10(0.9, 0.0, commit=target_commit, fixture_id="sk-002"),
        # sk-001 repeated instead of sk-003 - duplicate fixture_id.
        _row10(0.7, 0.0, commit=target_commit, fixture_id="sk-001"),
    ]
    _write_tsv_10col(tsv, rows)

    try:
        aggregate_latest(repo, "fake", n_fixtures=3, expected_commit=target_commit)
    except ValueError as e:
        msg = str(e)
        assert "duplicate fixture_id" in msg, f"unexpected error message: {msg}"
        assert "sk-001" in msg, f"duplicate id not named in error: {msg}"
    else:
        raise AssertionError("expected ValueError for duplicate fixture_id")
