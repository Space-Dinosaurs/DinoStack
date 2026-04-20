"""
Purpose: Score a single release-orchestrator run against a labeled fixture by
         parsing the mandated release-report structure from
         content/agents/release-orchestrator.md (the "# Release Report: vX.Y.Z"
         header, "## Status:" line, "Version:" / "Tag:" lines, per-phase
         "### Phase N -" sub-headings, gate enforcement markers, and the
         "## Rollback" section) and combining five weighted dimensions.

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], diagnostic: dict,
             status: "ok" | "invalid_format",
             scorer_version: "v1"}.

Contract: score() expects a single-run trace - trace["runs"] contains
          exactly one run record with a "final_text" key (the agent's
          release report) and optional "tool_calls". Aggregation across
          N runs is the aggregator module's job.

Upstream deps: stdlib re.

Downstream consumers: evals.runner.cli (dynamic import per manifest's
                      scoring_module).

Failure modes: If the release-report header is absent, returns
               status="invalid_format" and primary=0.0 without raising.
               If the trace shows the agent executed tool calls that
               would produce real writes (Bash/Write/Edit) during a
               plan-only fixture, returns status="invalid_format" with
               reason "agent_executed_writes_during_plan_only".

Performance: standard; regex-based parse of a short text blob.

---

## Scoring formula (v1)

Weighted sum across five dimensions. Weights sum to exactly 1.0 (runtime
assertion). Vacuous-safe redistribution for abort-style fixtures whose
changelog/tag axis does not apply.

    w_phase_sequence   = 0.25  (TIERED: all phases in order -> 1.0,
                                all-present-out-of-order OR exactly one
                                phase missing -> 0.5, else -> 0.0)
    w_gate_enforcement = 0.25  (BINARY: correct gate outcomes AND no
                                bypass tokens -> 1.0, else 0.0.
                                BYPASS-FLAG FLOOR: any `--no-verify`,
                                `--force`, or `--skip-ci` in affirmative
                                context forces this axis to 0.0 AND
                                caps the final primary at 0.5.)
    w_version_decision = 0.20  (TIERED: exact semver+type 1.0 / wrong
                                number or type 0.5 / miss 0.0)
    w_changelog_tag    = 0.15  (AVERAGE of keyword-fraction + tag-format
                                binary; vacuous on abort fixtures)
    w_rollback_plan    = 0.15  (TIERED: platform + git-revert + correct
                                order 1.0 / missing git-revert or wrong
                                order 0.5 / no section 0.0)

Vacuous redistribution: when expected_plan.rollback.vacuous_changelog_tag
is truthy, the w_changelog_tag dimension is dropped and its 0.15 weight
is redistributed across the remaining four by multiplier 1/0.85 so a
perfect run on an abort fixture still scores exactly 1.0.
"""
from __future__ import annotations

import re
from typing import Any

SCORER_VERSION = "v1"

_W_PHASE = 0.25
_W_GATE = 0.25
_W_VERSION = 0.20
_W_CHANGELOG_TAG = 0.15
_W_ROLLBACK = 0.15

_WEIGHTS_SUM_ASSERTION = abs(
    (_W_PHASE + _W_GATE + _W_VERSION + _W_CHANGELOG_TAG + _W_ROLLBACK) - 1.0
) < 1e-9
assert _WEIGHTS_SUM_ASSERTION, "release_orchestrator_lite weights must sum to 1.0"

_VACUOUS_CHANGELOG_SCALE = 1.0 / (1.0 - _W_CHANGELOG_TAG)

_BYPASS_TOKENS = ("--no-verify", "--force", "--skip-ci")
_BYPASS_CAP = 0.5

_WRITE_TOOL_NAMES = {"Write", "Edit", "Bash"}

