#!/usr/bin/env python3
"""
Tests for bin/_telemetry.py (DS-246): pricing, hook spawn normalization and
the primary-checkout merge. Loaded via SourceFileLoader like its consumers.

Run with: python3 -m pytest bin/tests/test_telemetry.py
"""
from __future__ import annotations

import importlib.machinery
import importlib.util
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
import telemetry_v2_fixtures as fx

_MOD_PATH = Path(__file__).resolve().parent.parent / "_telemetry.py"
_loader = importlib.machinery.SourceFileLoader("_telemetry_under_test", str(_MOD_PATH))
tel = importlib.util.module_from_spec(importlib.util.spec_from_loader(_loader.name, _loader))
_loader.exec_module(tel)


def test_resolve_rates_exact_family_and_unresolved():
    rates = tel.DEFAULT_RATES
    assert tel.resolve_rates("claude-opus-5-5", rates) == (rates["claude-opus-5-5"], "exact")
    assert tel.resolve_rates("claude-opus-5-5[1m]", rates)[1] == "exact"
    assert tel.resolve_rates("claude-haiku-4-5-20251001", rates) == (rates["claude-haiku-4-5"], "exact")
    assert tel.resolve_rates("claude-opus-5", rates) == (rates["claude-opus-5-5"], "family")
    assert tel.resolve_rates("opus", rates) == (rates["claude-opus-5-5"], "family")
    assert tel.resolve_rates("claude-fable-5", rates) == (rates["claude-fable-5-1"], "family")
    for model in ("<synthetic>", "inherit", None, "", "gpt-9"):
        assert tel.resolve_rates(model, rates) == (None, None), model


def test_price_tokens_hand_computed_with_1h_cache_at_2x_input():
    toks = fx.tokens(input=1000, output=2000, cache_read=1_000_000, cc_5m=100_000, cc_1h=50_000)
    priced = tel.price_tokens("claude-opus-5-5", toks, tel.DEFAULT_RATES)
    assert priced["match"] == "exact"
    assert priced["missing"] == []
    by_kind = priced["by_kind"]
    assert by_kind["input"] == pytest.approx(0.004)
    assert by_kind["output"] == pytest.approx(0.04)
    assert by_kind["cache_read"] == pytest.approx(0.2)
    assert by_kind["cache_creation_5m"] == pytest.approx(0.5)   # 1.25 x $4
    assert by_kind["cache_creation_1h"] == pytest.approx(0.4)   # 2 x $4
    assert priced["total"] == pytest.approx(1.144)


def test_price_tokens_without_split_prices_cache_writes_as_5m():
    priced = tel.price_tokens("claude-sonnet-5", {"cache_creation": 400_000}, tel.DEFAULT_RATES)
    assert priced["by_kind"]["cache_creation_5m"] == pytest.approx(1.0)  # 1.25 x $2
    assert priced["by_kind"]["cache_creation_1h"] == 0


def test_price_tokens_family_and_unpriced():
    family = tel.price_tokens("claude-opus-5", {"output": 1_000_000}, tel.DEFAULT_RATES)
    assert family["match"] == "family"
    assert family["total"] == pytest.approx(20.0)
    assert tel.price_tokens("gpt-9", {"output": 1}, tel.DEFAULT_RATES) is None


def test_price_tokens_missing_band_rate_only_matters_when_used():
    rates = {"m-1": {"input": 1.0, "output": 2.0}}
    used = tel.price_tokens("m-1", {"input": 10, "cache_read": 5}, rates)
    assert used["total"] is None
    assert used["missing"] == ["cache_read"]
    unused = tel.price_tokens("m-1", {"input": 1_000_000}, rates)
    assert unused["total"] == pytest.approx(1.0)


def test_load_rates_pricing_yml_overrides_defaults():
    pytest.importorskip("yaml")
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "pricing.yml"
        path.write_text(
            "models:\n"
            "  claude-opus-5-5: {input: 5.0, output: 25.0, cache_read: 0.5}\n"
            "  custom-model: {input: 1.0, output: 1.0, cache_read: 0.1}\n",
            encoding="utf-8",
        )
        rates, source = tel.load_rates(True, path)
        assert rates["claude-opus-5-5"]["input"] == 5.0
        assert rates["claude-sonnet-5"] == tel.DEFAULT_RATES["claude-sonnet-5"]
        assert "custom-model" in rates
        assert str(path) in source
        only_file, _ = tel.load_rates(False, path)
        assert set(only_file) == {"claude-opus-5-5", "custom-model"}

        path.write_text("models: [unclosed\n", encoding="utf-8")
        rates, source = tel.load_rates(True, path)
        assert rates["claude-opus-5-5"] == tel.DEFAULT_RATES["claude-opus-5-5"]
        assert "parse error" in source

        missing, source = tel.load_rates(True, Path(tmp) / "absent.yml")
        assert missing == tel.DEFAULT_RATES
        assert source.startswith("built-in")


