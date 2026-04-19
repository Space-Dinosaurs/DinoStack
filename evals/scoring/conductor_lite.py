"""
Purpose: Score a single orchestration-planner (conductor) routing-decision
         run against a labeled fixture. Parses the mandated "Routing decision
         (machine-readable)" fenced JSON block from the subagent's final text
         and computes a weighted multi-dimensional accuracy primary with
         per-dimension diagnostics.

Public API: score(trace: dict, fixture: dict) -> dict with keys
            {primary: float in [0, 1], diagnostic: dict,
             status: "ok" | "invalid_format",
             scorer_version: "v1"}.

Contract: score() expects a single-run trace - trace["runs"] contains exactly
          one run record. N-run aggregation is the aggregator's job.

Upstream deps: stdlib re, json.

Downstream consumers: evals.runner.cli (via dynamic import per manifest's
                      scoring_module field).

Failure modes: If the required "## Routing decision (machine-readable)"
               heading + fenced JSON block is absent or the JSON is
               malformed, returns status="invalid_format" and primary=0.0
               without raising.

Performance: standard; regex + json parse of a short text blob.

---

## Scoring formula (v1: weighted multi-dimensional accuracy)

Asymmetric by dimension: the decision_class carries full weight (1.0); the
next_agent (when expected) is a 0.5 weight sub-dimension; the loop_action
(when expected) is a 0.25 weight sub-dimension. must_not_select is a hard
penalty: if the chosen next_agent (or decision_class) is in the fixture's
must_not_select list, 1.0 is subtracted before clipping. This captures the
conductor-methodology asymmetry that wrongly spawning an Engineer on a
cap-reached escalation is worse than getting the broad decision right but
the loop_action label imprecise.

    decision_hit = 1.0 if decision_class matches, else 0.0
    agent_hit    = 1.0 if next_agent matches (and was expected), else 0.0
    loop_hit     = 1.0 if loop_action matches (and was expected), else 0.0

    agent_weight  = 0.5 if expected_next_agent is not None else 0.0
    loop_weight   = 0.25 if expected_loop_action is not None else 0.0

    denom = 1.0 + agent_weight + loop_weight
    numer = decision_hit
          + (agent_weight * agent_hit if expected_next_agent else 0)
          + (loop_weight  * loop_hit  if expected_loop_action else 0)

    must_not_penalty = 1.0 if chosen next_agent or decision_class is in
                             expected.must_not_select, else 0.0

    primary = clip((numer - must_not_penalty) / denom, 0.0, 1.0)

cost_class is NOT folded into the primary scalar. Folding it in would make
the primary unbounded (a single "critical" fixture could outweigh many
"low" ones) and would conflate two different questions: "did the conductor
pick the right routing?" vs. "how much does this specific fixture matter
for triage?". cost_class rides in diagnostic only and drives fixture
prioritization / stdev triage at the aggregator level. This is a known
limitation, documented here and in evals/fixtures/conductor/README.md.

### Worked examples

Fixture shapes taken from the 10-fixture corpus.

1. co-001 (escalate_cap_reached, must_not=[engineer, skeptic]).
   Expected: decision_class=escalate_cap_reached, next_agent=null,
   loop_action=exit_stalled.
   Perfect response: decision_hit=1, loop_hit=1. agent_weight=0 (no expected
   next_agent). denom = 1 + 0 + 0.25 = 1.25. numer = 1 + 0 + 0.25 = 1.25.
   primary = 1.0.
   Bad response (chose re_enter_loop, next_agent=engineer):
   decision_hit=0, loop_hit=0. must_not_penalty=1.0 (engineer in must_not).
   primary = clip((0 - 1) / 1.25, 0, 1) = 0.0.

2. co-005 (re_enter_loop, expected next_agent=engineer, loop_action=re_enter).
   Perfect: decision_hit=1, agent_hit=1, loop_hit=1.
   denom = 1 + 0.5 + 0.25 = 1.75. numer = 1 + 0.5 + 0.25 = 1.75.
   primary = 1.0.
   Right decision, wrong agent (e.g. skeptic): decision_hit=1, agent_hit=0.
   numer = 1 + 0 + 0.25 = 1.25. primary = 1.25/1.75 = 0.714.

3. co-006 (trivial_direct_edit, next_agent=null, loop_action=null,
   must_not=[engineer, skeptic, qa-engineer]).
   Perfect: decision_hit=1. denom = 1.0. primary = 1.0.
   Wrong (spawns engineer): decision_hit=0. must_not_penalty=1.0.
   primary = clip((0 - 1) / 1.0, 0, 1) = 0.0.

4. co-010 (spawn_agent: security-auditor).
   Perfect: decision_hit=1, agent_hit=1. loop_action expected=null.
   denom = 1.5. numer = 1.5. primary = 1.0.
   Spawned engineer instead: decision_hit=1 (still spawn_agent), agent_hit=0.
   numer = 1 + 0 + 0 = 1.0. primary = 1.0/1.5 = 0.667.
   (No must_not penalty because engineer is not in must_not here.)

### Rationale-keyword coverage (diagnostic only)

The fraction of fixture.expected_decision.rationale_keywords that appear in
the parsed rationale string (case-insensitive substring). Not folded into
primary - rationale quality is noisy and would penalize valid syntactic
paraphrases. Surfaces in diagnostic as rationale_kw_coverage for eye-
balling.
"""
from __future__ import annotations

