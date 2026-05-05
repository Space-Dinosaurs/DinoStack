"""Tests for verification_realism scorer - covers QA scenario 10 (symmetric floor)."""
import pytest

from evals.icl_vs_orchestration.scoring.verification_realism import score


def _make_ticket() -> dict:
    return {"ticket_id": "test", "ticket_yaml": {}}


def _icl_result_no_plan() -> dict:
    """ICL result with no architect plan by design."""
    return {
        "ticket_id": "test",
        "condition_id": "icl-baseline",
        "final_text": "Here is my implementation...",
        "diff": "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b",
        "artifacts": {
            "rationale_or_plan": "Here is my rationale.",
            "diff": "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b",
        },
    }


def _ae_result_with_plan() -> dict:
    """AE result with qa_criteria in final_text (single-shot path)."""
    return {
        "ticket_id": "test",
        "condition_id": "ae-orchestrated",
        "final_text": (
            "## Architect Plan\n"
            "This is the plan.\n"
            "## qa_criteria\n"
            "qa_skip: null\n"
            "scenarios:\n"
            "  - id: 1\n"
            "    description: test passes\n"
        ),
        "diff": "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b",
        "artifacts": {
            "rationale_or_plan": "This is the plan.",
            "diff": "--- a/x\n+++ b/x\n@@ -1 +1 @@\n-a\n+b",
        },
    }


def _ae_result_no_plan() -> dict:
    """AE result with no architect plan or qa_criteria."""
    return {
        "ticket_id": "test",
        "condition_id": "ae-orchestrated",
        "final_text": "Just some output without a plan.",
        "diff": None,
        "artifacts": {
            "rationale_or_plan": "Some output.",
            "diff": "",
        },
    }


def test_icl_always_floored():
    """ICL-baseline without architect plan always floors at 0.0."""
    s = score(_icl_result_no_plan(), _make_ticket())
    assert s["score"] == 0.0
    assert s["status"] == "floored"


def test_ae_with_qa_criteria_scored():
    """AE-orchestrated with qa_criteria in final_text scores > 0."""
    s = score(_ae_result_with_plan(), _make_ticket())
    assert s["score"] > 0.0
    assert s["status"] == "scored"


def test_ae_without_plan_floored():
    """AE-orchestrated without plan or qa_criteria floors at 0.0."""
    s = score(_ae_result_no_plan(), _make_ticket())
    assert s["score"] == 0.0
    assert s["status"] == "floored"


def test_icl_never_not_applicable():
    """ICL floors (status=floored) - never returns status=not-applicable."""
    s = score(_icl_result_no_plan(), _make_ticket())
    assert s["status"] != "not-applicable"
    assert s["status"] == "floored"


def test_symmetric_floor_in_aggregate():
    """Primary aggregates computed over identical DIMENSIONS list on both conditions.

    This verifies that floored dims are included in the registry aggregate (not dropped),
    so the primary score is computed over the same dim set.
    """
    from evals.icl_vs_orchestration.scoring.registry import load_registry, DIMENSIONS

    registry = load_registry()
    ae_result = _ae_result_with_plan()
    icl_result = _icl_result_no_plan()
    ticket = _make_ticket()

    ae_score = registry.score_result(ae_result, ticket)
    icl_score = registry.score_result(icl_result, ticket)

    # Both conditions compute primary over the same DIMENSIONS
    assert set(ae_score["dimensions"].keys()) == set(DIMENSIONS)
    assert set(icl_score["dimensions"].keys()) == set(DIMENSIONS)

    # ICL verification-realism is floored
    icl_vr = icl_score["dimensions"]["verification-realism"]
    assert icl_vr["status"] == "floored"
    assert icl_vr["score"] == 0.0

    # floored_dim_count_per_condition for ICL includes verification-realism
    assert "verification-realism" in icl_score.get("floored_dims", [])