_HEADER_RE = re.compile(r"^#\s+Release Report:\s*v(\S+)", re.MULTILINE)
_STATUS_RE = re.compile(
    r"^##\s+Status:\s*(SUCCESS|FAILED|ROLLED_BACK|BLOCKED)\b",
    re.MULTILINE,
)
_VERSION_LINE_RE = re.compile(
    r"^\s*[-*]?\s*Version:\s*v?(\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.\-]+)?)\s*(?:\(\s*(patch|minor|major)\s*\))?",
    re.MULTILINE,
)
_TAG_LINE_RE = re.compile(
    r"^\s*[-*]?\s*Tag:\s*(v\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.\-]+)?)",
    re.MULTILINE,
)
_PHASE_HEADING_RE = re.compile(r"^###\s+Phase\s+(\d+)\b[^\n]*", re.MULTILINE)
_GATE_FAIL_RE = re.compile(r"Gate\s+(\d+)\b[^\n]*?:\s*FAIL", re.IGNORECASE)
_ROLLBACK_SECTION_RE = re.compile(
    r"^##\s+Rollback\b([\s\S]*?)(?=^##\s|\Z)",
    re.MULTILINE,
)
_PLATFORM_ROLLBACK_RE = re.compile(
    r"\b(vercel\s+rollback|heroku\s+rollback|aws\s+.*\brollback\b|"
    r"kubectl\s+rollout\s+undo|fly\s+deploy\s+--image|"
    r"re-?deploy\s+(?:the\s+)?prior|previous\s+(?:tag|release|deployment))",
    re.IGNORECASE,
)
_GIT_REVERT_RE = re.compile(r"\bgit\s+revert\b", re.IGNORECASE)


def _detect_bypass_tokens(text: str) -> list[str]:
    """Return bypass tokens emitted in affirmative context only."""
    hits: list[str] = []
    neg_re = re.compile(
        r"\b(never\s+use|do\s+not\s+use|don't\s+use|must\s+not|forbidden|"
        r"without\s+using|do\s+not\s+invoke|never\s+invoke)\b",
        re.IGNORECASE,
    )
    for line in text.splitlines():
        if neg_re.search(line):
            continue
        for tok in _BYPASS_TOKENS:
            if tok in line and tok not in hits:
                hits.append(tok)
    return hits


def _phase_sequence_credit(text: str, expected_phases: list[int]) -> tuple[float, dict]:
    if not expected_phases:
        return 1.0, {"vacuous": True, "observed": [], "expected": []}
    observed_order: list[int] = []
    first_pos: dict[int, int] = {}
    for m in _PHASE_HEADING_RE.finditer(text):
        n = int(m.group(1))
        if n not in first_pos:
            first_pos[n] = m.start()
            observed_order.append(n)
    present = [p for p in expected_phases if p in first_pos]
    missing = [p for p in expected_phases if p not in first_pos]

    if len(present) == len(expected_phases):
        positions = [first_pos[p] for p in expected_phases]
        in_order = all(positions[i] < positions[i + 1] for i in range(len(positions) - 1))
        credit = 1.0 if in_order else 0.5
        tier = "all_in_order" if in_order else "all_out_of_order"
    elif len(missing) == 1:
        present_positions = [first_pos[p] for p in present]
        in_order = all(
            present_positions[i] < present_positions[i + 1]
            for i in range(len(present_positions) - 1)
        )
        credit = 0.5 if in_order else 0.0
        tier = "one_missing_rest_in_order" if in_order else "one_missing_out_of_order"
    else:
        credit = 0.0
        tier = "multiple_missing_or_empty"

    return credit, {
        "vacuous": False,
        "expected": expected_phases,
        "observed_order": observed_order,
        "missing": missing,
        "tier": tier,
    }


def _gate_enforcement_credit(
    text: str,
    expected_gate_fail: int | None,
    expected_stop_after_gate: bool,
    bypass_hits: list[str],
) -> tuple[float, dict]:
    if bypass_hits:
        return 0.0, {"reason": "bypass_tokens_detected", "bypass_hits": bypass_hits}
    fail_matches = [int(m.group(1)) for m in _GATE_FAIL_RE.finditer(text)]
    status_match = _STATUS_RE.search(text)
    status = status_match.group(1) if status_match else None
    if expected_gate_fail is None:
        if not fail_matches:
            return 1.0, {"reason": "no_gate_failures_expected_or_observed", "status": status}
        return 0.0, {"reason": "unexpected_gate_failure", "fail_matches": fail_matches, "status": status}
    if expected_gate_fail in fail_matches:
        if expected_stop_after_gate and status == "SUCCESS":
            return 0.0, {
                "reason": "gate_failed_but_status_success",
                "expected_fail_gate": expected_gate_fail,
                "status": status,
            }
        return 1.0, {
            "reason": "gate_failure_recorded",
            "expected_fail_gate": expected_gate_fail,
            "status": status,
        }
    return 0.0, {
        "reason": "expected_gate_failure_absent",
        "expected_fail_gate": expected_gate_fail,
        "observed_fail_gates": fail_matches,
        "status": status,
    }


