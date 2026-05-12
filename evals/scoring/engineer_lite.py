"""
Purpose: Score a single Engineer run against a labeled fixture by parsing
         the mandatory structured return block (status header + fenced YAML
         block) defined in content/agents/engineer.md and checking four
         weighted dimensions: output format compliance, quality gate
         reporting completeness, acceptance criteria coverage, and scope
         discipline (absence of forbidden patterns).

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], diagnostic: dict,
             status: "ok" | "invalid_format",
             scorer_version: "v1"}.

Contract: score() expects a single-run trace (trace["runs"] has exactly one
          run record). Aggregation across N runs is the aggregator module's
          job. A multi-run trace is an API-misuse bug and asserts.

Upstream deps: stdlib re, yaml (pyyaml).

Downstream consumers: evals.runner.cli (dynamic import per manifest's
                      scoring_module field).

Failure modes: if the status header ("Status: DONE" etc.) is absent, returns
               status="invalid_format" and primary=0.0. If the fenced YAML
               block is present but malformed, partial credit is still
               awarded for the status header. Never raises; all errors are
               surfaced via status/diagnostic.

Performance: standard; regex-based parse of a short text blob.

---

## Scoring formula (v1)

Four weighted dimensions; weights sum to exactly 1.0 (runtime assertion).

    w_format    = 0.35  (status header present; fenced YAML block present
                         and contains required top-level keys: status,
                         files_modified, quality_gate_results)
    w_gates     = 0.25  (quality_gate_results block has lint/typecheck/test
                         fields with valid enum values; raw_output present
                         and non-empty; penalises "not_run" for gates that
                         should have been exercised per fixture)
    w_criteria  = 0.30  (fraction of fixture.acceptance_keywords found in
                         the full response; vacuous -> 1.0 if none specified)
    w_scope     = 0.10  (absence of forbidden_patterns from fixture; full
                         credit if none specified; 0.0 deduction per hit,
                         floor 0.0)

Format gate: if the status header is completely absent the run is
             invalid_format (primary 0.0, all scoring skipped).

### Version history

v1 (this commit): initial scorer. Four dimensions covering the engineer's
    three load-bearing protocol obligations (return format, quality-gate
    evidence, acceptance criterion coverage) plus a lightweight scope-
    discipline axis for fixtures that want to verify the engineer did not
    add unrequested changes.
"""
from __future__ import annotations

import re
from typing import Any

try:
    import yaml as _yaml
    _YAML_AVAILABLE = True
except ImportError:
    _YAML_AVAILABLE = False

SCORER_VERSION = "v1"

_W_FORMAT = 0.35
_W_GATES = 0.25
_W_CRITERIA = 0.30
_W_SCOPE = 0.10

_WEIGHTS_SUM_ASSERTION = abs(
    (_W_FORMAT + _W_GATES + _W_CRITERIA + _W_SCOPE) - 1.0
) < 1e-9
assert _WEIGHTS_SUM_ASSERTION, "engineer_lite weights must sum to 1.0"

# Status values recognised by the engineer spec.
_VALID_STATUSES = {"DONE", "DONE_WITH_CONCERNS", "NEEDS_CONTEXT", "BLOCKED"}

# Quality gate enum values recognised by the engineer spec.
_VALID_GATE_VALUES = {"pass", "fail", "not_run"}

# Required top-level keys in the fenced YAML block.
_REQUIRED_YAML_KEYS = {"status", "files_modified", "quality_gate_results"}

# Required keys inside quality_gate_results.
_REQUIRED_GATE_KEYS = {"lint", "typecheck", "test", "raw_output"}

# Regex to find "Status: <VALUE>" as the first non-blank line of the response.
_STATUS_HEADER_RE = re.compile(
    r"^\s*Status:\s*(DONE|DONE_WITH_CONCERNS|NEEDS_CONTEXT|BLOCKED)\b",
    re.MULTILINE,
)