import json
import re
from typing import Any

SCORER_VERSION = "v1"

# The conductor's response MUST end with this heading followed by a fenced
# JSON code block. We anchor on the heading to avoid false matches on JSON
# code blocks elsewhere in the response (e.g. example snippets).
_DECISION_BLOCK_RE = re.compile(
    r"##\s*Routing\s+decision\s*\(machine-readable\)\s*\n+"
    r"```(?:json)?\s*\n(.*?)\n```",
    re.IGNORECASE | re.DOTALL,
)


def _extract_decision(text: str) -> tuple[dict | None, str]:
    """Return (parsed_dict, reason_if_invalid). reason is empty on success."""
    m = _DECISION_BLOCK_RE.search(text or "")
    if not m:
        return None, "decision_block_not_found"
    payload = m.group(1).strip()
    try:
        parsed = json.loads(payload)
    except json.JSONDecodeError as e:
        return None, f"json_decode_error: {e}"
    if not isinstance(parsed, dict):
        return None, "decision_payload_not_object"
    required = {"decision_class", "next_agent", "loop_action", "rationale"}
    missing = required - set(parsed.keys())
    if missing:
        return None, f"missing_fields: {sorted(missing)}"
    return parsed, ""


def _rationale_kw_coverage(rationale: str, keywords: list[str]) -> float:
    if not keywords:
        return 1.0
    r_low = (rationale or "").lower()
    hits = sum(1 for kw in keywords if kw and kw.lower() in r_low)
    return round(hits / len(keywords), 6)


def score(trace: dict, fixture: dict) -> dict:
    runs = trace.get("runs") or []
    if not runs:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {"reason": "no_runs"},
            "scorer_version": SCORER_VERSION,
        }
    assert len(runs) == 1, (
        "conductor_lite.score expects a single-run trace; aggregation across N "
        "runs happens in evals.runner.aggregator, not here."
    )

    run = runs[0]
    text = run.get("final_text") or ""
    parsed, reason = _extract_decision(text)
    if parsed is None:
        return {
            "primary": 0.0,
            "status": "invalid_format",
            "diagnostic": {
                "reason": reason,
                "final_text_preview": text[:600],
            },
            "scorer_version": SCORER_VERSION,
        }

    expected = fixture.get("expected_decision") or {}
    exp_dc = expected.get("decision_class")
    exp_na = expected.get("next_agent")
    exp_la = expected.get("loop_action")
    cost_class = expected.get("cost_class")
    rationale_keywords = expected.get("rationale_keywords") or []
    must_not_select = set(expected.get("must_not_select") or [])

    got_dc = parsed.get("decision_class")
    got_na = parsed.get("next_agent")
    got_la = parsed.get("loop_action")
    got_rationale = parsed.get("rationale") or ""

    decision_hit = 1.0 if got_dc == exp_dc else 0.0

    if exp_na is not None:
        agent_weight = 0.5
        agent_hit = 1.0 if got_na == exp_na else 0.0
    else:
        agent_weight = 0.0
        agent_hit = 0.0

    if exp_la is not None:
        loop_weight = 0.25
        loop_hit = 1.0 if got_la == exp_la else 0.0
    else:
        loop_weight = 0.0
        loop_hit = 0.0

    denom = 1.0 + agent_weight + loop_weight
    numer = decision_hit + agent_weight * agent_hit + loop_weight * loop_hit

    must_not_penalty = 0.0
    if got_na in must_not_select or got_dc in must_not_select:
        must_not_penalty = 1.0

    primary_raw = (numer - must_not_penalty) / denom if denom > 0 else 0.0
    primary = max(0.0, min(1.0, primary_raw))

    diagnostic: dict[str, Any] = {
        "decision_hit": decision_hit,
        "agent_hit": agent_hit if exp_na is not None else None,
        "loop_hit": loop_hit if exp_la is not None else None,
        "must_not_penalty": must_not_penalty,
        "cost_class": cost_class,
        "rationale_kw_coverage": _rationale_kw_coverage(got_rationale, rationale_keywords),
        "parsed_decision": {
            "decision_class": got_dc,
            "next_agent": got_na,
            "loop_action": got_la,
            "rationale": got_rationale,
        },
        "expected_decision": {
            "decision_class": exp_dc,
            "next_agent": exp_na,
            "loop_action": exp_la,
            "cost_class": cost_class,
            "must_not_select": sorted(must_not_select),
        },
        "score_components": {
            "numer": round(numer, 6),
            "denom": round(denom, 6),
            "agent_weight": agent_weight,
            "loop_weight": loop_weight,
        },
        "scorer_version": SCORER_VERSION,
    }

    return {
        "primary": round(primary, 6),
        "status": "ok",
        "diagnostic": diagnostic,
        "scorer_version": SCORER_VERSION,
    }
