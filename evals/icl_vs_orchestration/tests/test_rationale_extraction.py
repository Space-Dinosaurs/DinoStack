"""Tests for rationale extraction - covers QA scenario 11 (symmetric fallback rule).

Both AE and ICL adapters use the same extract_rationale_or_plan rule:
- If a structured section is found: extraction_method="structured"
- If not found: extraction_method="fallback-full-text", rationale_or_plan=full text
"""
import pytest

from evals.icl_vs_orchestration.conditions.base import extract_rationale_or_plan


# ---- ICL-no-section: entire final_text is used ----

def test_icl_no_section_fallback():
    """ICL fixture without structured rationale -> fallback-full-text."""
    final_text = "I will fix the bug by checking token expiry. Here is the diff:\n```diff\n-x\n+y\n```"
    rationale, method = extract_rationale_or_plan(final_text)
    assert method == "fallback-full-text"
    assert rationale == final_text


# ---- ICL-with-section: structured section extracted ----

def test_icl_with_markdown_section():
    """ICL fixture with ## Rationale section -> structured."""
    final_text = (
        "## Rationale\n"
        "The bug is in the expiry check. We fix it by adding a date comparison.\n"
        "## Diff\n"
        "```diff\n-if (token) return true;\n+if (token && !expired(token)) return true;\n```"
    )
    rationale, method = extract_rationale_or_plan(final_text)
    assert method == "structured"
    assert "expiry check" in rationale
    assert "## Diff" not in rationale


def test_icl_with_rationale_section_body_only():
    """Extracted body does not include the section header."""
    final_text = "## Rationale\nThis is the plan.\n## Diff\nsome diff"
    rationale, method = extract_rationale_or_plan(final_text)
    assert method == "structured"
    assert rationale == "This is the plan."


# ---- AE-no-section: entire architect plan text is used ----

def test_ae_no_section_fallback():
    """AE fixture (single-shot) without structured section -> fallback-full-text."""
    plan_text = (
        "The implementation will add a health endpoint to src/routes/health.ts "
        "and register it in app.ts before the auth middleware."
    )
    rationale, method = extract_rationale_or_plan(plan_text)
    assert method == "fallback-full-text"
    assert rationale == plan_text


# ---- AE-with-section: structured section extracted ----

def test_ae_with_markdown_rationale_section():
    """AE fixture with ## Rationale section -> structured."""
    plan_text = (
        "## Architect Plan\n"
        "We add a health endpoint.\n"
        "## Rationale\n"
        "Health checks are required for container orchestration (k8s, ECS).\n"
        "## Changes\n"
        "1. Add src/routes/health.ts\n"
    )
    rationale, method = extract_rationale_or_plan(plan_text)
    assert method == "structured"
    assert "container orchestration" in rationale
    # Should not include the ## Changes section
    assert "## Changes" not in rationale


def test_ae_with_plan_section():
    """AE fixture with ## Plan section -> structured."""
    plan_text = (
        "Some preamble.\n"
        "## Plan\n"
        "Refactor the session adapter to use Postgres.\n"
        "## Implementation\n"
        "Files: adapter.ts, migration.sql"
    )
    rationale, method = extract_rationale_or_plan(plan_text)
    assert method == "structured"
    assert "Postgres" in rationale


# ---- Symmetric fallback behavior ----

def test_both_conditions_use_same_extraction_rule():
    """Both AE and ICL adapters use extract_rationale_or_plan identically.

    This test verifies the symmetric extraction rule produces the same
    extraction_method for equivalent source_text on both conditions.
    """
    # Source with no structured section
    unstructured = "The change fixes the bug by updating the logic."
    ae_rationale, ae_method = extract_rationale_or_plan(unstructured)
    icl_rationale, icl_method = extract_rationale_or_plan(unstructured)
    assert ae_method == "fallback-full-text"
    assert icl_method == "fallback-full-text"
    assert ae_rationale == icl_rationale

    # Source with a structured section
    structured = "## Rationale\nThis is the rationale.\n## Diff\nsome diff"
    ae_rationale2, ae_method2 = extract_rationale_or_plan(structured)
    icl_rationale2, icl_method2 = extract_rationale_or_plan(structured)
    assert ae_method2 == "structured"
    assert icl_method2 == "structured"
    assert ae_rationale2 == icl_rationale2


def test_xml_delimiter_extraction():
    """XML-style rationale delimiter is also recognized."""
    text = "<rationale>The plan is to migrate the session store.</rationale>"
    rationale, method = extract_rationale_or_plan(text)
    assert method == "structured"
    assert "migrate the session store" in rationale


def test_empty_text_fallback():
    """Empty text falls back to empty string with fallback-full-text method."""
    rationale, method = extract_rationale_or_plan("")
    assert method == "fallback-full-text"
    assert rationale == ""