# Regex to extract the first fenced YAML block (```yaml ... ``` or ```yml ... ```).
_YAML_BLOCK_RE = re.compile(
    r"```(?:yaml|yml)\s*\n(.*?)```",
    re.DOTALL | re.IGNORECASE,
)


def _extract_yaml_block(text: str) -> str | None:
    """Return the body of the first fenced YAML block, or None."""
    m = _YAML_BLOCK_RE.search(text)
    return m.group(1) if m else None


def _parse_yaml_block(block: str) -> dict | None:
    """Attempt to parse a YAML string; return the dict or None on failure."""
    if not _YAML_AVAILABLE:
        return None
    try:
        data = _yaml.safe_load(block)
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _score_format(text: str) -> tuple[float, dict]:
    """Score the structural completeness of the engineer's return."""
    status_match = _STATUS_HEADER_RE.search(text)
    status_present = status_match is not None
    status_value = status_match.group(1) if status_match else None

    if not status_present:
        return 0.0, {
            "status_header_present": False,
            "yaml_block_present": False,
            "yaml_parseable": False,
            "required_keys_present": [],
            "required_keys_missing": sorted(_REQUIRED_YAML_KEYS),
        }

    yaml_raw = _extract_yaml_block(text)
    yaml_present = yaml_raw is not None

    if not yaml_present:
        # Status header present but no YAML block - partial credit.
        return 0.4, {
            "status_header_present": True,
            "status_value": status_value,
            "yaml_block_present": False,
            "yaml_parseable": False,
            "required_keys_present": [],
            "required_keys_missing": sorted(_REQUIRED_YAML_KEYS),
        }

    parsed = _parse_yaml_block(yaml_raw)
    yaml_parseable = parsed is not None

    if not yaml_parseable:
        return 0.6, {
            "status_header_present": True,
            "status_value": status_value,
            "yaml_block_present": True,
            "yaml_parseable": False,
            "required_keys_present": [],
            "required_keys_missing": sorted(_REQUIRED_YAML_KEYS),
        }

    keys_present = [k for k in _REQUIRED_YAML_KEYS if k in parsed]
    keys_missing = [k for k in _REQUIRED_YAML_KEYS if k not in parsed]
    key_fraction = len(keys_present) / len(_REQUIRED_YAML_KEYS)

    # Full credit for status + block + parseable + all keys; partial otherwise.
    credit = 0.6 + 0.4 * key_fraction

    return credit, {
        "status_header_present": True,
        "status_value": status_value,
        "yaml_block_present": True,
        "yaml_parseable": True,
        "required_keys_present": sorted(keys_present),
        "required_keys_missing": sorted(keys_missing),
    }


def _score_gates(text: str) -> tuple[float, dict]:
    """Score quality gate reporting completeness."""
    yaml_raw = _extract_yaml_block(text)
    if not yaml_raw:
        return 0.0, {
            "reason": "no_yaml_block",
            "gate_fields_present": [],
            "gate_fields_valid": [],
            "raw_output_present": False,
        }

    parsed = _parse_yaml_block(yaml_raw)
    if not parsed:
        return 0.0, {
            "reason": "yaml_unparseable",
            "gate_fields_present": [],
            "gate_fields_valid": [],
            "raw_output_present": False,
        }

    qg = parsed.get("quality_gate_results")
    if not isinstance(qg, dict):
        return 0.0, {
            "reason": "quality_gate_results_missing_or_not_mapping",
            "gate_fields_present": [],
            "gate_fields_valid": [],
            "raw_output_present": False,
        }

    gate_keys = {"lint", "typecheck", "test"}
    fields_present = [k for k in gate_keys if k in qg]
    fields_valid = [
        k for k in fields_present
        if str(qg.get(k, "")).lower() in _VALID_GATE_VALUES
    ]
    raw_output = qg.get("raw_output")
    raw_present = isinstance(raw_output, str) and len(raw_output.strip()) > 0

    # Credit: (valid gate fields / 3) * 0.7 + raw_output present * 0.3
    gate_fraction = len(fields_valid) / len(gate_keys)
    credit = gate_fraction * 0.7 + (0.3 if raw_present else 0.0)

    return credit, {
        "gate_fields_present": sorted(fields_present),
        "gate_fields_valid": sorted(fields_valid),
        "gate_fields_invalid": sorted(
            k for k in fields_present if k not in fields_valid
        ),
        "raw_output_present": raw_present,
        "raw_output_len": len((raw_output or "").strip()),
    }