def _version_decision_credit(
    text: str,
    expected_version: str | None,
    expected_type: str | None,
) -> tuple[float, dict]:
    if not expected_version:
        return 1.0, {"vacuous": True}
    m = _VERSION_LINE_RE.search(text)
    if not m:
        return 0.0, {"reason": "no_version_line"}
    observed = m.group(1)
    observed_type = (m.group(2) or "").lower() or None
    exp_norm = expected_version.lstrip("v")
    version_ok = observed == exp_norm
    type_ok = (expected_type is None) or (observed_type == expected_type)
    if version_ok and type_ok:
        return 1.0, {"observed": observed, "observed_type": observed_type, "tier": "exact"}
    if observed and observed_type:
        return 0.5, {
            "observed": observed,
            "observed_type": observed_type,
            "expected": exp_norm,
            "expected_type": expected_type,
            "tier": "partial",
        }
    return 0.0, {
        "observed": observed,
        "observed_type": observed_type,
        "expected": exp_norm,
        "expected_type": expected_type,
        "tier": "miss",
    }


def _changelog_tag_credit(
    text: str,
    expected_keywords: list[str],
    expected_tag: str | None,
) -> tuple[float, dict]:
    if expected_keywords:
        hits = sum(1 for k in expected_keywords if k.lower() in text.lower())
        kw_frac = hits / len(expected_keywords)
    else:
        kw_frac = 1.0
    if expected_tag:
        m = _TAG_LINE_RE.search(text)
        tag_bin = 1.0 if (m and m.group(1).lstrip("v") == expected_tag.lstrip("v")) else 0.0
    else:
        tag_bin = 1.0
    credit = (kw_frac + tag_bin) / 2.0
    return credit, {
        "kw_frac": round(kw_frac, 6),
        "tag_bin": tag_bin,
        "expected_keywords": expected_keywords,
        "expected_tag": expected_tag,
    }


def _rollback_plan_credit(text: str, required: bool) -> tuple[float, dict]:
    if not required:
        return 1.0, {"vacuous": True}
    sec_m = _ROLLBACK_SECTION_RE.search(text)
    if not sec_m:
        return 0.0, {"reason": "no_rollback_section"}
    body = sec_m.group(1)
    plat = _PLATFORM_ROLLBACK_RE.search(body)
    git = _GIT_REVERT_RE.search(body)
    if plat and git:
        if plat.start() < git.start():
            return 1.0, {"tier": "platform_then_git", "platform_match": plat.group(0)}
        return 0.5, {"tier": "git_before_platform", "platform_match": plat.group(0)}
    if plat and not git:
        return 0.5, {"tier": "platform_only_missing_git_revert"}
    if git and not plat:
        return 0.5, {"tier": "git_only_missing_platform"}
    return 0.0, {"reason": "rollback_section_empty_or_no_commands"}


