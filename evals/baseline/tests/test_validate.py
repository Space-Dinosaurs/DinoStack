"""
Unit tests for evals.baseline.validate.validate_baseline().

Tests a fixture baseline JSON built in-memory (no live capture required).
Stage 6 will reuse validate_baseline() to confirm the recorded schema before
reading score data; these tests exercise all 6 validation steps.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from evals.baseline.validate import validate_baseline


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _minimal_valid_baseline(components_dir: Path) -> dict:
    """Build a minimal schema_version: 1 baseline that should pass all validations."""
    # Discover actual component names from the real evals/components/ directory
    # so the manifest_enumeration invariant holds
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
                    "fixture_description": f"test fixture for {name}",
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
        "baseline_id": "test-baseline",
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
            "hostname": "test-host",
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


def _write_baseline(tmp_path: Path, data: dict) -> Path:
    p = tmp_path / "baseline.json"
    p.write_text(json.dumps(data))
    return p


def _components_dir() -> Path:
    """Resolve evals/components/ relative to this file."""
    return Path(__file__).resolve().parent.parent.parent / "components"


# ---------------------------------------------------------------------------
# Step 1: JSON loading and schema_version
# ---------------------------------------------------------------------------

def test_file_not_found(tmp_path):
    result = validate_baseline(tmp_path / "nonexistent.json")
    assert not result.ok
    assert any("file not found" in e for e in result.errors)


def test_invalid_json(tmp_path):
    p = tmp_path / "bad.json"
    p.write_text("{not valid json")
    result = validate_baseline(p)
    assert not result.ok
    assert any("JSON parse error" in e for e in result.errors)


def test_wrong_schema_version(tmp_path):
    components_dir = _components_dir()
    data = _minimal_valid_baseline(components_dir)
    data["schema_version"] = 2
    p = _write_baseline(tmp_path, data)
    result = validate_baseline(p)
    assert not result.ok
    assert any("schema_version" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Step 2: Required fields
# ---------------------------------------------------------------------------

def test_missing_required_field(tmp_path):
    components_dir = _components_dir()
    data = _minimal_valid_baseline(components_dir)
    del data["git"]
    p = _write_baseline(tmp_path, data)
    result = validate_baseline(p)
    assert not result.ok
    assert any("git" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Step 3: git dirty flags
# ---------------------------------------------------------------------------

def test_dirty_tree_rejected(tmp_path):
    components_dir = _components_dir()
    data = _minimal_valid_baseline(components_dir)
    data["git"]["ai_tools_dirty"] = True
    p = _write_baseline(tmp_path, data)
    result = validate_baseline(p)
    assert not result.ok
    assert any("ai_tools_dirty" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Step 4: Manifest enumeration
# ---------------------------------------------------------------------------

def test_missing_component_detected(tmp_path):
    components_dir = _components_dir()
    data = _minimal_valid_baseline(components_dir)
    # Remove one component without moving it to skipped/failed
    removed = data["components"].pop(0)
    # Also update manifest_enumeration to flag it
    data["manifest_enumeration"]["all_accounted_for"] = False
    p = _write_baseline(tmp_path, data)
    result = validate_baseline(p)
    assert not result.ok
    assert any("not accounted for" in e for e in result.errors)


def test_extra_component_detected(tmp_path):
    components_dir = _components_dir()
    data = _minimal_valid_baseline(components_dir)
    # Add a component that doesn't have a YAML file
    data["components"].append({
        "name": "nonexistent-component-xyz",
        "manifest_path": "evals/components/nonexistent-component-xyz.yaml",
        "manifest_sha256": "a" * 64,
        "fixtures": [],
    })
    p = _write_baseline(tmp_path, data)
    result = validate_baseline(p)
    assert not result.ok
    assert any("not found in evals/components/" in e for e in result.errors)


def test_skipped_and_failed_count_as_accounted(tmp_path):
    components_dir = _components_dir()
    data = _minimal_valid_baseline(components_dir)
    # Move first component to skipped
    comp = data["components"].pop(0)
    data["components_skipped"].append({"name": comp["name"], "reason": "no tsv"})
    # Move second to failed
    comp2 = data["components"].pop(0)
    data["components_failed"].append({"name": comp2["name"], "reason": "error"})
    p = _write_baseline(tmp_path, data)
    result = validate_baseline(p)
    assert result.ok, f"Unexpected errors: {result.errors}"


# ---------------------------------------------------------------------------
# Step 5: Fixture field validation
# ---------------------------------------------------------------------------

def test_fixture_median_out_of_range(tmp_path):
    components_dir = _components_dir()
    data = _minimal_valid_baseline(components_dir)
    data["components"][0]["fixtures"][0]["primary_score_median"] = 1.5
    p = _write_baseline(tmp_path, data)
    result = validate_baseline(p)
    assert not result.ok
    assert any("primary_score_median" in e for e in result.errors)


def test_fixture_n_runs_zero(tmp_path):
    components_dir = _components_dir()
    data = _minimal_valid_baseline(components_dir)
    data["components"][0]["fixtures"][0]["n_runs"] = 0
    p = _write_baseline(tmp_path, data)
    result = validate_baseline(p)
    assert not result.ok
    assert any("n_runs" in e for e in result.errors)


def test_fixture_empty_status(tmp_path):
    components_dir = _components_dir()
    data = _minimal_valid_baseline(components_dir)
    data["components"][0]["fixtures"][0]["status"] = ""
    p = _write_baseline(tmp_path, data)
    result = validate_baseline(p)
    assert not result.ok
    assert any("status" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Step 6: environment.agentic_engineering_json
# ---------------------------------------------------------------------------

def test_ae_json_null_rejected(tmp_path):
    components_dir = _components_dir()
    data = _minimal_valid_baseline(components_dir)
    data["environment"]["agentic_engineering_json"] = None
    p = _write_baseline(tmp_path, data)
    result = validate_baseline(p)
    assert not result.ok
    assert any("agentic_engineering_json" in e for e in result.errors)


def test_ae_json_explicit_null_dict_accepted(tmp_path):
    components_dir = _components_dir()
    data = _minimal_valid_baseline(components_dir)
    data["environment"]["agentic_engineering_json"] = {"null": "file-not-found"}
    p = _write_baseline(tmp_path, data)
    result = validate_baseline(p)
    assert result.ok, f"Unexpected errors: {result.errors}"
    assert any("null" in w for w in result.warnings)


# ---------------------------------------------------------------------------
# Step 3b: agentic_engineering_sha required (regression for F1 SHA inversion fix)
# ---------------------------------------------------------------------------

def test_missing_agentic_engineering_sha_rejected(tmp_path):
    """Regression: validator must reject baselines with no agentic_engineering_sha key."""
    components_dir = _components_dir()
    data = _minimal_valid_baseline(components_dir)
    del data["git"]["agentic_engineering_sha"]
    p = _write_baseline(tmp_path, data)
    result = validate_baseline(p)
    assert not result.ok
    assert any("agentic_engineering_sha" in e for e in result.errors)


def test_empty_agentic_engineering_sha_rejected(tmp_path):
    """Regression: validator must reject baselines where agentic_engineering_sha is empty string."""
    components_dir = _components_dir()
    data = _minimal_valid_baseline(components_dir)
    data["git"]["agentic_engineering_sha"] = ""
    p = _write_baseline(tmp_path, data)
    result = validate_baseline(p)
    assert not result.ok
    assert any("agentic_engineering_sha" in e for e in result.errors)


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------

def test_valid_baseline_passes(tmp_path):
    components_dir = _components_dir()
    data = _minimal_valid_baseline(components_dir)
    p = _write_baseline(tmp_path, data)
    result = validate_baseline(p)
    assert result.ok, f"Unexpected errors: {result.errors}"
    assert result.errors == []
