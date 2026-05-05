"""
Purpose: Validates a captured baseline JSON artifact against the schema_version: 1 contract.
         Used as the verification gate for Stage 0 and as the regression-floor checker
         before Stage 6 comparison runs.

Public API:
    validate_baseline(path: Path) -> ValidationResult
    CLI: python -m evals.baseline.validate <path>

Upstream dependencies:
    - Python 3.11 stdlib (json, pathlib, glob)
    - evals/components/*.yaml (for dynamic manifest enumeration; resolved relative to
      this file's location)

Downstream consumers:
    - CI / verification-gate: evals-baseline-capture acceptance criterion
      (`python -m evals.baseline.validate evals/baselines/2026-05-pre-icl-restructure.json` exits 0)
    - Stage-6 comparison runner: imports validate_baseline to confirm the loaded baseline
      is schema-valid before reading score data
    - evals/auto/ smoke scenario: imports validate_baseline to assert ok==True on the
      fixture baseline

Failure modes:
    - File not found: ValidationResult(ok=False, errors=["file not found: ..."])
    - JSON parse error: ValidationResult(ok=False, errors=["JSON parse error: ..."])
    - Schema violations: collects ALL errors before returning; does not short-circuit.
    - Missing evals/components/ directory: hard error on manifest enumeration step.

Performance: Pure offline JSON read + glob. No model calls. Expected <100ms.
"""

import json
import sys
from pathlib import Path
from typing import Optional


# Resolved paths
_THIS_FILE = Path(__file__).resolve()
_EVALS_DIR = _THIS_FILE.parent.parent        # evals/
_REPO_ROOT = _THIS_FILE.parent.parent.parent # repo root


class ValidationResult:
    def __init__(self, ok: bool, errors: list[str], warnings: list[str]):
        self.ok = ok
        self.errors = errors
        self.warnings = warnings

    def __repr__(self) -> str:
        return f"ValidationResult(ok={self.ok}, errors={self.errors}, warnings={self.warnings})"


