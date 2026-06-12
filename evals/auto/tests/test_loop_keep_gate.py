"""
Tests for the loop keep gate (unit L): pairing, stats.keep_decision wiring,
ledger columns, and advance-on-keep behavior in _one_iteration + run().

Monkeypatches runner_shim.run_component and runner_shim.aggregate_latest to
drive _one_iteration without any subprocess or filesystem dependency beyond
a temporary directory for git ops and the ledger.
"""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Any, Dict
from unittest.mock import patch

import pytest

from evals.auto import loop as loop_mod
from evals.auto.loop import (
    LEDGER_HEADER,
    LoopConfig,
    _one_iteration,
    _append_ledger_row,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_rows(fixture_ids: list[str], scores: list[float]) -> list[dict]:
    """Build minimal TSV-style dicts for pair_deltas."""
    return [
        {"fixture_id": fid, "primary_score_median": str(score)}
        for fid, score in zip(fixture_ids, scores)
    ]


def _read_ledger(path: Path) -> list[dict]:
    with path.open("r", encoding="utf-8", newline="") as fh:
        reader = csv.DictReader(fh, delimiter="\t")
        return list(reader)


def _base_cfg(tmp_path: Path, baseline_rows: list[dict]) -> LoopConfig:
    """Minimal LoopConfig wired to tmp_path as repo_root."""
    return LoopConfig(
        repo_root=tmp_path,
        component="skeptic",
        component_cfg={
            "editable": ["content/agents/skeptic.md"],
            "locked": [],
            "max_edit_loc": 20,
        },
        max_iterations=5,
        time_budget_sec=3600,
        cost_budget_usd=10.0,
        n_fixtures=len(baseline_rows) if baseline_rows else 5,
        baseline_metric=0.50,
        baseline_pooled_stdev=0.05,
        baseline_rows=baseline_rows,
    )


# Canned editor response that produces a valid (non-empty) diff.
_VALID_DIFF = """\
--- a/content/agents/skeptic.md
+++ b/content/agents/skeptic.md
@@ -1,3 +1,4 @@
 line one
+added line
 line two
 line three
"""

_VALID_EDITOR_RESULT = {
    "ok": True,
    "text": (
        "```diff\n" + _VALID_DIFF + "```\n"
        "Overfitting Rule verdict: no because this improves clarity\n"
    ),
    "cost_usd": 0.01,
    "returncode": 0,
    "stderr": "",
}

_VALID_APPLY_RESULT = {"ok": True, "reason": "", "paths": ["content/agents/skeptic.md"]}

FIXTURE_IDS = [f"sk-{i:03d}" for i in range(1, 8)]  # 7 fixtures for clear signal

_BASELINE_SCORES = [0.50, 0.48, 0.52, 0.47, 0.51, 0.49, 0.50]
_IMPROVED_SCORES = [0.72, 0.71, 0.73, 0.70, 0.74, 0.72, 0.71]  # +>0.20 per fixture
_FLAT_SCORES     = [0.50, 0.48, 0.52, 0.47, 0.51, 0.49, 0.50]  # no change

_BASELINE_ROWS = _make_rows(FIXTURE_IDS, _BASELINE_SCORES)
_IMPROVED_ROWS = _make_rows(FIXTURE_IDS, _IMPROVED_SCORES)
_FLAT_ROWS     = _make_rows(FIXTURE_IDS, _FLAT_SCORES)


def _run_component_ok(head_commit: str = "abc123") -> dict:
    return {
        "ok": True,
        "stdout": "",
        "stderr": "",
        "returncode": 0,
        "cost_usd": 0.0,
        "head_commit": head_commit,
    }


def _agg(rows: list[dict], metric: float | None = None) -> dict:
    if metric is None:
        scores = [float(r["primary_score_median"]) for r in rows]
        metric = sum(scores) / len(scores)
    return {
        "metric": metric,
        "pooled_stdev": 0.05,
        "rows": rows,
        "cost_usd": 0.0,
    }


# ---------------------------------------------------------------------------
# git_ops stubs - _one_iteration calls current_branch, commit_all, head_sha,
# reset_hard. We stub them all so no actual git repo is required.
# ---------------------------------------------------------------------------

class _FakeGitOps:
    """Namespace of git_ops replacements."""

    @staticmethod
    def current_branch(_repo_root):
        return "auto-harness/skeptic-test"

    @staticmethod
    def commit_all(_repo_root, _msg):
        return "proposed_sha_001"

    @staticmethod
    def head_sha(_repo_root):
        return "head_sha_after_keep"

    @staticmethod
    def reset_hard(_repo_root, _sha):
        pass


# apply_mod stubs
class _FakeApply:
    @staticmethod
    def extract_diff(text):
        if "```diff" in text:
            start = text.index("```diff") + len("```diff\n")
            end = text.index("```\n", start)
            return text[start:end]
        return ""

    @staticmethod
    def validate_paths(diff, *, editable, locked):
        return {"ok": True, "reason": "", "paths": ["content/agents/skeptic.md"]}

    @staticmethod
    def count_changed_loc(diff):
        return 1

    @staticmethod
    def apply_diff(_repo_root, _diff):
        return {"ok": True, "reason": "", "paths": []}

    @staticmethod
    def normalise_heading(line):
        return line.lower().lstrip("#").strip()


# editor_mod stubs
def _fake_load_program_template():
    return "{{COMPONENT}}"

def _fake_build_brief(template, ctx):
    return template

def _fake_spawn_editor(_repo_root, _brief, *, timeout_sec, model):
    return _VALID_EDITOR_RESULT


# overfitting stub
def _fake_parse_verdict(text, *, diff=""):
    return {"verdict": "pass", "reason": "no because stub"}


# state_mod stubs (no state file in these tests)
class _FakeStateMod:
    @staticmethod
    def new_state(**kwargs): return {}
    @staticmethod
    def save(_path, _st): pass
    @staticmethod
    def load(_path): return {}


# ---------------------------------------------------------------------------
# Test: keep decision when improvement is clear
# ---------------------------------------------------------------------------

def test_keep_on_clear_improvement(tmp_path):
    """Clear per-fixture improvement -> decision='keep', ledger cols populated."""
    cfg = _base_cfg(tmp_path, _BASELINE_ROWS)

    with (
        patch.object(loop_mod, "git_ops", _FakeGitOps),
        patch.object(loop_mod.apply_mod, "extract_diff", _FakeApply.extract_diff),
        patch.object(loop_mod.apply_mod, "validate_paths", _FakeApply.validate_paths),
        patch.object(loop_mod.apply_mod, "count_changed_loc", _FakeApply.count_changed_loc),
        patch.object(loop_mod.apply_mod, "apply_diff", _FakeApply.apply_diff),
        patch.object(loop_mod.editor_mod, "load_program_template", _fake_load_program_template),
        patch.object(loop_mod.editor_mod, "build_brief", _fake_build_brief),
        patch.object(loop_mod.editor_mod, "spawn_editor", _fake_spawn_editor),
        patch.object(loop_mod.overfit, "parse_verdict", _fake_parse_verdict),
        patch.object(loop_mod, "_normalise_headings", lambda t: t),
        patch("evals.auto.runner_shim.run_component", return_value=_run_component_ok("commit_v1")),
        patch("evals.auto.runner_shim.aggregate_latest", return_value=_agg(_IMPROVED_ROWS)),
    ):
        out = _one_iteration(
            cfg,
            iteration=1,
            base_metric=0.50,
            base_pooled_stdev=0.05,
            base_commit="base_sha_001",
            cumulative_cost=0.0,
            base_rows=_BASELINE_ROWS,
        )

    assert out["decision"] == "keep", f"expected keep, got {out['decision']}: {out['row']['reason']}"
    row = out["row"]
    assert row["signed_rank_p"] != "", "signed_rank_p should be populated"
    assert row["effect_mean_delta"] != "", "effect_mean_delta should be populated"
    assert row["nonzero_pairs"] != "", "nonzero_pairs should be populated"
    assert float(row["effect_mean_delta"]) > 0.02
    assert int(row["nonzero_pairs"]) >= 5
    # new_rows should reflect the improved rows
    assert out["new_rows"] == _IMPROVED_ROWS


# ---------------------------------------------------------------------------
# Test: revert when no improvement
# ---------------------------------------------------------------------------

def test_revert_on_no_improvement(tmp_path):
    """No per-fixture delta -> decision='revert'."""
    cfg = _base_cfg(tmp_path, _BASELINE_ROWS)

    with (
        patch.object(loop_mod, "git_ops", _FakeGitOps),
        patch.object(loop_mod.apply_mod, "extract_diff", _FakeApply.extract_diff),
        patch.object(loop_mod.apply_mod, "validate_paths", _FakeApply.validate_paths),
        patch.object(loop_mod.apply_mod, "count_changed_loc", _FakeApply.count_changed_loc),
        patch.object(loop_mod.apply_mod, "apply_diff", _FakeApply.apply_diff),
        patch.object(loop_mod.editor_mod, "load_program_template", _fake_load_program_template),
        patch.object(loop_mod.editor_mod, "build_brief", _fake_build_brief),
        patch.object(loop_mod.editor_mod, "spawn_editor", _fake_spawn_editor),
        patch.object(loop_mod.overfit, "parse_verdict", _fake_parse_verdict),
        patch.object(loop_mod, "_normalise_headings", lambda t: t),
        patch("evals.auto.runner_shim.run_component", return_value=_run_component_ok("commit_v2")),
        patch("evals.auto.runner_shim.aggregate_latest", return_value=_agg(_FLAT_ROWS)),
    ):
        out = _one_iteration(
            cfg,
            iteration=1,
            base_metric=0.50,
            base_pooled_stdev=0.05,
            base_commit="base_sha_001",
            cumulative_cost=0.0,
            base_rows=_BASELINE_ROWS,
        )

    assert out["decision"] == "revert", f"expected revert, got {out['decision']}"
    row = out["row"]
    # Stats columns still populated on revert (real values computed before decision)
    assert row["signed_rank_p"] != "" or row["nonzero_pairs"] == "0"
    # new_rows stays as base_rows on revert
    assert out["new_rows"] == _BASELINE_ROWS


# ---------------------------------------------------------------------------
# Test: all 3 new ledger columns present at ALL 6 sites
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("site,extra_patches,expect_decision", [
    (
        "auth_fatal",
        {"editor_ok": False, "stderr": "401 Unauthorized"},
        "halt",
    ),
    (
        "reject_empty_diff",
        {"empty_diff": True},
        "reject",
    ),
    (
        "dry_run",
        {"dry_run": True},
        "dry_run_skip_apply",
    ),
    (
        "apply_fail",
        {"apply_fails": True},
        "reject",
    ),
    (
        "runner_fail",
        {"runner_fails": True},
        "revert",
    ),
])
def test_ledger_columns_present_at_all_non_runner_sites(tmp_path, site, extra_patches, expect_decision):
    """Every early-exit site must populate (even if empty) all 3 new columns."""
    cfg = _base_cfg(tmp_path, _BASELINE_ROWS)
    if extra_patches.get("dry_run"):
        cfg = LoopConfig(
            repo_root=tmp_path,
            component="skeptic",
            component_cfg={
                "editable": ["content/agents/skeptic.md"],
                "locked": [],
                "max_edit_loc": 20,
            },
            max_iterations=1,
            time_budget_sec=3600,
            cost_budget_usd=10.0,
            n_fixtures=len(_BASELINE_ROWS),
            baseline_metric=0.50,
            baseline_pooled_stdev=0.05,
            dry_run=True,
            baseline_rows=_BASELINE_ROWS,
        )

    def _editor_result(ok=True, stderr="", empty=False):
        if not ok:
            return {"ok": False, "text": "", "cost_usd": 0.0, "returncode": 1, "stderr": stderr}
        if empty:
            return {"ok": True, "text": "```diff\n```\nOverfitting Rule verdict: no because no-op\n",
                    "cost_usd": 0.0, "returncode": 0, "stderr": ""}
        return _VALID_EDITOR_RESULT

    editor_ok = not extra_patches.get("editor_ok") is False
    editor_result = _editor_result(
        ok=not (extra_patches.get("editor_ok") is False),
        stderr=extra_patches.get("stderr", ""),
        empty=extra_patches.get("empty_diff", False),
    )

    apply_result = (
        {"ok": False, "reason": "patch_failed", "stderr": "conflict"}
        if extra_patches.get("apply_fails")
        else _VALID_APPLY_RESULT
    )

    runner_result = (
        {"ok": False, "returncode": 1, "stderr": "runner died", "stdout": "", "cost_usd": 0.0, "head_commit": ""}
        if extra_patches.get("runner_fails")
        else _run_component_ok()
    )

    with (
        patch.object(loop_mod, "git_ops", _FakeGitOps),
        patch.object(loop_mod.apply_mod, "extract_diff", _FakeApply.extract_diff),
        patch.object(loop_mod.apply_mod, "validate_paths", _FakeApply.validate_paths),
        patch.object(loop_mod.apply_mod, "count_changed_loc", _FakeApply.count_changed_loc),
        patch.object(loop_mod.apply_mod, "apply_diff", lambda _r, _d: apply_result),
        patch.object(loop_mod.editor_mod, "load_program_template", _fake_load_program_template),
        patch.object(loop_mod.editor_mod, "build_brief", _fake_build_brief),
        patch.object(loop_mod.editor_mod, "spawn_editor", lambda *a, **kw: editor_result),
        patch.object(loop_mod.overfit, "parse_verdict", _fake_parse_verdict),
        patch.object(loop_mod, "_normalise_headings", lambda t: t),
        patch("evals.auto.runner_shim.run_component", return_value=runner_result),
        patch("evals.auto.runner_shim.aggregate_latest", return_value=_agg(_FLAT_ROWS)),
    ):
        out = _one_iteration(
            cfg,
            iteration=1,
            base_metric=0.50,
            base_pooled_stdev=0.05,
            base_commit="base_sha_001",
            cumulative_cost=0.0,
            base_rows=_BASELINE_ROWS,
        )

    row = out["row"]
    assert out["decision"] == expect_decision, f"site={site}: expected {expect_decision}, got {out['decision']}"
    # All 3 columns must be present (can be empty string on non-runner paths)
    for col in ("signed_rank_p", "effect_mean_delta", "nonzero_pairs"):
        assert col in row, f"site={site}: missing column {col!r} in ledger row"
    # LEDGER_HEADER coverage - all columns present
    missing = [c for c in LEDGER_HEADER if c not in row]
    assert not missing, f"site={site}: row missing LEDGER_HEADER columns: {missing}"


# ---------------------------------------------------------------------------
# Test: advance-on-keep - second iteration pairs against first-kept rows
# ---------------------------------------------------------------------------

def test_advance_base_rows_on_keep(tmp_path):
    """After a kept iteration, subsequent iterations pair against the kept rows."""
    # Arrange two iterations:
    # iter 1: baseline->improved (keep). iter 2: improved->improved2 (keep).
    # We capture the base_rows each iteration receives.
    IMPROVED2_SCORES = [s + 0.10 for s in _IMPROVED_SCORES]
    IMPROVED2_ROWS = _make_rows(FIXTURE_IDS, IMPROVED2_SCORES)

    captured_base_rows: list[list] = []
    call_count = [0]

    def _fake_aggregate(_repo_root, _component, _n_fixtures, expected_commit=None):
        call_count[0] += 1
        if call_count[0] == 1:
            return _agg(_IMPROVED_ROWS)
        return _agg(IMPROVED2_ROWS)

    def _patched_one_iteration(cfg, *, iteration, base_metric, base_pooled_stdev,
                               base_commit, cumulative_cost, base_rows):
        captured_base_rows.append(list(base_rows))
        return _orig_one_iteration(
            cfg,
            iteration=iteration,
            base_metric=base_metric,
            base_pooled_stdev=base_pooled_stdev,
            base_commit=base_commit,
            cumulative_cost=cumulative_cost,
            base_rows=base_rows,
        )

    _orig_one_iteration = _one_iteration

    cfg = LoopConfig(
        repo_root=tmp_path,
        component="skeptic",
        component_cfg={
            "editable": ["content/agents/skeptic.md"],
            "locked": [],
            "max_edit_loc": 20,
        },
        max_iterations=2,
        time_budget_sec=3600,
        cost_budget_usd=10.0,
        n_fixtures=len(_BASELINE_ROWS),
        baseline_metric=0.50,
        baseline_pooled_stdev=0.05,
        baseline_rows=_BASELINE_ROWS,
    )

    with (
        patch.object(loop_mod, "git_ops", _FakeGitOps),
        patch.object(loop_mod.apply_mod, "extract_diff", _FakeApply.extract_diff),
        patch.object(loop_mod.apply_mod, "validate_paths", _FakeApply.validate_paths),
        patch.object(loop_mod.apply_mod, "count_changed_loc", _FakeApply.count_changed_loc),
        patch.object(loop_mod.apply_mod, "apply_diff", _FakeApply.apply_diff),
        patch.object(loop_mod.editor_mod, "load_program_template", _fake_load_program_template),
        patch.object(loop_mod.editor_mod, "build_brief", _fake_build_brief),
        patch.object(loop_mod.editor_mod, "spawn_editor", _fake_spawn_editor),
        patch.object(loop_mod.overfit, "parse_verdict", _fake_parse_verdict),
        patch.object(loop_mod, "_normalise_headings", lambda t: t),
        patch.object(loop_mod, "_one_iteration", _patched_one_iteration),
        patch("evals.auto.runner_shim.run_component", return_value=_run_component_ok()),
        patch("evals.auto.runner_shim.aggregate_latest", side_effect=_fake_aggregate),
    ):
        result = loop_mod.run(cfg)

    assert result["keeps"] == 2, f"expected 2 keeps, got {result['keeps']}"
    # Iteration 1 pairs against original baseline rows
    assert captured_base_rows[0] == _BASELINE_ROWS, "iter 1 should use original baseline_rows"
    # Iteration 2 pairs against the rows from iteration 1 (improved, not baseline)
    assert captured_base_rows[1] == _IMPROVED_ROWS, (
        f"iter 2 should use iteration 1's kept rows, got {captured_base_rows[1]}"
    )
