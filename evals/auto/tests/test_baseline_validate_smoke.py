"""
Smoke scenario: validate_baseline() returns ok=True against a fixture baseline.

This test is the Stage 0 verification gate referenced by the architect plan
(implementation step 6). Stage 6 comparison runner will import validate_baseline
from the same location; this test confirms the import path and ok==True contract
hold before Stage 6 is built.

The fixture is constructed in-memory using the same helper pattern as
evals/baseline/tests/test_validate.py to avoid committing a static JSON artifact
that could drift from the live schema.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.baseline.validate import validate_baseline


# ---------------------------------------------------------------------------
# Fixture helpers (mirrors _minimal_valid_baseline in test_validate.py)
# ---------------------------------------------------------------------------

def _components_dir() -> Path:
    """Resolve evals/components/ relative to this file."""
    # evals/auto/tests/ -> evals/auto/ -> evals/ -> components/
    return Path(__file__).resolve().parent.parent.parent / "components"


def _minimal_valid_baseline(components_dir: Path) -> dict:
    """Build a minimal schema_version: 1 baseline that passes all validations."""
    yaml_names = sorted(p.stem for p in components_dir.glob("*.yaml"))
    components = []
    for name in yaml_names:
        components.append({
            "name": name,
            "manifest_path": f"evals/components/{name}.yaml",
            "manifest_sha256": "a" * 64,
            "fixtures": [
                {
                    "fixture_hash": "b" * 64,
                    "fixture_description": f"smoke fixture for {name}",
                    "primary_score_median": 0.75,
                    "primary_score_stdev": 0.05,
                    "n_runs": 3,
                    "status": "ok",
                    "captured_at_sha": "c" * 40,
                }
            ],
        })
    return {
        "schema_version": 1,
        "baseline_id": "smoke-test-baseline",
        "captured_at_utc": "2026-05-05T00:00:00+00:00",
        "captured_by": "evals-baseline-capture@v1",
        "stochasticity_disclaimer": "This baseline is one sample.",
        "git": {
            "ai_tools_sha": "d" * 40,
            "ai_tools_dirty": False,
            "agentic_engineering_sha": "e" * 40,
            "agentic_engineering_dirty": False,
            "helios_sha": None,
            "helios_dirty": False,
        },
        "environment": {
            "claude_cli_version": "1.0.0",
            "claude_config_snapshot": "model: sonnet",
            "agentic_engineering_json": {"mode": "opt-out", "profile": "default"},
            "agentic_engineering_json_path": "/home/test/.claude/agentic-engineering.json",
            "model_tier_default": "sonnet:profile=default",
            "python_version": "3.11.0",
            "platform": "darwin-arm64",
            "hostname": "smoke-host",
        },
        "components": components,
        "components_skipped": [],
        "components_failed": [],
        "manifest_enumeration": {
            "discovered_yaml_files": [f"evals/components/{n}.yaml" for n in yaml_names],
            "count": len(yaml_names),
            "all_accounted_for": True,
        },
    }


# ---------------------------------------------------------------------------
# Smoke scenario
# ---------------------------------------------------------------------------

def test_validate_baseline_ok_on_fixture(tmp_path: Path) -> None:
    """
    validate_baseline() must return ok=True against a well-formed fixture baseline.

    This is the Stage 0 verification gate: if this test fails, the validator
    contract is broken and Stage 6 cannot safely consume baseline artifacts.
    """
    components_dir = _components_dir()
    data = _minimal_valid_baseline(components_dir)
    baseline_path = tmp_path / "smoke-baseline.json"
    baseline_path.write_text(json.dumps(data))

    result = validate_baseline(baseline_path)

    assert result.ok is True, (
        f"validate_baseline() returned ok=False on a well-formed fixture.\n"
        f"Errors: {result.errors}\n"
        f"Warnings: {result.warnings}"
    )
    assert result.errors == [], f"Unexpected validation errors: {result.errors}"