def validate_baseline(path: Path) -> ValidationResult:
    """
    Validate a baseline JSON file against the schema_version: 1 contract.

    Validation steps (all must pass for ok=True):
      1. JSON loads; schema_version == 1.
      2. Required top-level fields present: git, environment, components,
         stochasticity_disclaimer, baseline_id, captured_at_utc, captured_by.
      3. git.*_dirty all False (baseline must be captured on a clean tree).
      4. Dynamically enumerate evals/components/*.yaml; assert every file appears in
         exactly one of: components | components_skipped | components_failed.
         Mismatch is a hard fail with the missing/extra names listed.
      5. Every fixture has primary_score_median in [0.0, 1.0], n_runs >= 1,
         status non-empty.
      6. environment.agentic_engineering_json is a dict (or explicit null marker dict
         with a "null" key containing a reason string).

    Returns ValidationResult(ok: bool, errors: list[str], warnings: list[str]).
    """
    errors: list[str] = []
    warnings: list[str] = []

    # --- Step 1: Load JSON ---
    if not path.exists():
        return ValidationResult(ok=False, errors=[f"file not found: {path}"], warnings=[])

    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        return ValidationResult(ok=False, errors=[f"JSON parse error: {exc}"], warnings=[])

    if not isinstance(data, dict):
        return ValidationResult(ok=False, errors=["top-level JSON value must be an object"], warnings=[])

    if data.get("schema_version") != 1:
        errors.append(
            f"schema_version must be 1, got {data.get('schema_version')!r}"
        )

    # --- Step 2: Required fields ---
    required_fields = [
        "git", "environment", "components", "stochasticity_disclaimer",
        "baseline_id", "captured_at_utc", "captured_by",
        "components_skipped", "components_failed", "manifest_enumeration",
    ]
    for field in required_fields:
        if field not in data:
            errors.append(f"missing required field: {field!r}")

    # Don't proceed with structural checks if basic fields are absent
    if errors:
        return ValidationResult(ok=False, errors=errors, warnings=warnings)

    # --- Step 3: git.*_dirty all False ---
    git = data["git"]
    for key in ("ai_tools_dirty", "agentic_engineering_dirty", "helios_dirty"):
        if key in git and git[key] is True:
            errors.append(
                f"git.{key} is True - baseline must be captured on a clean working tree"
            )

    if "ai_tools_sha" not in git or not git["ai_tools_sha"]:
        errors.append("git.ai_tools_sha is missing or empty")

    # --- Step 4: Dynamic manifest enumeration ---
    components_dir = _EVALS_DIR / "components"
    if not components_dir.exists():
        errors.append(f"evals/components/ directory not found at {components_dir}")
    else:
        yaml_names = {y.stem for y in sorted(components_dir.glob("*.yaml"))}

        components = data.get("components", [])
        skipped = data.get("components_skipped", [])
        failed = data.get("components_failed", [])

        in_components = {c["name"] for c in components if isinstance(c, dict) and "name" in c}
        in_skipped = {s["name"] for s in skipped if isinstance(s, dict) and "name" in s}
        in_failed = {f["name"] for f in failed if isinstance(f, dict) and "name" in f}
        accounted = in_components | in_skipped | in_failed

        missing_from_output = yaml_names - accounted
        extra_in_output = accounted - yaml_names

        if missing_from_output:
            errors.append(
                f"components not accounted for in baseline: {sorted(missing_from_output)}"
            )
        if extra_in_output:
            errors.append(
                f"baseline names not found in evals/components/: {sorted(extra_in_output)}"
            )

        # Duplicates across sections
        overlap_cs = in_components & in_skipped
        overlap_cf = in_components & in_failed
        overlap_sf = in_skipped & in_failed
        for pair_name, overlap in [
            ("components+skipped", overlap_cs),
            ("components+failed", overlap_cf),
            ("skipped+failed", overlap_sf),
        ]:
            if overlap:
                errors.append(
                    f"component name appears in multiple sections ({pair_name}): {sorted(overlap)}"
                )

    # --- Step 5: Fixture field validation ---
    components_list = data.get("components", [])
    for comp in components_list:
        if not isinstance(comp, dict):
            errors.append("components[] entry is not an object")
            continue
        comp_name = comp.get("name", "<unknown>")
        for fixture in comp.get("fixtures", []):
            if not isinstance(fixture, dict):
                errors.append(f"{comp_name}: fixture entry is not an object")
                continue
            median = fixture.get("primary_score_median")
            if median is None:
                errors.append(f"{comp_name}: fixture missing primary_score_median")
            elif not isinstance(median, (int, float)) or not (0.0 <= float(median) <= 1.0):
                errors.append(
                    f"{comp_name}: fixture primary_score_median {median!r} not in [0, 1]"
                )
            n_runs = fixture.get("n_runs")
            if n_runs is None:
                errors.append(f"{comp_name}: fixture missing n_runs")
            elif not isinstance(n_runs, int) or n_runs < 1:
                errors.append(f"{comp_name}: fixture n_runs {n_runs!r} < 1")
            status = fixture.get("status")
            if not status or not isinstance(status, str):
                errors.append(f"{comp_name}: fixture missing or empty status")

    # --- Step 6: environment.agentic_engineering_json is a dict ---
    env = data.get("environment", {})
    ae_json = env.get("agentic_engineering_json")
    if ae_json is None:
        # Explicit Python None in JSON = null; check if it was meant as explicit null
        # The schema says it should be a dict (or explicit null dict with "null" key)
        errors.append(
            "environment.agentic_engineering_json is JSON null - "
            "expected a dict or {'null': '<reason>'}"
        )
    elif not isinstance(ae_json, dict):
        errors.append(
            f"environment.agentic_engineering_json must be a dict, got {type(ae_json).__name__!r}"
        )
    # else: it's a dict - could be real config or {"null": "<reason>"}, both valid

    # --- Warnings (non-blocking) ---
    if isinstance(ae_json, dict) and "null" in ae_json:
        warnings.append(
            f"environment.agentic_engineering_json recorded as null with reason: "
            f"{ae_json['null']!r}"
        )

    env_claude_ver = env.get("claude_cli_version")
    if env_claude_ver is None:
        warnings.append("environment.claude_cli_version is null (claude CLI not available)")

    # manifest_enumeration consistency check (warning only if all_accounted_for=False)
    me = data.get("manifest_enumeration", {})
    if not me.get("all_accounted_for", True):
        warnings.append("manifest_enumeration.all_accounted_for is False")

    ok = len(errors) == 0
    return ValidationResult(ok=ok, errors=errors, warnings=warnings)


def main() -> None:
    import argparse
    parser = argparse.ArgumentParser(
        description="Validate an evals baseline JSON file against schema_version: 1.",
    )
    parser.add_argument("path", type=Path, help="Path to the baseline JSON file")
    args = parser.parse_args()

    result = validate_baseline(args.path)

    if result.warnings:
        for w in result.warnings:
            print(f"WARNING: {w}")

    if result.ok:
        print(f"OK: {args.path} validates against schema_version: 1")
        sys.exit(0)
    else:
        print(f"FAIL: {args.path} has {len(result.errors)} validation error(s):")
        for err in result.errors:
            print(f"  - {err}")
        sys.exit(1)


if __name__ == "__main__":
    main()