def _score_criteria(text: str, keywords: list[str]) -> tuple[float, dict]:
    """Fraction of acceptance_keywords found (case-insensitive) in the response."""
    if not keywords:
        return 1.0, {"vacuous": True, "hits": 0, "total": 0, "missing": []}
    lower = text.lower()
    hits = 0
    missing: list[str] = []
    for kw in keywords:
        if kw.lower() in lower:
            hits += 1
        else:
            missing.append(kw)
    return hits / len(keywords), {
        "vacuous": False,
        "hits": hits,
        "total": len(keywords),
        "missing": missing,
    }


def _score_scope(text: str, forbidden: list[str]) -> tuple[float, dict]:
    """Credit 1.0 if no forbidden patterns appear; deduct per hit, floor 0.0."""
    if not forbidden:
        return 1.0, {"vacuous": True, "hits": [], "total_patterns": 0}
    hits: list[str] = []
    for pattern in forbidden:
        if pattern.lower() in text.lower():
            hits.append(pattern)
    credit = max(0.0, 1.0 - len(hits) / len(forbidden))
    return credit, {
        "vacuous": False,
        "hits": hits,
        "total_patterns": len(forbidden),
    }


def score(trace: dict, fixture: dict) -> dict:
    """Score one engineer run against a fixture.

    Parameters
    ----------
    trace:
        Dict with a "runs" key containing exactly one run record. Each run
        record must have a "final_text" key with the agent's full response.
    fixture:
        The raw fixture dict (fixture.raw from the loader). Expected keys:
        - inputs.acceptance_keywords (list[str], optional)
        - inputs.forbidden_patterns (list[str], optional)
    """
    runs = trace.get("runs") or []
    if not runs:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {"reason": "no_runs", "scorer_version": SCORER_VERSION},
            "scorer_version": SCORER_VERSION,
        }
    assert len(runs) == 1, (
        "engineer_lite.score expects a single-run trace; aggregation "
        "across N runs happens in evals.runner.aggregator, not here."
    )

    run = runs[0]
    text = run.get("final_text") or ""

    # Format gate: status header must be present.
    if not _STATUS_HEADER_RE.search(text):
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {
                "reason": "no_status_header",
                "final_text_preview": text[:400],
                "scorer_version": SCORER_VERSION,
            },
            "scorer_version": SCORER_VERSION,
        }

    inputs = fixture.get("inputs") or {}
    if not isinstance(inputs, dict):
        inputs = {}
    acceptance_keywords = list(inputs.get("acceptance_keywords") or [])
    forbidden_patterns = list(inputs.get("forbidden_patterns") or [])

    format_credit, format_detail = _score_format(text)
    gates_credit, gates_detail = _score_gates(text)
    criteria_credit, criteria_detail = _score_criteria(text, acceptance_keywords)
    scope_credit, scope_detail = _score_scope(text, forbidden_patterns)

    primary_raw = (
        _W_FORMAT * format_credit
        + _W_GATES * gates_credit
        + _W_CRITERIA * criteria_credit
        + _W_SCOPE * scope_credit
    )
    primary = max(0.0, min(1.0, primary_raw))

    diagnostic: dict[str, Any] = {
        "format": format_detail,
        "gates": gates_detail,
        "criteria": criteria_detail,
        "scope": scope_detail,
        "weights": {
            "format": _W_FORMAT,
            "gates": _W_GATES,
            "criteria": _W_CRITERIA,
            "scope": _W_SCOPE,
        },
        "scorer_version": SCORER_VERSION,
    }

    return {
        "primary": round(primary, 6),
        "status": "ok",
        "diagnostic": diagnostic,
        "scorer_version": SCORER_VERSION,
    }
