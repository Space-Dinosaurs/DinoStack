# Purpose: Derive every enforcer-hook subcount this repo restates in prose
#          (total hook count, log_fire consumers, ACTION-ONLY vs
#          EVERY-VERDICT posture split) directly off `hooks/enforce-*.py`
#          source on disk, via an AST walk of each hook's fire-log call
#          sites. Extracted verbatim (DS-179) from
#          bin/tests/test_tracker_writeback_ranking_spec.py's round-5
#          `_derive_enforcer_facts()` / `_fire_log_decisions()` /
#          `_callee_name()` helpers, which now import this module instead
#          of defining the logic locally - see that test file's own
#          round-5 header comment for why a hand-typed cardinal is
#          rejected here: four prior hand-reconciliation rounds each
#          missed a prose site or pinned a stale value, so every consumer
#          of this module must derive its cardinals from the returned
#          dict, never restate one as a literal.
#
# Public API: derive_enforcer_facts(repo_root: Path) -> dict with keys
#             {hooks, total, consumers, by_decision, every_verdict,
#             action_only} - see the function's own docstring for the
#             exact shape. Return shape is FIXED: it must match what
#             bin/tests/test_tracker_writeback_ranking_spec.py's own
#             `_assert_derivation_is_not_vacuous()` and
#             `_ENFORCER_SUBCOUNT_SITES` sweep already expect, because that
#             test imports this function instead of defining it locally.
#
# Upstream deps: Python 3 stdlib only (ast, pathlib). Reads
#                `<repo_root>/hooks/enforce-*.py` source files; writes
#                nothing.
#
# Downstream consumers: bin/tests/test_tracker_writeback_ranking_spec.py
#                        (imports derive_enforcer_facts via
#                        importlib.util.spec_from_file_location, mirroring
#                        bin/tests/test_stamp_agent_fragments.py's import
#                        pattern); bin/ds-hook-fire-report (joins this
#                        module's per-hook posture split against
#                        `.agentic/.enforcement-fires.jsonl` fire counts).
#
# Failure modes: never raises on a well-formed hooks/ directory. A glob
#                that stops matching, or an AST walk that stops resolving
#                the local-wrapper call shape (see `_fire_log_decisions`
#                docstring), silently under-reports rather than raising -
#                callers that need to detect that failure mode call
#                `_assert_derivation_is_not_vacuous`-style floor
#                assertions on the returned dict themselves; this module
#                does not assert on its own output.
#
# Performance: one AST parse per hooks/enforce-*.py file (currently 15
#              files, low tens of KB each) - sub-second, no I/O beyond the
#              initial glob + read.

from __future__ import annotations

import ast
from pathlib import Path

# Every fire-log `decision` literal a hook can emit, matching the shared
# vocabulary hooks/lib/enforcement_log.py's log_fire() accepts. "allow_grant"
# added by enforce-ticket-batching.py's operator-granted mid-session
# exception (bin/ds-ticket-grant) - see that hook's own module docstring.
_FIRE_LOG_DECISIONS = ("deny", "allow", "allow_advisory", "allow_grant")


def _callee_name(func) -> str:
    """Resolve a call's callee name through an immediately-invoked call.

    `_load_log_fire()(data, name, decision, reason)` is the shape every hook
    uses - the callee of the OUTER call is itself a Call node, so a plain
    `func.id` lookup returns nothing and every derivation built on it is
    silently empty. That exact vacuity bit an earlier draft of this helper.
    """
    while isinstance(func, ast.Call):
        func = func.func
    return getattr(func, "id", None) or getattr(func, "attr", None) or ""


def _fire_log_decisions(src: str) -> set[str]:
    """Every fire-log `decision` literal a hook can emit, read from its AST.

    Two call shapes exist and both must be resolved or the derivation
    under-reports (an under-report is the dangerous direction here: it would
    shrink the every-verdict set and silently inflate the action-only count):

      1. Direct: `_load_log_fire()(data, "enforce-tier", "deny", reason)` -
         the lib signature, decision at positional index 2.
      2. Via a local wrapper: `enforce-no-abdication.py` and
         `enforce-ticket-batching.py` funnel their calls through a private
         helper that takes `decision` as a parameter and forwards it. The
         literals live at the WRAPPER's call sites, not at the log_fire call,
         so the wrapper is resolved to a sink first (fixed point) and its own
         `decision` parameter index is used.
    """
    tree = ast.parse(src)
    defs = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)}
    # name -> positional index of the `decision` argument.
    sinks = {"log_fire": 2, "_load_log_fire": 2}
    changed = True
    while changed:
        changed = False
        for name, fn in defs.items():
            if name in sinks:
                continue
            calls = [c for c in ast.walk(fn) if isinstance(c, ast.Call)]
            if not any(_callee_name(c) in sinks for c in calls):
                continue
            params = [a.arg for a in fn.args.args]
            if "decision" not in params:
                continue
            sinks[name] = params.index("decision")
            changed = True

    found = set()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _callee_name(node)
        if name not in sinks:
            continue
        idx = sinks[name]
        cands = []
        if len(node.args) > idx and isinstance(node.args[idx], ast.Constant):
            cands.append(node.args[idx].value)
        cands += [
            kw.value.value
            for kw in node.keywords
            if kw.arg == "decision" and isinstance(kw.value, ast.Constant)
        ]
        found |= {c for c in cands if c in _FIRE_LOG_DECISIONS}
    return found


def derive_enforcer_facts(repo_root: Path) -> dict:
    """Every enforcer subcount this repo restates in prose, derived off disk.

    Returns:
        {
          "hooks": set[str]              - basenames of hooks/enforce-*.py
          "total": int                   - len(hooks)
          "consumers": set[str]          - hooks that reference log_fire
          "by_decision": dict[str, set[str]] - decision literal -> hook names
          "every_verdict": set[str]      - hooks that log a plain "allow"
          "action_only": int             - len(consumers) - len(every_verdict)
        }

    Integers, not strings, so a caller cannot accidentally compare a word
    form against a numeral form and pass on a mismatch.
    """
    hooks = sorted((repo_root / "hooks").glob("enforce-*.py"))
    sources = {h.name: h.read_text(encoding="utf-8") for h in hooks}
    consumers = {name for name, src in sources.items() if "log_fire" in src}
    by_decision: dict[str, set[str]] = {d: set() for d in _FIRE_LOG_DECISIONS}
    for name, src in sources.items():
        for decision in _fire_log_decisions(src):
            by_decision[decision].add(name)
    every_verdict = by_decision["allow"]
    return {
        "hooks": {h.name for h in hooks},
        "total": len(hooks),
        "consumers": consumers,
        "by_decision": by_decision,
        "every_verdict": every_verdict,
        "action_only": len(consumers) - len(every_verdict),
    }
