#!/usr/bin/env python3
"""
Purpose: PreToolUse hook that enforces the METHODOLOGY §Delegation AskUserQuestion
         precondition by denying any single-select AskUserQuestion call that
         presents 2+ options with no recommended default. Converts the prose
         "no multiple-choice ballots" rule into a hard gate on Claude Code: a
         co-equal ballot offloads the conductor's own decision onto the operator.
         The recommended option must carry a label ending in "(Recommended)";
         that token is what this hook keys on. Feeds the deny reason back to the
         model so it can re-issue correctly or proceed without AskUserQuestion.
         Confirmed-supported floor: Claude Code 2.1.178+ (the modern
         permissionDecision: "deny" path this hook emits is stable from that
         release). The hook fails open on parse error, so older builds degrade
         to no-enforcement rather than breaking.

Public API: Run as a Claude Code PreToolUse hook. Reads JSON from stdin,
            writes hookSpecificOutput JSON to stdout when denying, exits 0 always.

Upstream deps: Python 3 stdlib only (json, sys, importlib.util). No external
               dependencies. Best-effort dynamic import of the sibling
               hooks/lib/enforcement_log.py fire-logging helper (see G2 in
               MEMORY.md / this hook's Failure modes) - a failed import
               degrades to a no-op logger, never a crash.

Downstream consumers: Claude Code hook runner (PreToolUse event for the
                      AskUserQuestion tool). Wired via ~/.claude/settings.json
                      by .claude/install.sh.

Failure modes:
    - Malformed stdin: fail-open (exit 0, no deny). A hook bug must never brick
      all AskUserQuestion calls - enforcement gaps are preferable to blanket
      blocks.
    - Null or non-dict tool_input: fail-open (exit 0). Same contract.
    - Non-AskUserQuestion tool_name: passthrough (exit 0). Scoped to that tool.
    - questions not a list: fail-open (exit 0). Cannot evaluate the ballot shape.
    - Non-dict question entries: skipped (cannot evaluate). Other entries still
      checked.
    - A single-select question with 2+ options and no "(Recommended)" label:
      deny with reason fed back to model. multiSelect: true, single-option, and
      any option labelled "(Recommended)" all allow.
    - Older Claude Code versions (pre-permissionDecision support, issue #4669):
      if a future version ignores permissionDecision: deny, switch to exit 2 with
      the reason on stderr as the fallback enforcement path.
    - Fire-log write failure (hooks/lib/enforcement_log.py unimportable, disk
      full, unwritable .agentic/, OR a raising log_fire from a signature
      mismatch on a half-applied lib snapshot): never affects the deny
      decision or this hook's own exit code. Two layers of protection: (1)
      the deny decision is printed to stdout BEFORE the lib is even loaded
      or called, so the decision has already reached the model regardless of
      what happens next; (2) the load-and-call is additionally wrapped in
      its own try/except at the call site, so a raise there cannot even
      reach the outer except handler or produce stderr noise.

Performance: < 1 ms per call (pure in-memory JSON parse + bounded iteration over
             questions/options + single print, no I/O).
"""

import json
import os
import sys


def _load_log_fire():
    """Best-effort dynamic import of the shared fire-logging helper.

    Falls back to a no-op when the sibling module cannot be loaded (missing
    file, syntax error, snapshot copy drift) - fire-logging is additive
    telemetry, never a hard dependency of the enforcement decision itself.

    Called lazily from inside the deny branch (never at module scope) so the
    overwhelming majority of invocations - every silent allow - never read,
    compile, or exec this file at all.
    """
    try:
        import importlib.util as _ilu

        here = os.path.dirname(os.path.abspath(__file__))
        mod_path = os.path.join(here, "lib", "enforcement_log.py")
        spec = _ilu.spec_from_file_location("enforcement_log", mod_path)
        mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.log_fire
    except Exception:
        return lambda *a, **k: None


def _has_recommended_label(options) -> bool:
    """True if any option in the list has a label containing '(recommended)'."""
    for opt in options:
        if not isinstance(opt, dict):
            continue
        label = opt.get("label")
        if isinstance(label, str) and "(recommended)" in label.lower():
            return True
    return False


def main() -> None:
    try:
        # Fail-open: never block on malformed input - a broken hook must not
        # prevent the conductor from asking the operator at all.
        try:
            data = json.load(sys.stdin)
        except Exception:
            sys.exit(0)

        # Only enforce on AskUserQuestion. All other tools passthrough.
        if data.get("tool_name") != "AskUserQuestion":
            sys.exit(0)

        # tool_input may be null/missing. Treat as fail-open since we cannot
        # make an enforcement decision without a dict to inspect.
        raw_tinput = data.get("tool_input")
        if raw_tinput is None:
            sys.exit(0)
        tinput = raw_tinput if isinstance(raw_tinput, dict) else {}

        questions = tinput.get("questions")
        if not isinstance(questions, list):
            sys.exit(0)

        # Deny iff ANY question is a single-select co-equal ballot: not
        # multiSelect, 2+ options, and no option labelled "(Recommended)".
        deny = False
        for q in questions:
            if not isinstance(q, dict):
                continue
            if q.get("multiSelect") is True:
                continue
            options = q.get("options")
            if not isinstance(options, list) or len(options) < 2:
                continue
            if _has_recommended_label(options):
                continue
            deny = True
            break

        if not deny:
            sys.exit(0)

        deny_reason = (
            "AskUserQuestion blocked: a single-select question presents 2+ "
            "options with no recommended default. Per METHODOLOGY.md "
            "§Delegation (AskUserQuestion precondition), a multiple-choice "
            "ballot is disallowed when a best option is derivable. Derive "
            "the best option from the six default sources, then EITHER "
            "proceed with it directly (no AskUserQuestion call) OR re-issue "
            'with exactly one option whose label ends in "(Recommended)" '
            "and proceed-unless-told-otherwise framing. Genuinely "
            "irreversible AND unauthorized confirmations are exempt - mark "
            'the recommended option\'s label "(Recommended)" to pass.'
        )
        # Decision print comes FIRST, unconditionally. Telemetry is loaded
        # and called only after the decision has reached stdout, and is
        # wrapped in its own try/except so a raising log_fire (e.g. a
        # signature mismatch from a half-applied lib snapshot) can never
        # suppress or follow this deny - see hooks/lib/enforcement_log.py
        # manifest "Failure modes".
        print(
            json.dumps(
                {
                    "hookSpecificOutput": {
                        "hookEventName": "PreToolUse",
                        "permissionDecision": "deny",
                        "permissionDecisionReason": deny_reason,
                    }
                }
            )
        )
        try:
            _load_log_fire()(
                data, "enforce-askuserquestion-default", "deny", deny_reason
            )
        except Exception:
            pass
        sys.exit(0)

    except Exception:
        # Defense-in-depth: any unexpected error exits 0 (fail-open).
        sys.exit(0)


if __name__ == "__main__":
    main()
