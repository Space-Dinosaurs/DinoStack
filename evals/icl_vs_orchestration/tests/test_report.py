"""Tests for report.py - validate_report, build_summary, build_methodology.

Covers the cost-normalization-contract.md compliance requirement that
results-v1.json carries a methodology.skeptic_input_cost_normalization block.
"""
from __future__ import annotations

import pytest

from evals.icl_vs_orchestration.report import (
    REQUIRED_REPORT_FIELDS,
    build_methodology,
    build_summary,
    validate_report,
)
from evals.icl_vs_orchestration.scoring.output_coherence import TAXONOMY_VERSION


def _minimal_valid_report() -> dict:
    """Return a report dict that satisfies all validate_report requirements."""
    return {
        "schema_version": "v1",
        "run_id": "test-run-001",
        "corpus_dir": "corpora/smoke",
        "ae_execution_mode": "single-shot",
        "correctness_method": "rubric-v1",
        "output_coherence_method": "taxonomy-v1",
        "output_coherence_taxonomy_version": TAXONOMY_VERSION,
        "smoke": True,
        "aborted": False,
        "cells_dropped_by_per_cell_budget": 0,
        "weights_renormalized_count": 0,
        "floored_dim_count_per_condition": {},
        "rationale_extraction_method_count": {},
        "cost": {"global_usd": 0.0, "global_tokens": 0},
        "methodology": build_methodology(),
        "summary": build_summary({}),
        "tickets": {},
    }


# ---------------------------------------------------------------------------
# Required fields tests
# ---------------------------------------------------------------------------

def test_required_report_fields_includes_methodology():
    """REQUIRED_REPORT_FIELDS must include 'methodology' per contract."""
    assert "methodology" in REQUIRED_REPORT_FIELDS


def test_validate_report_valid_report_passes():
    """A fully-formed report with methodology block passes validate_report."""
    validate_report(_minimal_valid_report())  # must not raise


def test_validate_report_missing_methodology_raises():
    """validate_report raises ValueError when methodology key is absent."""
    report = _minimal_valid_report()
    del report["methodology"]
    with pytest.raises(ValueError, match="methodology"):
        validate_report(report)


def test_validate_report_methodology_missing_normalization_block_raises():
    """validate_report raises ValueError when normalization block is absent."""
    report = _minimal_valid_report()
    report["methodology"] = {}  # Empty methodology
    with pytest.raises(ValueError, match="skeptic_input_cost_normalization"):
        validate_report(report)


def test_validate_report_normalization_block_missing_field_raises():
    """validate_report raises ValueError when normalization block is missing a field."""
    report = _minimal_valid_report()
    report["methodology"] = {
        "skeptic_input_cost_normalization": {
            "applied": False,
            # missing method, baseline_tokens, post_restructure_tokens
        }
    }
    with pytest.raises(ValueError, match="method|baseline_tokens|post_restructure_tokens"):
        validate_report(report)


def test_validate_report_wrong_taxonomy_version_raises():
    """validate_report raises ValueError on mismatched taxonomy version."""
    report = _minimal_valid_report()
    report["output_coherence_taxonomy_version"] = "wrong-version"
    with pytest.raises(ValueError, match="output_coherence_taxonomy_version"):
        validate_report(report)


# ---------------------------------------------------------------------------
# build_methodology tests
# ---------------------------------------------------------------------------

def test_build_methodology_default_contains_normalization_block():
    """build_methodology() returns dict with skeptic_input_cost_normalization."""
    m = build_methodology()
    assert "skeptic_input_cost_normalization" in m


def test_build_methodology_default_applied_false():
    """Default build_methodology uses applied=False (fixed-estimate path)."""
    m = build_methodology()
    assert m["skeptic_input_cost_normalization"]["applied"] is False


def test_build_methodology_with_custom_block():
    """build_methodology accepts a pre-built normalization block."""
    custom_block = {
        "applied": True,
        "method": "subtract_median_global_context_tokens_per_spawn",
        "baseline_tokens": 0,
        "post_restructure_tokens": 7500,
    }
    m = build_methodology(normalization_block=custom_block)
    assert m["skeptic_input_cost_normalization"]["applied"] is True
    assert m["skeptic_input_cost_normalization"]["post_restructure_tokens"] == 7500


def test_build_methodology_none_uses_default():
    """build_methodology(normalization_block=None) falls back to default block."""
    m = build_methodology(normalization_block=None)
    norm = m["skeptic_input_cost_normalization"]
    assert "applied" in norm
    assert norm["baseline_tokens"] == 0


# ---------------------------------------------------------------------------
# build_summary tests
# ---------------------------------------------------------------------------

def test_build_summary_empty_input():
    """build_summary on empty input returns zero-state summary."""
    summary = build_summary({})
    assert summary["tickets_run"] == 0
    assert summary["conditions"] == []


def test_build_summary_single_ticket():
    """build_summary correctly aggregates a single ticket's scores."""
    scores = {
        "t1": {
            "ae-orchestrated": {"primary": 0.8},
            "icl-baseline": {"primary": 0.6},
        }
    }
    summary = build_summary(scores)
    assert summary["tickets_run"] == 1
    assert "ae-orchestrated" in summary["conditions"]
    assert "icl-baseline" in summary["conditions"]
    assert abs(summary["per_condition_primary_mean"]["ae-orchestrated"] - 0.8) < 1e-6
    assert abs(summary["per_condition_primary_mean"]["icl-baseline"] - 0.6) < 1e-6


def test_build_summary_multiple_tickets_mean():
    """build_summary averages primary scores correctly across tickets."""
    scores = {
        "t1": {"ae-orchestrated": {"primary": 0.8}},
        "t2": {"ae-orchestrated": {"primary": 0.4}},
    }
    summary = build_summary(scores)
    assert summary["tickets_run"] == 2
    assert abs(summary["per_condition_primary_mean"]["ae-orchestrated"] - 0.6) < 1e-6
