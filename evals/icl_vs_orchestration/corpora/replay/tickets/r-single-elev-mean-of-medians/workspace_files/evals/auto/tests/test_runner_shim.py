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


def test_mean_differs_from_median_on_asymmetric_input(tmp_path: Path):
    """Asymmetric input where mean (0.6667) differs from median (0.5)."""
    from evals.auto.runner_shim import aggregate_latest
    tsv = tmp_path / "evals" / "results" / "fake.tsv"
    rows = [_row(0.5, 0.0), _row(0.5, 0.0), _row(1.0, 0.0)]
    _write_tsv(tsv, rows)
    out = aggregate_latest(tmp_path, "fake", n_fixtures=3)
    expected_mean = (0.5 + 0.5 + 1.0) / 3  # ~0.6667
    assert abs(out["metric"] - expected_mean) < 1e-9
    # Hard guard: must NOT equal median (0.5)
    assert abs(out["metric"] - 0.5) > 1e-6


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
