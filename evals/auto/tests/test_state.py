"""Unit tests for evals.auto.state - atomic write + round-trip."""
from __future__ import annotations

from pathlib import Path

from evals.auto.state import load, new_state, save


def test_new_state_has_required_fields():
    s = new_state(
        branch="auto-harness/skeptic-X",
        baseline=0.5,
        component="skeptic",
        max_iterations=5,
        time_budget_sec=60,
        cost_budget_usd=1.0,
    )
    for k in ("branch", "baseline_metric", "component", "max_iterations",
              "time_budget_sec", "cost_budget_usd", "iteration",
              "last_kept_metric", "keeps", "reverts", "history"):
        assert k in s
    assert s["iteration"] == 0
    assert s["last_kept_metric"] == 0.5


def test_save_and_load_roundtrip(tmp_path: Path):
    path = tmp_path / "state.json"
    s = new_state(
        branch="b", baseline=0.7, component="skeptic",
        max_iterations=3, time_budget_sec=30, cost_budget_usd=1.0,
    )
    s["history"].append({"iteration": 1, "decision": "keep", "delta": "0.05", "metric_after": 0.75})
    save(path, s)
    s2 = load(path)
    assert s2["branch"] == "b"
    assert s2["history"][0]["decision"] == "keep"
    assert s2["baseline_metric"] == 0.7


def test_save_is_atomic_leaves_no_tempfile(tmp_path: Path):
    path = tmp_path / "state.json"
    s = new_state(
        branch="b", baseline=0.1, component="skeptic",
        max_iterations=1, time_budget_sec=1, cost_budget_usd=0.1,
    )
    save(path, s)
    save(path, s)
    # Only the state file should remain; no .state.*.tmp leftovers.
    leftover = [p for p in tmp_path.iterdir() if p.name.startswith(".state.")]
    assert leftover == []