def test_normalize_rolls_resumed_runs_into_one_spawn():
    events = [
        fx.v2_start("2026-09-01T10:00:00Z", "qa-engineer", "s1", "AUT-1"),
        fx.v2_complete("2026-09-01T10:05:00Z", "qa-engineer", "s1", "AUT-1", wall_seconds=300.0,
                       cumulative=fx.tokens(input=100), model="claude-sonnet-5", qa_result="FAIL"),
        fx.v2_complete("2026-09-01T11:02:00Z", "qa-engineer", "s1", "AUT-1", run_index=2,
                       run_start_ts="2026-09-01T11:00:00Z", wall_seconds=120.0,
                       cumulative=fx.tokens(input=160), run_tokens=fx.tokens(input=60),
                       model="claude-sonnet-5", pair_method="resume", qa_result="PASS"),
        fx.internal_stop("2026-09-01T10:06:00Z"),
    ]
    (rec,) = tel.normalize_hook_spawns(events, include_legacy=False)
    assert rec.spawn_id == "s1" and rec.agent == "qa-engineer" and rec.task_id == "AUT-1"
    assert [r["run_index"] for r in rec.runs] == [1, 2]
    assert [r["qa_result"] for r in rec.runs] == ["FAIL", "PASS"]
    assert rec.runs[1]["pair_method"] == "resume"
    assert rec.runs[1]["run_tokens"]["input"] == 60
    assert rec.wall_seconds == 420.0 and rec.wall_null_runs == 0
    assert rec.tokens["input"] == 160
    assert rec.model == "claude-sonnet-5"


def test_normalize_legacy_rows_excluded_or_wall_dropped():
    events = [
        fx.v2_start("2026-09-01T10:00:00Z", "engineer", "s1"),
        fx.legacy_complete("2026-09-01T10:00:31Z", "engineer", "s1", cumulative=fx.tokens(input=7)),
    ]
    (v2_only,) = tel.normalize_hook_spawns(events, include_legacy=False)
    assert v2_only.runs == []
    (with_legacy,) = tel.normalize_hook_spawns(events, include_legacy=True)
    assert with_legacy.runs[0]["wall_seconds"] is None
    assert with_legacy.runs[0]["run_tokens"] is None
    assert with_legacy.wall_seconds is None and with_legacy.wall_null_runs == 1
    assert with_legacy.tokens["input"] == 7


def test_normalize_orphan_complete_has_no_start():
    events = [fx.v2_complete("2026-09-01T10:00:00Z", "architect", "gone", "AUT-2",
                             cumulative=fx.tokens(output=5))]
    (rec,) = tel.normalize_hook_spawns(events, include_legacy=False)
    assert rec.start_ts is None
    assert rec.spawn_id == "orphan:gone"
    assert rec.task_id == "AUT-2"


def test_normalize_run1_falls_back_to_cumulative_tokens_and_skips_synthetic_model():
    run1 = fx.v2_complete("2026-09-01T10:00:00Z", "engineer", "s1", cumulative=fx.tokens(input=9),
                          model="<synthetic>")
    del run1["data"]["run_tokens"]
    run2 = fx.v2_complete("2026-09-01T11:00:00Z", "engineer", "s1", run_index=2,
                          cumulative=fx.tokens(input=12))
    del run2["data"]["run_tokens"]
    events = [fx.v2_start("2026-09-01T09:00:00Z", "engineer", "s1"), run1, run2]
    (rec,) = tel.normalize_hook_spawns(events, include_legacy=False)
    assert rec.runs[0]["run_tokens"]["input"] == 9
    assert rec.runs[0]["model"] is None
    assert rec.runs[1]["run_tokens"] is None
    assert rec.model == "claude-opus-5-5"


def test_primary_root_and_merge_from_linked_worktree():
    with tempfile.TemporaryDirectory() as tmp:
        main, worktree = fx.make_linked_worktree(Path(tmp))
        start = fx.v2_start("2026-09-01T10:00:00Z", "engineer", "s1", "AUT-3")
        fx.write_jsonl(main / ".agentic" / "events.jsonl", [
            start,
            {"ts": "2026-09-01T10:00:01Z", "event": "spawn_complete", "agent": "engineer",
             "data": {"source": "conductor"}},
            {"ts": "2026-09-01T10:00:02Z", "event": "session_total", "data": {"source": "hook"}},
        ])
        wt_events = worktree / ".agentic" / "events.jsonl"
        local = [fx.v2_start("2026-09-01T09:00:00Z", "architect", "s0")]
        fx.write_jsonl(wt_events, local)

        assert tel.primary_root(worktree) == main
        assert tel.primary_root(main) == main
        merged = tel.merge_primary_spawn_rows(wt_events, list(local))
        assert merged == local + [start]
        main_events = main / ".agentic" / "events.jsonl"
        assert tel.merge_primary_spawn_rows(main_events, [start]) == [start]
        assert tel.merge_primary_spawn_rows(wt_events, list(local), Path(tmp) / "nope.jsonl") == local