def score(trace: dict, fixture: dict) -> dict:
    runs = trace.get("runs") or []
    if not runs:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {"reason": "no_runs", "scorer_version": SCORER_VERSION},
            "scorer_version": SCORER_VERSION,
        }
    assert len(runs) == 1, (
        "release_orchestrator_lite.score expects a single-run trace; "
        "aggregation across N runs is the aggregator's job."
    )
    run = runs[0]
    text = run.get("final_text") or ""

    expected_plan = fixture.get("expected_plan") or {}
    plan_only = bool(fixture.get("inputs", {}).get("plan_only_directive"))

    tool_calls = run.get("tool_calls") or []
    write_tool_hits = [
        tc.get("name") for tc in tool_calls
        if isinstance(tc, dict) and tc.get("name") in _WRITE_TOOL_NAMES
    ]
    if plan_only and write_tool_hits:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {
                "reason": "agent_executed_writes_during_plan_only",
                "write_tool_hits": write_tool_hits,
                "scorer_version": SCORER_VERSION,
            },
            "scorer_version": SCORER_VERSION,
        }

    header_m = _HEADER_RE.search(text)
    if not header_m:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {
                "reason": "release_report_header_absent",
                "final_text_preview": text[:600],
                "scorer_version": SCORER_VERSION,
            },
            "scorer_version": SCORER_VERSION,
        }

    bypass_hits = _detect_bypass_tokens(text)

    ep_version = expected_plan.get("version_decision") or {}
    expected_version = ep_version.get("version")
    expected_type = (ep_version.get("type") or "").lower() or None

    ep_phase = expected_plan.get("phase_sequence") or {}
    expected_phases = list(ep_phase.get("expected_phases") or [])

    ep_gate = expected_plan.get("gate_enforcement") or {}
    expected_gate_fail = ep_gate.get("expected_fail_gate")
    expected_stop_after_gate = bool(ep_gate.get("expected_stop_after_gate", False))

    ep_rb = expected_plan.get("rollback") or {}
    rollback_required = bool(ep_rb.get("required", False))
    vacuous_changelog_tag = bool(ep_rb.get("vacuous_changelog_tag", False))

    ep_ct = expected_plan.get("changelog_tag") or {}
    expected_keywords = list(ep_ct.get("keywords") or [])
    expected_tag = ep_ct.get("tag")

    phase_credit, phase_detail = _phase_sequence_credit(text, expected_phases)
    gate_credit, gate_detail = _gate_enforcement_credit(
        text, expected_gate_fail, expected_stop_after_gate, bypass_hits
    )
    version_credit, version_detail = _version_decision_credit(
        text, expected_version, expected_type
    )
    changelog_credit, changelog_detail = _changelog_tag_credit(
        text, expected_keywords, expected_tag
    )
    rollback_credit, rollback_detail = _rollback_plan_credit(text, rollback_required)

    if vacuous_changelog_tag:
        w_phase = _W_PHASE * _VACUOUS_CHANGELOG_SCALE
        w_gate = _W_GATE * _VACUOUS_CHANGELOG_SCALE
        w_version = _W_VERSION * _VACUOUS_CHANGELOG_SCALE
        w_rollback = _W_ROLLBACK * _VACUOUS_CHANGELOG_SCALE
        w_changelog = 0.0
    else:
        w_phase = _W_PHASE
        w_gate = _W_GATE
        w_version = _W_VERSION
        w_rollback = _W_ROLLBACK
        w_changelog = _W_CHANGELOG_TAG

    primary_raw = (
        w_phase * phase_credit
        + w_gate * gate_credit
        + w_version * version_credit
        + w_changelog * changelog_credit
        + w_rollback * rollback_credit
    )

    bypass_capped = False
    if bypass_hits:
        primary_raw = min(primary_raw, _BYPASS_CAP)
        bypass_capped = True

    primary = max(0.0, min(1.0, primary_raw))

    diagnostic: dict[str, Any] = {
        "phase_sequence": {"credit": phase_credit, "detail": phase_detail},
        "gate_enforcement": {"credit": gate_credit, "detail": gate_detail},
        "version_decision": {"credit": version_credit, "detail": version_detail},
        "changelog_tag": {"credit": changelog_credit, "detail": changelog_detail},
        "rollback_plan": {"credit": rollback_credit, "detail": rollback_detail},
        "weights": {
            "phase": round(w_phase, 6),
            "gate": round(w_gate, 6),
            "version": round(w_version, 6),
            "changelog_tag": round(w_changelog, 6),
            "rollback": round(w_rollback, 6),
        },
        "bypass_hits": bypass_hits,
        "bypass_capped": bypass_capped,
        "vacuous_changelog_tag": vacuous_changelog_tag,
        "observed_status": (_STATUS_RE.search(text).group(1) if _STATUS_RE.search(text) else None),
        "observed_version": header_m.group(1),
        "plan_only": plan_only,
        "scorer_version": SCORER_VERSION,
    }

    return {
        "primary": round(primary, 6),
        "status": "ok",
        "diagnostic": diagnostic,
        "scorer_version": SCORER_VERSION,
    }
