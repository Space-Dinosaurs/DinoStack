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


def test_median_of_medians_and_pooled_stdev(tmp_path: Path):
    # Simulate a component with 3 fixtures and two full baseline runs worth of rows.
    # aggregate_latest should pick the last n_fixtures=3 and compute:
    #   median of [0.5, 0.9, 0.7] = 0.7
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
