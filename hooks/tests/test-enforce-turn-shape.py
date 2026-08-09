# Run with: python3 hooks/tests/test-enforce-turn-shape.py
"""
Unit tests for hooks/enforce-turn-shape.py (DS-122).

Each case pipes a JSON payload into the hook via stdin and asserts:
  ADVISORY - exit 0, hookSpecificOutput.additionalContext starts with
             "TURN-SHAPE:" and contains the expected finding substring.
  QUIET    - exit 0, no stdout at all (silent allow).

The hook MUST NEVER emit a blocking decision under any input - there is no
{"decision": "block", ...} shape this hook can produce.

Test coverage (mirrors the 14-case spec in the DS-122 spawn brief):
  a. identity check fires on a missing identity line
  b. identity check passes on a well-formed identity line
  c. status-only flag fires (>2 body lines, no warrant)
  d. status-only flag does not fire when '## Operator decisions' is present
  e. completion warrant recognizes '[phase: complete]' / explicit terminal
     phrases, and does NOT recognize a bare done/shipped/merged
  f. forced-yield fires on a Waiting: line + extra prose, no other warrant
  g. forced-yield passes on the exact identity + Waiting: shape
  h. AE_TURN_SHAPE_GUARD_DISABLE=1 short-circuits to exit 0, no output
  i. config toggle absent/false/true - absent means ON
  j. output is ALWAYS exit 0 regardless of findings
  k. malformed/garbage stdin -> exit 0, no output
  l. a warranted completion/decision turn that ALSO carries a Waiting: line
     is NOT flagged (the shape check is gated off)
  m. a stoppage-only turn with one explanatory sentence beside the
     Waiting: line IS flagged
  n. log_fire() is called exactly once when a finding is emitted, and NOT
     called on a clean turn (patches _load_log_fire directly)
  r. the worked example embedded in the identity-line advisory matches
     _IDENTITY_LINE_RE itself (DS-132)
  s. DS-151 turn-charge model (rewritten from the deleted per-warrant
     exclusion model - see hooks/enforce-turn-shape.py's "Charge model"
     docstring section): flat BASE_BODY_BUDGET=10 at/over boundary per
     warrant shape (QUIET at budget, ADVISORY one line over); the
     decisions-block item-count exemption (s7); a sole-stoppage
     forced-yield turn is unaffected regardless of Waiting: line count
     (s10c, structurally free now, not via a skipped check); the answer
     warrant no longer buys ANY special budget, generous or fallback -
     amendment A1 closes an unbounded per-instance Waiting: free-pool
     escape (identity + 40 well-formed Waiting: lines + a decision warrant
     - see the "s2/s4/s6/s5c/s8 flip" cases below, all originally
     ADVISORY under the deleted per-warrant model, now QUIET or ADVISORY
     purely by flat line count); fenced-content exclusion is capped and
     scoped to the status region (s12/s12b/s13/s13b/s13c).
  v. DS-151 new regression fixtures (verified escapes under the OLD
     per-warrant-exclusion model, closed by the charge-model rewrite):
     v1/v2 CF-1 fence-multiplication; v3/v4 CF-2 unrecognized-decisions-
     content; v5/v5b CF-2 indented-item escape (contrasted against
     unbounded legitimate item count); v6 fenced-heading amendment A8
     (produces status-only, not a volume finding - zero warrants remain
     once the heading is unfenced-invisible); v7/v7b amendment A1's fat-
     vs-well-formed Waiting: line distinction; v8/v9 realistic-turn
     false-positive gates.
  t. DS-151 finding 4: operator-decisions per-item sprawl - item COUNT
     stays unbounded (t3, many short items) but a single item's LINE COUNT
     is bounded at MAX_LINES_PER_DECISION_ITEM, now folding in fenced
     content (amendment A2) (t2 regression: one item sprawling to 40
     lines; t4: per-item, not aggregate, measurement)
  u. DS-151 constant/boundary pins, now BEHAVIORAL (test-strategy item 3):
     u1/u2 (bare BODY_BUDGET_ANSWER constant pins) are DELETED with the
     constants they pinned; u3/u4 assert the fence-cap and per-item-cap
     BOUNDARIES through the hook's actual QUIET/ADVISORY behavior, not by
     importing and comparing an integer.
"""

from __future__ import annotations

import importlib.util
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import time

HOOK_PATH = os.path.join(os.path.dirname(__file__), "..", "enforce-turn-shape.py")

IDENTITY_OK = "unit-1 · fix-thing · abc1234 [phase: implement]"
IDENTITY_COMPLETE = "unit-1 · fix-thing · abc1234 [phase: complete]"

total = 0
failed = 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def run_hook(payload: str, env: dict | None = None) -> tuple[int, str, str]:
    merged_env = os.environ.copy()
    merged_env.pop("AE_TURN_SHAPE_GUARD_DISABLE", None)
    if env:
        merged_env.update(env)
    result = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=payload,
        capture_output=True,
        text=True,
        env=merged_env,
        timeout=10,
    )
    return result.returncode, result.stdout, result.stderr


def make_payload(message: str, cwd: str | None = None, extra: dict | None = None) -> str:
    obj = {"last_assistant_message": message}
    if cwd is not None:
        obj["cwd"] = cwd
    if extra:
        obj.update(extra)
    return json.dumps(obj)


def parse_output(stdout: str):
    if not stdout.strip():
        return {}
    try:
        return json.loads(stdout)
    except Exception:
        return {}


def is_quiet(returncode: int, stdout: str) -> bool:
    return returncode == 0 and not stdout.strip()


def is_advisory(returncode: int, stdout: str, contains: str | None = None) -> bool:
    if returncode != 0:
        return False
    obj = parse_output(stdout)
    hso = obj.get("hookSpecificOutput", {})
    ctx = hso.get("additionalContext", "")
    if hso.get("hookEventName") != "Stop":
        return False
    if not ctx.startswith("TURN-SHAPE:"):
        return False
    if contains is not None and contains not in ctx:
        return False
    return True


def check(label: str, condition: bool):
    global total, failed
    total += 1
    status = "PASS" if condition else "FAIL"
    if not condition:
        failed += 1
    print(f"  [{status}] {label}")


# ---------------------------------------------------------------------------
# a. identity check fires on a missing identity line
# ---------------------------------------------------------------------------

rc, out, err = run_hook(make_payload("Done."))
check("a. missing identity line -> ADVISORY (identity finding)", is_advisory(rc, out, "identity"))

# ---------------------------------------------------------------------------
# a2. REGRESSION: the advisory must carry a worked example, not just the
#     word "identity" - a middle dot and a bracketed [phase: ...] tag must
#     both be present in the additionalContext so the conductor can copy
#     the shape instead of guessing it.
# ---------------------------------------------------------------------------

rc, out, err = run_hook(make_payload("Done."))
_ctx = parse_output(out).get("hookSpecificOutput", {}).get("additionalContext", "")
check(
    "a2. missing identity line -> advisory includes a `·` and a `[phase:` example",
    "·" in _ctx and "[phase:" in _ctx,
)

# ---------------------------------------------------------------------------
# b. identity check passes on a well-formed one
# ---------------------------------------------------------------------------

rc, out, err = run_hook(make_payload(IDENTITY_COMPLETE))
check("b. well-formed identity + completion -> QUIET", is_quiet(rc, out))

# ---------------------------------------------------------------------------
# c. status-only flag fires
# ---------------------------------------------------------------------------

status_only_msg = (
    IDENTITY_OK + "\n"
    "Did a first thing.\n"
    "Did a second thing.\n"
    "Did a third thing.\n"
)
rc, out, err = run_hook(make_payload(status_only_msg))
check("c. >2 body lines, no warrant -> ADVISORY (status-only)", is_advisory(rc, out, "status-only"))

# ---------------------------------------------------------------------------
# d. passes on a message containing '## Operator decisions'
# ---------------------------------------------------------------------------

decision_msg = (
    IDENTITY_OK + "\n"
    "Did a first thing.\n"
    "Did a second thing.\n"
    "Did a third thing.\n"
    "\n"
    "## Operator decisions\n"
    "- Proceed with X (Recommended)\n"
)
rc, out, err = run_hook(make_payload(decision_msg))
check("d. '## Operator decisions' heading present -> QUIET", is_quiet(rc, out))

# ---------------------------------------------------------------------------
# e. completion warrant: '[phase: complete]' / explicit phrase pass;
#    bare done/shipped/merged does NOT count as completion
# ---------------------------------------------------------------------------

completion_explicit_msg = (
    IDENTITY_OK + "\n"
    "First line of prose.\n"
    "Second line of prose.\n"
    "Task is complete.\n"
)
rc, out, err = run_hook(make_payload(completion_explicit_msg))
check(
    "e1. explicit terminal phrase ('task is complete') -> QUIET (completion warrant recognized)",
    is_quiet(rc, out),
)

bare_done_msg = (
    IDENTITY_OK + "\n"
    "First line of prose.\n"
    "Second line of prose.\n"
    "Unit 2 merged.\n"
)
rc, out, err = run_hook(make_payload(bare_done_msg))
check(
    "e2. bare 'merged' does NOT satisfy completion warrant -> ADVISORY (status-only)",
    is_advisory(rc, out, "status-only"),
)

bare_shipped_msg = (
    IDENTITY_OK + "\n"
    "First line of prose.\n"
    "Second line of prose.\n"
    "PR shipped, pulling main.\n"
)
rc, out, err = run_hook(make_payload(bare_shipped_msg))
check(
    "e3. bare 'shipped' does NOT satisfy completion warrant -> ADVISORY (status-only)",
    is_advisory(rc, out, "status-only"),
)

# ---------------------------------------------------------------------------
# f. forced-yield fires on Waiting: line + extra prose, no other warrant
# ---------------------------------------------------------------------------

forced_yield_extra_msg = (
    IDENTITY_OK + "\n"
    "Some explanation here that is not itself a Waiting line.\n"
    "Waiting: operator approval to proceed.\n"
)
rc, out, err = run_hook(make_payload(forced_yield_extra_msg))
check(
    "f. Waiting: line + extra prose, no other warrant -> ADVISORY (forced-yield)",
    is_advisory(rc, out, "forced-yield"),
)

# ---------------------------------------------------------------------------
# g. forced-yield passes on the exact identity + Waiting: shape
# ---------------------------------------------------------------------------

forced_yield_clean_msg = IDENTITY_OK + "\nWaiting: operator approval to proceed.\n"
rc, out, err = run_hook(make_payload(forced_yield_clean_msg))
check("g. identity + Waiting: only -> QUIET", is_quiet(rc, out))

forced_yield_clean_multi_msg = (
    IDENTITY_OK + "\n"
    "Waiting: operator approval on item A.\n"
    "Waiting: operator approval on item B.\n"
)
rc, out, err = run_hook(make_payload(forced_yield_clean_multi_msg))
check("g2. identity + multiple Waiting: lines only -> QUIET", is_quiet(rc, out))

# ---------------------------------------------------------------------------
# h. AE_TURN_SHAPE_GUARD_DISABLE=1 short-circuits to exit 0, no output
# ---------------------------------------------------------------------------

rc, out, err = run_hook(make_payload("Done."), env={"AE_TURN_SHAPE_GUARD_DISABLE": "1"})
check("h. kill-switch set -> QUIET even on a flagged message", is_quiet(rc, out))

# ---------------------------------------------------------------------------
# i. config toggle absent/false/true - absent means ON
# ---------------------------------------------------------------------------
# NOTE: each sub-case gets its OWN fresh cwd. The loop guard (DS-122 fix)
# caps consecutive advisories at CONSECUTIVE_BLOCK_CAP=2 per cwd (see the
# counter-cap tests below), so four ADVISORY-expecting invocations sharing
# one cwd would trip the cap on i4. Isolating each sub-case preserves each
# assertion while keeping the loop-guard counter out of the config-toggle
# path - mirroring how test-enforce-no-abdication.py isolates each
# counter-sensitive case in its own subdirectory.

with tempfile.TemporaryDirectory() as tmp_dir:
    real_tmp = os.path.realpath(tmp_dir)

    def _fresh_cwd(name: str) -> str:
        d = os.path.join(real_tmp, name)
        os.makedirs(os.path.join(d, ".agentic"), exist_ok=True)
        return d

    # i1. config.json absent entirely -> guard stays ON.
    i1_cwd = _fresh_cwd("i1")
    rc, out, err = run_hook(make_payload("Done.", cwd=i1_cwd))
    check("i1. config.json absent -> guard ON (ADVISORY on flagged message)", is_advisory(rc, out, "identity"))

    # i2. config.json present, key explicitly false -> guard OFF.
    i2_cwd = _fresh_cwd("i2")
    with open(os.path.join(i2_cwd, ".agentic", "config.json"), "w") as f:
        json.dump({"turn_shape_guard_enabled": False}, f)
    rc, out, err = run_hook(make_payload("Done.", cwd=i2_cwd))
    check("i2. turn_shape_guard_enabled=false -> QUIET (guard disabled)", is_quiet(rc, out))

    # i3. config.json present, key explicitly true -> guard ON.
    i3_cwd = _fresh_cwd("i3")
    with open(os.path.join(i3_cwd, ".agentic", "config.json"), "w") as f:
        json.dump({"turn_shape_guard_enabled": True}, f)
    rc, out, err = run_hook(make_payload("Done.", cwd=i3_cwd))
    check("i3. turn_shape_guard_enabled=true -> ADVISORY (guard on)", is_advisory(rc, out, "identity"))

    # i4. config.json present but key absent -> guard stays ON.
    i4_cwd = _fresh_cwd("i4")
    with open(os.path.join(i4_cwd, ".agentic", "config.json"), "w") as f:
        json.dump({"some_other_key": True}, f)
    rc, out, err = run_hook(make_payload("Done.", cwd=i4_cwd))
    check("i4. config.json present, key absent -> guard ON", is_advisory(rc, out, "identity"))

# ---------------------------------------------------------------------------
# j. output is ALWAYS exit 0 regardless of findings
# ---------------------------------------------------------------------------

rc_flagged, _, _ = run_hook(make_payload("Done."))
rc_clean, _, _ = run_hook(make_payload(IDENTITY_COMPLETE))
check("j1. exit code is 0 on a flagged turn", rc_flagged == 0)
check("j2. exit code is 0 on a clean turn", rc_clean == 0)

# ---------------------------------------------------------------------------
# k. malformed/garbage stdin -> exit 0, no output
# ---------------------------------------------------------------------------

rc, out, err = run_hook("{not valid json::")
check("k1. garbage stdin -> QUIET", is_quiet(rc, out))

rc, out, err = run_hook("")
check("k2. empty stdin -> QUIET", is_quiet(rc, out))

rc, out, err = run_hook("[1, 2, 3]")
check("k3. valid JSON but not an object -> QUIET", is_quiet(rc, out))

# ---------------------------------------------------------------------------
# l. a warranted completion/decision turn that ALSO carries a Waiting: line
#    is NOT flagged (shape check gated off)
# ---------------------------------------------------------------------------

# l1's body MUST contain a non-Waiting: line (here: "Shipped unit 3, task
# is complete.") so the forced-yield gate ("stoppage is the SOLE
# warrant") is genuinely exercised - if the completion warrant is not
# recognized, this line would trip "forced-yield: extra content" the same
# way case (f) does. A body consisting of ONLY a Waiting: line (the prior
# version of this fixture) is vacuous: _forced_yield_flag's per-line loop
# returns None regardless of the gate, since every body line already
# matches _WAITING_LINE_RE - deleting the `warrants["completion"] or`
# term from the gate condition would leave this fixture green.
completion_plus_waiting_msg = (
    IDENTITY_COMPLETE + "\n"
    "Shipped unit 3, task is complete.\n"
    "Waiting: nothing further.\n"
)
rc, out, err = run_hook(make_payload(completion_plus_waiting_msg))
check("l1. completion warrant + Waiting: line -> QUIET (shape check skipped)", is_quiet(rc, out))

decision_plus_waiting_msg = (
    IDENTITY_OK + "\n"
    "\n"
    "## Operator decisions\n"
    "- Proceed with X (Recommended)\n"
    "\n"
    "Waiting: operator sign-off on the recommendation above.\n"
)
rc, out, err = run_hook(make_payload(decision_plus_waiting_msg))
check("l2. decision warrant + Waiting: line -> QUIET (shape check skipped)", is_quiet(rc, out))

# ---------------------------------------------------------------------------
# m. a stoppage-only turn with one explanatory sentence beside the
#    Waiting: line IS flagged
# ---------------------------------------------------------------------------

stoppage_with_explanation_msg = (
    IDENTITY_OK + "\n"
    "This is blocked on a credential I do not have.\n"
    "Waiting: the API key for the staging environment.\n"
)
rc, out, err = run_hook(make_payload(stoppage_with_explanation_msg))
check(
    "m. stoppage-only + one explanatory sentence -> ADVISORY (forced-yield)",
    is_advisory(rc, out, "forced-yield"),
)

# ---------------------------------------------------------------------------
# p. REGRESSION (Skeptic Major, round 2): apostrophes/contractions must NOT
#    satisfy the 'answer' warrant. Pins the fix that dropped the
#    single-quote alternative from _QUOTED_FRAGMENT_RE - without the fix,
#    this message's contractions/possessives ("they're", "that's",
#    "engineer's", "isn't", "don't", "can't") would each open/close a
#    bogus quoted-fragment match, setting the answer warrant and silently
#    suppressing the status-only flag this case expects.
# ---------------------------------------------------------------------------

apostrophe_msg = (
    IDENTITY_OK + "\n"
    "Ran the tests, they're green, that's all.\n"
    "The engineer's branch isn't stale.\n"
    "I don't think we can't merge yet.\n"
)
rc, out, err = run_hook(make_payload(apostrophe_msg))
check(
    "p. apostrophes do NOT satisfy the answer warrant -> ADVISORY (status-only)",
    is_advisory(rc, out, "status-only"),
)

# ---------------------------------------------------------------------------
# q. REGRESSION (Skeptic Minor, round 2): pin the catastrophic-backtracking
#    fix on _IDENTITY_LINE_RE. A first line with ~3200 middle-dot/period
#    characters and no '[phase:' tag must classify in well under a second -
#    a generous 1.0s bound (measured value is now microseconds) that is
#    loose enough to avoid flaking on a slow CI runner while still catching
#    a regression to the unbounded '.*' form (measured 13.8s pre-fix).
# ---------------------------------------------------------------------------

_pathological_msg = "x" + ("·" * 3200) + "\nno phase tag here at all\n"
_start = time.monotonic()
rc, out, err = run_hook(make_payload(_pathological_msg))
_elapsed = time.monotonic() - _start
check(
    f"q. pathological identity-line input completes in <1.0s (took {_elapsed:.4f}s)",
    _elapsed < 1.0,
)

# ---------------------------------------------------------------------------
# n. log_fire() called exactly once on a finding, not called on a clean turn
#    (patches _load_log_fire directly via module import, per spec)
# ---------------------------------------------------------------------------

_spec = importlib.util.spec_from_file_location(
    "enforce_turn_shape", os.path.join(os.path.dirname(__file__), "..", "enforce-turn-shape.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


def _run_main_with_stdin(payload: str, calls: list):
    """Call the imported module's main() with stdin/stdout redirected and
    _load_log_fire patched to a recorder. Returns captured stdout."""
    _mod._load_log_fire = lambda: (
        lambda data, hook_name, decision, reason: calls.append((hook_name, decision, reason))
    )
    old_stdin, old_stdout = sys.stdin, sys.stdout
    sys.stdin = io.StringIO(payload)
    sys.stdout = io.StringIO()
    try:
        try:
            _mod.main()
        except SystemExit:
            pass
        return sys.stdout.getvalue()
    finally:
        sys.stdin, sys.stdout = old_stdin, old_stdout


_calls_flagged: list = []
_out_flagged = _run_main_with_stdin(make_payload("Done."), _calls_flagged)
check(
    "n1. log_fire called exactly once with hook_name='enforce-turn-shape', "
    "decision='allow_advisory' on a finding",
    len(_calls_flagged) == 1
    and _calls_flagged[0][0] == "enforce-turn-shape"
    and _calls_flagged[0][1] == "allow_advisory",
)

_calls_clean: list = []
_out_clean = _run_main_with_stdin(make_payload(IDENTITY_COMPLETE), _calls_clean)
check("n2. log_fire NOT called on a clean turn", len(_calls_clean) == 0)


# ---------------------------------------------------------------------------
# r. REGRESSION: the worked example embedded in the identity-line advisory
#    finding must itself satisfy _IDENTITY_LINE_RE - an example that fails
#    the regex it is teaching is worse than no example at all. Extracted
#    from the live advisory output (not re-typed here) so this pins against
#    source drift instead of just re-asserting a copy of the literal.
# ---------------------------------------------------------------------------

_r_match = re.search(r"`([^`]*)`", _ctx)
check("r. advisory contains a backtick-quoted example", _r_match is not None)
_r_example = _r_match.group(1) if _r_match else ""
check(
    "r. embedded advisory example matches _IDENTITY_LINE_RE",
    bool(_mod._IDENTITY_LINE_RE.match(_r_example)),
)

# ---------------------------------------------------------------------------
# o. transcript_path fallback (_last_assistant_text_from_transcript), used
#    when last_assistant_message is absent/empty. Previously zero coverage
#    (Skeptic Minor). Covers a single-block transcript entry AND a
#    two-block entry, pinning the "\n".join(parts) fix - a two-block entry
#    joined with " " would collapse the body onto one line and silently
#    suppress the forced-yield finding this case expects.
# ---------------------------------------------------------------------------


def _write_transcript(tmp_dir: str, lines: list) -> str:
    path = os.path.join(tmp_dir, "transcript.jsonl")
    with open(path, "w", encoding="utf-8") as f:
        for line in lines:
            f.write(json.dumps(line) + "\n")
    return path


with tempfile.TemporaryDirectory() as tmp_dir:
    # o1. single-block assistant content (string form) via transcript fallback.
    transcript_path = _write_transcript(
        tmp_dir,
        [
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": IDENTITY_OK
                + "\nSome explanation here that is not itself a Waiting line.\n"
                + "Waiting: operator approval to proceed.\n",
            },
        ],
    )
    rc, out, err = run_hook(
        json.dumps({"last_assistant_message": "", "transcript_path": transcript_path})
    )
    check(
        "o1. transcript fallback, single string-content block -> ADVISORY (forced-yield)",
        is_advisory(rc, out, "forced-yield"),
    )

    # o2. two-block assistant content (list-of-text-blocks form) via
    # transcript fallback - the case the "\n".join fix targets. Split
    # across two text blocks so a " ".join would collapse them onto one
    # line and silently suppress the forced-yield finding.
    transcript_path = _write_transcript(
        tmp_dir,
        [
            {"role": "user", "content": "go"},
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "text",
                        "text": IDENTITY_OK
                        + "\nSome explanation here that is not itself a Waiting line.",
                    },
                    {"type": "text", "text": "Waiting: operator approval to proceed."},
                ],
            },
        ],
    )
    rc, out, err = run_hook(
        json.dumps({"last_assistant_message": "", "transcript_path": transcript_path})
    )
    check(
        "o2. transcript fallback, two-block content joined with newline -> ADVISORY (forced-yield)",
        is_advisory(rc, out, "forced-yield"),
    )


# ---------------------------------------------------------------------------
# s. DS-151 turn-charge model (rewritten from the deleted per-warrant
#    exclusion model). Fixed contract values mirror the constants in
#    enforce-turn-shape.py; the hook runs as a subprocess so we cannot
#    import them directly at collection time (they ARE imported later, in
#    the "u." section, for boundary-sizing only - never for a bare
#    integer-equality assertion; see test-strategy item 3).
# ---------------------------------------------------------------------------

BASE_BODY_BUDGET = 10
FENCE_FREE_LINES = 20
ITEM_FREE_LINES = 3
MAX_LINES_PER_DECISION_ITEM = 3


def _nlines(n: int, prefix: str = "Line") -> str:
    return "\n".join(f"{prefix} {i}." for i in range(1, n + 1)) + "\n"


# s1. decision warrant, body AT the flat budget (10 lines) -> QUIET.
# (A9: relabeled - the old per-warrant DECISION budget of 3 no longer
# exists; this now pins the flat BASE_BODY_BUDGET boundary.)
s1_msg = IDENTITY_OK + "\n" + _nlines(BASE_BODY_BUDGET) + "\n## Operator decisions\n- Proceed with X (Recommended)\n"
rc, out, err = run_hook(make_payload(s1_msg))
check("s1. decision warrant, body at flat budget (10 lines) -> QUIET", is_quiet(rc, out))

# s2. decision warrant, body ONE line OVER the flat budget (11 lines) ->
# ADVISORY. (A9/flip: resized from the old 4-line boundary - see plan test
# strategy table - to re-pin the new 10-line boundary.)
s2_msg = IDENTITY_OK + "\n" + _nlines(BASE_BODY_BUDGET + 1) + "\n## Operator decisions\n- Proceed with X (Recommended)\n"
rc, out, err = run_hook(make_payload(s2_msg))
check(
    "s2. decision warrant, body 1 line over flat budget -> ADVISORY (turn volume exceeded)",
    is_advisory(rc, out, "turn volume exceeded"),
)

# s3. completion warrant, body AT the flat budget (10 lines) -> QUIET.
# (A9: relabeled from the old COMPLETION budget of 6.)
s3_msg = IDENTITY_COMPLETE + "\n" + _nlines(BASE_BODY_BUDGET, prefix="Shipped item")
rc, out, err = run_hook(make_payload(s3_msg))
check("s3. completion warrant, body at flat budget (10 lines) -> QUIET", is_quiet(rc, out))

# s4. FLIP (plan test-strategy table): under the deleted per-warrant model
# this 7-line completion turn was ADVISORY (over the old COMPLETION budget
# of 6) - this WAS the round-2 false positive. Under the flat 10-line
# budget it is QUIET; the assertion is inverted deliberately, not deleted,
# so a regression back to a tight per-warrant budget is caught.
s4_msg = IDENTITY_COMPLETE + "\n" + _nlines(7, prefix="Shipped item")
rc, out, err = run_hook(make_payload(s4_msg))
check(
    "s4. FLIP: completion warrant, 7-line body (was ADVISORY under the deleted "
    "per-warrant model - this WAS the round-2 FP) -> now QUIET under the flat budget",
    is_quiet(rc, out),
)

# s4b. Same shape resized to 11 lines, over the flat budget -> ADVISORY.
# Keeps a genuine over-budget pin for the completion-warrant shape now that
# s4 itself is QUIET.
s4b_msg = IDENTITY_COMPLETE + "\n" + _nlines(BASE_BODY_BUDGET + 1, prefix="Shipped item")
rc, out, err = run_hook(make_payload(s4b_msg))
check(
    "s4b. completion warrant, 11-line body (over flat budget) -> ADVISORY (turn volume exceeded)",
    is_advisory(rc, out, "turn volume exceeded"),
)

# s5. answer warrant, body AT the flat budget (10 lines total, including
# the quoted line that supplies the warrant) -> QUIET. (A9: resized from
# the old, now-deleted, WEAK_FALLBACK boundary of 6 to the new flat
# boundary of 10 - amendment A1/finding-3a's whole "fallback budget"
# concept no longer exists; the answer warrant gets no special budget at
# all any more, generous or reduced.)
s5_msg = (
    IDENTITY_OK
    + "\n"
    + '"Here is the direct answer to your question."\n'
    + _nlines(BASE_BODY_BUDGET - 1, prefix="Detail")
)
rc, out, err = run_hook(make_payload(s5_msg))
check("s5. answer warrant, body at flat budget (10 lines total) -> QUIET", is_quiet(rc, out))

# s6. FLIP (plan test-strategy table): under the deleted per-warrant model
# this 7-line answer turn was ADVISORY (over the old WEAK_FALLBACK budget
# of 6). Under the flat 10-line budget it is QUIET.
s6_msg = (
    IDENTITY_OK
    + "\n"
    + '"Here is the direct answer to your question."\n'
    + _nlines(6, prefix="Detail")
)
rc, out, err = run_hook(make_payload(s6_msg))
check(
    "s6. FLIP: answer warrant, 7-line body (was ADVISORY under the deleted "
    "per-warrant fallback budget of 6) -> now QUIET under the flat budget",
    is_quiet(rc, out),
)

# s6c. Same shape resized to 11 lines total, over the flat budget ->
# ADVISORY, and the message cites "budget is 10" (the flat budget), not
# the deleted per-warrant fallback value of 6 (A9: s6b's old assertion
# "budget is 6" becomes "budget is 10").
s6c_msg = (
    IDENTITY_OK
    + "\n"
    + '"Here is the direct answer to your question."\n'
    + _nlines(10, prefix="Detail")
)
rc, out, err = run_hook(make_payload(s6c_msg))
check(
    "s6c. answer warrant, 11-line body (over flat budget) -> ADVISORY (turn volume exceeded)",
    is_advisory(rc, out, "turn volume exceeded"),
)
check(
    "s6c-b. advisory cites the flat budget (10), not a deleted per-warrant fallback (6)",
    "budget is 10" in parse_output(out).get("hookSpecificOutput", {}).get("additionalContext", ""),
)

# s5c. FLIP + REGRESSION repurpose (DS-151 amendment): under the deleted
# per-warrant model, an incidental quoted fragment bought the whole turn
# the most generous budget via max() across warrants - closing that bypass
# was finding 3's whole point. Under the flat charge model, warrant
# COMPOSITION no longer affects the budget AT ALL (there is only one
# budget), so this fixture is repurposed per the plan's instruction:
# assert that the SAME body length yields an IDENTICAL verdict whether or
# not the incidental quote is present (both QUIET), proving the quote
# genuinely no longer matters to the volume determination - not even in
# the direction of buying a bigger budget, nor in the direction of costing
# one. A completion warrant is present in BOTH variants (not just the
# quoted one) so removing the quote does not also remove every warrant and
# trip the unrelated status-only check.
s5c_with_quote_msg = (
    IDENTITY_COMPLETE
    + "\n"
    + 'Merged "fix: resolve turn-shape gate regression" into main.\n'
    + _nlines(7, prefix="Also did thing")
)
rc, out, err = run_hook(make_payload(s5c_with_quote_msg))
check("s5c. incidental quote present, 9-line body, completion warrant -> QUIET", is_quiet(rc, out))

s5c_no_quote_msg = (
    IDENTITY_COMPLETE
    + "\n"
    + "Merged the fix for the turn-shape gate regression into main.\n"
    + _nlines(7, prefix="Also did thing")
)
rc, out, err = run_hook(make_payload(s5c_no_quote_msg))
check(
    "s5c-b. same 9-line body WITHOUT the quote, same completion warrant -> "
    "IDENTICAL verdict (QUIET) - the quote's presence no longer changes the budget",
    is_quiet(rc, out),
)

# s5c-over. 12-line variant (with the quote) to keep a genuine ADVISORY pin
# for this shape now that the base fixture is QUIET both ways.
s5c_over_msg = (
    IDENTITY_COMPLETE
    + "\n"
    + 'Merged "fix: resolve turn-shape gate regression" into main.\n'
    + _nlines(10, prefix="Also did thing")
)
rc, out, err = run_hook(make_payload(s5c_over_msg))
check(
    "s5c-over. 12-line variant of the same shape -> ADVISORY (turn volume exceeded)",
    is_advisory(rc, out, "turn volume exceeded"),
)

# s7. decisions-block exemption: a large number of decision items (10, well
# beyond the flat budget's line count if they were charged individually)
# does NOT count against the volume check by ITEM COUNT - only actual line
# count (short items, none over ITEM_FREE_LINES) is measured. Also pins
# that content/sections/02-delegation.md's ban on a decision-item cap is
# respected (no item-count limit is applied anywhere in this hook).
s7_decision_items = "\n".join(f"{i}. Action {i} - reason. Reply STOP to skip." for i in range(1, 11))
s7_msg = IDENTITY_OK + "\n" + _nlines(BASE_BODY_BUDGET) + "\n## Operator decisions\n" + s7_decision_items + "\n"
rc, out, err = run_hook(make_payload(s7_msg))
check(
    "s7. decisions-block exemption: 10 decision items, body at flat budget -> QUIET",
    is_quiet(rc, out),
)

# s8. FLIP + consolidation: combo warrant (stoppage + completion). Under
# the deleted per-warrant model this used max(STOPPAGE=3, COMPLETION=6)=6
# as its budget; that whole "most generous of present warrants' budgets"
# concept is deleted (warrant-keyed budgets are unsound - see the module
# docstring). Under the flat model, since completion is ALSO present,
# stoppage is not the SOLE warrant, so the Waiting: line charges 1 like
# any other line (amendment A1) - the combo is now judged purely by flat
# line count, same as s9's boundary case, at 10 lines (9 prose + 1
# Waiting:) -> QUIET. s8_over below (11 lines) pins the genuine over-budget
# case.
s8_msg = IDENTITY_COMPLETE + "\n" + _nlines(9, prefix="Shipped item") + "Waiting: nothing further.\n"
rc, out, err = run_hook(make_payload(s8_msg))
check(
    "s8. stoppage+completion combo, 10 lines (9 prose + 1 Waiting:, not sole "
    "stoppage so it charges) -> QUIET at the flat budget",
    is_quiet(rc, out),
)
check(
    "s8b. combo case is NOT flagged as forced-yield (gated off by completion warrant)",
    "forced-yield" not in parse_output(out).get("hookSpecificOutput", {}).get("additionalContext", ""),
)

s8_over_msg = IDENTITY_COMPLETE + "\n" + _nlines(10, prefix="Shipped item") + "Waiting: nothing further.\n"
rc, out, err = run_hook(make_payload(s8_over_msg))
check(
    "s8-over. same combo shape, 11 lines (over flat budget) -> ADVISORY (turn volume exceeded)",
    is_advisory(rc, out, "turn volume exceeded"),
)

# s9. same combo, AT the flat budget (9 prose + 1 Waiting: = 10 lines) ->
# QUIET. (A9: relabeled from "at the completion budget (6 lines)" - the
# per-warrant COMPLETION budget no longer exists; this pins the flat
# 10-line boundary for the combo shape, identical to s8 above by
# construction - kept as a separate fixture per the plan's fixture table.)
s9_msg = IDENTITY_COMPLETE + "\n" + _nlines(9, prefix="Shipped item") + "Waiting: nothing further.\n"
rc, out, err = run_hook(make_payload(s9_msg))
check("s9. stoppage+completion combo, at the flat budget (10 lines) -> QUIET", is_quiet(rc, out))

# s10. forced-yield turn (stoppage as SOLE warrant) is unaffected by the
# volume check - the identity + Waiting:-only shape (2 lines, well under
# the flat budget) stays QUIET, same as case g2.
s10_msg = IDENTITY_OK + "\nWaiting: item A.\nWaiting: item B.\n"
rc, out, err = run_hook(make_payload(s10_msg))
check("s10. forced-yield turn (2 Waiting: lines, sole warrant) -> QUIET, volume check inert", is_quiet(rc, out))

# s10c. REGRESSION (DS-151 Skeptic Critical finding 1, exact adversarial
# input, still pinned under the charge model): a 5-agent fan-out
# forced-yield turn (5 Waiting: lines, well over the OLD per-warrant
# STOPPAGE budget of 3, and over the current flat BASE_BODY_BUDGET too if
# each line charged) must stay QUIET -
# conductor-turn-format.md:31 states the Waiting: count is "unbounded, not
# re-capped at 1-3". Under the charge model this is now satisfied
# STRUCTURALLY (amendment A1): stoppage is the sole warrant here, so every
# well-formed Waiting: line charges 0 regardless of count, rather than via
# a whole-check skip.
s10c_msg = IDENTITY_OK + "\n" + "\n".join(f"Waiting: agent-{i} - unit {i} review." for i in range(1, 6)) + "\n"
rc, out, err = run_hook(make_payload(s10c_msg))
check(
    "s10c. forced-yield turn (5 Waiting: lines, sole warrant) -> QUIET, "
    "structurally free (amendment A1), not via a skipped check",
    is_quiet(rc, out),
)

# s10d. NEW: the A1 escape this amendment specifically closes - the SAME
# 5-Waiting:-line shape, but with a decision warrant ALSO present, so
# stoppage is no longer sole. Each well-formed Waiting: line now charges 1
# like ordinary prose (A1) - 5 lines is still well under the flat budget,
# so this stays QUIET too, but for a DIFFERENT reason (flat line count,
# not the sole-stoppage free pool). See v1's sibling fixture (40 lines)
# below for the case where this crosses into ADVISORY.
s10d_msg = (
    IDENTITY_OK
    + "\n"
    + "\n".join(f"Waiting: agent-{i} - unit {i} review." for i in range(1, 6))
    + "\n\n## Operator decisions\n- Proceed with X (Recommended)\n"
)
rc, out, err = run_hook(make_payload(s10d_msg))
check(
    "s10d. 5 Waiting: lines + decision warrant (stoppage no longer sole) -> "
    "still QUIET at 5 lines, but charged at full weight, not via the free pool",
    is_quiet(rc, out),
)

# s11. fenced code block content is excluded from the volume count: 10
# lines of "code" inside a fence plus 2 lines of real prose (well under the
# flat budget) -> QUIET, even though the raw line count (12) would exceed
# a tight per-warrant budget under the deleted model.
s11_code_lines = "\n".join(f"line_{i} = {i}" for i in range(1, 11))
s11_msg = (
    IDENTITY_OK
    + "\nHere is the diff.\n```python\n"
    + s11_code_lines
    + "\n```\nApplied cleanly.\n\n## Operator decisions\n- Proceed with X (Recommended)\n"
)
rc, out, err = run_hook(make_payload(s11_msg))
check(
    "s11. fenced code block excluded from volume count (2 real body lines) -> QUIET",
    is_quiet(rc, out),
)

# s12. REGRESSION (DS-151 Skeptic Major finding 2a, exact adversarial
# input, still pinned under the charge model): 30 lines of ORDINARY PROSE
# wrapped in a single closed fence, plus 2 real body lines - under the old
# unconditional exclusion this counted as 0 and passed silently (QUIET);
# after the fix, the 10 lines beyond FENCE_FREE_LINES=20 count at full
# weight, pushing the charge to 2 + 10 = 12, which exceeds the flat
# BASE_BODY_BUDGET=10 -> ADVISORY.
s12_fence_lines = "\n".join(f"Prose line {i}, not code at all." for i in range(1, 31))
s12_msg = (
    IDENTITY_COMPLETE
    + "\nHere is the summary.\n```\n"
    + s12_fence_lines
    + "\n```\nDone reporting.\n"
)
rc, out, err = run_hook(make_payload(s12_msg))
check(
    "s12. 30 prose lines in a closed fence (over FENCE_FREE_LINES) -> ADVISORY (turn volume exceeded)",
    is_advisory(rc, out, "turn volume exceeded"),
)

# s12b. Fence content AT the cap (exactly FENCE_FREE_LINES lines) stays
# fully excluded -> QUIET, confirming the cap boundary itself (not just
# "over the cap").
s12b_fence_lines = "\n".join(f"Prose line {i}." for i in range(1, FENCE_FREE_LINES + 1))
s12b_msg = (
    IDENTITY_COMPLETE
    + "\nHere is the summary.\n```\n"
    + s12b_fence_lines
    + "\n```\nDone reporting.\n"
)
rc, out, err = run_hook(make_payload(s12b_msg))
check(
    "s12b. fence content exactly AT FENCE_FREE_LINES -> QUIET (fully excluded)",
    is_quiet(rc, out),
)

# s13. REGRESSION (DS-151 Skeptic Major finding 2b, exact adversarial
# input, still pinned under the charge model): an UNCLOSED fence (opened,
# never closed) at true EOF. Under the old bug, the unbalanced ``` latched
# in_code=True to EOF and silently zeroed every line after it. Under the
# charge model, an unmatched trailing opener is simply NOT fenced (fail
# closed, _segment docstring) - no special case needed, and no
# exclusion cap applies. Resized to 15 buffered lines (A9: "resize to 15
# buffered lines (charge 17)") and PAIRED with a validly-closed fence of
# the identical 15 lines (s13-closed below) so the fixture proves the
# unclosed path gets no allowance BY CONTRAST with the closed path, not by
# a bare number alone.
s13_fence_body = "\n".join(f"line_{i} = {i}" for i in range(1, 16))
s13_msg = IDENTITY_COMPLETE + "\nHere is the diff.\nMore prose here.\n```python\n" + s13_fence_body + "\n"
rc, out, err = run_hook(make_payload(s13_msg))
check(
    "s13. unclosed fence (15 lines) at true EOF -> every buffered line counts "
    "at full weight -> ADVISORY (turn volume exceeded)",
    is_advisory(rc, out, "turn volume exceeded"),
)

s13_closed_msg = (
    IDENTITY_COMPLETE
    + "\nHere is the diff.\nMore prose here.\n```python\n"
    + s13_fence_body
    + "\n```\nDone reporting.\n"
)
rc, out, err = run_hook(make_payload(s13_closed_msg))
check(
    "s13-closed. IDENTICAL 15-line fence content, validly CLOSED -> QUIET "
    "(the contrast: unclosed gets no allowance, closed does)",
    is_quiet(rc, out),
)

# s13b. Boundary pair for the unclosed-fence path: buffered count lands
# exactly AT the flat budget (4 prose + 1 opener + 5 buffered = 10) ->
# QUIET; one buffered line more (6) pushes to 11 -> ADVISORY. (A9:
# relabeled and resized from the old "exactly at the completion budget (6
# lines)" boundary, which no longer exists.)
_s13b_prose = "\n".join(f"Prose line {i}." for i in range(1, 5))
_s13b_fence = "\n".join(f"fence line {i}" for i in range(1, 6))
s13b_msg = IDENTITY_COMPLETE + "\n" + _s13b_prose + "\n```\n" + _s13b_fence + "\n"
rc, out, err = run_hook(make_payload(s13b_msg))
check(
    "s13b. unclosed fence, buffered count exactly at the flat budget (10) -> QUIET",
    is_quiet(rc, out),
)

_s13c_fence = "\n".join(f"fence line {i}" for i in range(1, 7))
s13c_msg = IDENTITY_COMPLETE + "\n" + _s13b_prose + "\n```\n" + _s13c_fence + "\n"
rc, out, err = run_hook(make_payload(s13c_msg))
check(
    "s13c. unclosed fence, buffered count ONE over the flat budget (11) -> ADVISORY",
    is_advisory(rc, out, "turn volume exceeded"),
)


# ---------------------------------------------------------------------------
# v. DS-151 new regression fixtures (verified escapes under the OLD,
#    deleted per-warrant exclusion model). Test-strategy item 2: v1-v9 are
#    all confirmed to produce a DIFFERENT verdict against the pre-DS-151
#    hook (commit 40ba9ce4) than they assert here - see the fix summary
#    for the recorded old-code failure list. v5b/v7b/v8/v9 are QUIET
#    contrast/false-positive-gate fixtures, not escape fixtures, and are
#    NOT required to differ from old-code behavior (old code was already
#    QUIET on them too, correctly).
# ---------------------------------------------------------------------------


def _fence(n: int) -> str:
    return "```\n" + "\n".join(f"fence content line {i}" for i in range(1, n + 1)) + "\n```"


# v1. CF-1 gate: four 20-line CLOSED fences (aggregate 88 fenced nonblank
# lines) -> ADVISORY, charge 69. Must be >=2 fences - a 1-fence fixture
# passes under the old buggy per-fence-cap code too (s12b already pins
# that boundary).
v1_msg = IDENTITY_COMPLETE + "\n" + "\n".join(_fence(20) for _ in range(4)) + "\nTask is complete.\n"
rc, out, err = run_hook(make_payload(v1_msg))
check(
    "v1. CF-1 gate: four 20-line closed fences -> ADVISORY, charge 69",
    is_advisory(rc, out, "charge is 69"),
)

# v2. Minimal multiplication case: two 20-line closed fences -> ADVISORY,
# charge 25.
v2_msg = IDENTITY_COMPLETE + "\n" + "\n".join(_fence(20) for _ in range(2)) + "\nTask is complete.\n"
rc, out, err = run_hook(make_payload(v2_msg))
check(
    "v2. two 20-line closed fences (minimal multiplication case) -> ADVISORY, charge 25",
    is_advisory(rc, out, "charge is 25"),
)

# v3. CF-2 escape: 40 preamble lines under the heading, no item marker at
# all -> ADVISORY. Under the old "stop counting at the heading" design
# this region had NO accounting at all.
v3_msg = IDENTITY_OK + "\n\n## Operator decisions\n" + "\n".join(f"Preamble narrative line {i}." for i in range(1, 41)) + "\n"
rc, out, err = run_hook(make_payload(v3_msg))
check(
    "v3. 40 preamble lines under the heading, no item marker -> ADVISORY (turn volume exceeded)",
    is_advisory(rc, out, "turn volume exceeded"),
)

# v4. CF-2 escape, distinct shape from v3: a decisions block with no
# markers at all (short unstructured narrative, no bullets/numbers)
# -> ADVISORY once it exceeds the flat budget.
v4_msg = (
    IDENTITY_OK
    + "\n\n## Operator decisions\n"
    + "\n".join(f"Unstructured narrative line {i} with no bullet or number." for i in range(1, 13))
    + "\n"
)
rc, out, err = run_hook(make_payload(v4_msg))
check(
    "v4. decisions block with no markers at all -> ADVISORY (turn volume exceeded)",
    is_advisory(rc, out, "turn volume exceeded"),
)

# v5. CF-2 indented-item escape: a 40-line item indented at column 2 ->
# ADVISORY. The OLD _DECISION_ITEM_START_RE was column-0 anchored, so an
# indented item was never recognized as an item start at all - the new
# regex (`^ {0,3}(?:\d+[.)]|[-*+])\s+\S`) recognizes it.
v5_msg = (
    IDENTITY_OK
    + "\n\n## Operator decisions\n  - Proceed with X (Recommended)\n"
    + "\n".join(f"    extra narrative line {i}" for i in range(1, 40))
    + "\n"
)
rc, out, err = run_hook(make_payload(v5_msg))
check(
    "v5. 40-line item indented at column 2 -> ADVISORY (turn volume exceeded and/or item sprawl)",
    is_advisory(rc, out),
)

# v5b. CONTRAST (not an escape fixture): 40 SEPARATE one-line indented
# items -> QUIET. Proves the fix distinguishes "one item sprawling to 40
# lines" (v5, flagged) from "40 compliant items" (fine, item count stays
# unbounded) - now that indentation is correctly recognized either way.
v5b_msg = (
    IDENTITY_OK
    + "\n\n## Operator decisions\n"
    + "\n".join(f"  - Action {i} (Recommended) - reason." for i in range(1, 41))
    + "\n"
)
rc, out, err = run_hook(make_payload(v5b_msg))
check("v5b. 40 separate one-line indented items -> QUIET (item count unbounded)", is_quiet(rc, out))

# v6. Amendment A8: a fenced '## Operator decisions' heading + 40 prose
# lines produces ZERO warrants under step-7's narrowed detection domain
# (the heading is invisible while fenced, and nothing else in the message
# supplies a warrant) - so _volume_flag's zero-warrant early return fires,
# and the advisory comes from _status_only_flag instead. Re-specified per
# A8 to assert the finding it ACTUALLY produces.
v6_prose = "\n".join(f"Prose line {i} inside the fence." for i in range(1, 41))
v6_msg = IDENTITY_OK + "\n```\n## Operator decisions\n" + v6_prose + "\n```\n"
rc, out, err = run_hook(make_payload(v6_msg))
check(
    "v6 (A8 re-spec). fenced heading + 40 prose, zero warrants -> ADVISORY "
    "(status-only), NOT a volume finding",
    is_advisory(rc, out, "status-only"),
)
check(
    "v6b. fenced-heading case does NOT produce a volume finding",
    "turn volume exceeded" not in parse_output(out).get("hookSpecificOutput", {}).get("additionalContext", ""),
)

# v7. Amendment A1's fat-vs-well-formed distinction: 30 "Waiting:"-shaped
# lines that EXCEED WAITING_LINE_MAX_CHARS (fat) -> ADVISORY. A fat
# Waiting: line is never well-formed regardless of stoppage_sole, so it
# charges 1 like ordinary prose.
v7_msg = IDENTITY_OK + "\n" + "\n".join("Waiting: " + ("x" * 150) + f" item {i}" for i in range(1, 31)) + "\n"
rc, out, err = run_hook(make_payload(v7_msg))
check(
    "v7. 30 fat (>WAITING_LINE_MAX_CHARS) Waiting: lines -> ADVISORY (turn volume exceeded)",
    is_advisory(rc, out, "turn volume exceeded"),
)

# v7b. CONTRAST (not an escape fixture): 50 well-formed Waiting: lines,
# sole warrant -> QUIET. Confirms the free pool is genuinely unbounded by
# COUNT for well-formed lines, only bounded by CHARACTER LENGTH per line.
v7b_msg = IDENTITY_OK + "\n" + "\n".join(f"Waiting: item {i}." for i in range(1, 51)) + "\n"
rc, out, err = run_hook(make_payload(v7b_msg))
check("v7b. 50 well-formed Waiting: lines (sole warrant) -> QUIET", is_quiet(rc, out))

# v8. False-positive gate: a realistic 7-line completion turn -> QUIET.
v8_msg = (
    IDENTITY_COMPLETE
    + "\nShipped unit 3.\nRan lint, typecheck, tests - all green.\n"
    + "Merged to main via squash.\nPulled latest main locally.\n"
    + "Cleaned up the worktree.\nTask is complete.\n"
)
rc, out, err = run_hook(make_payload(v8_msg))
check("v8. realistic 7-line completion turn -> QUIET (false-positive gate)", is_quiet(rc, out))

# v9. False-positive gate: a realistic 7-line answer turn -> QUIET.
v9_msg = (
    IDENTITY_OK
    + '\n"Yes, the fence pool is aggregate, not per-fence."\n'
    + "That closes CF-1 structurally.\nSplitting fences no longer buys extra free lines.\n"
    + "Verified against the exhaustive harness.\nNo further action needed here.\n"
    + "Let me know if that answers it.\n"
)
rc, out, err = run_hook(make_payload(v9_msg))
check("v9. realistic 7-line answer turn -> QUIET (false-positive gate)", is_quiet(rc, out))


# ---------------------------------------------------------------------------
# t. DS-151 finding 4: operator-decisions per-item sprawl check.
#    MAX_LINES_PER_DECISION_ITEM = 3. Item COUNT stays unbounded (already
#    covered by s7/v5b above); this section covers per-item SHAPE.
# ---------------------------------------------------------------------------

# t1. a single item within budget (3 lines) -> QUIET. Continuation lines
# are deliberately NOT bullet/number-prefixed (plain prose) - under the
# new indentation-tolerant _DECISION_ITEM_START_RE (up to 3 leading
# spaces, CF-2 fix), an indented bulleted continuation line would itself
# be recognized as a new item start rather than folding into item 1.
t1_msg = (
    IDENTITY_OK
    + "\n"
    + _nlines(3)
    + "\n## Operator decisions\n1. Proceed with X (Recommended)\n   reason: matches existing pattern.\n   Reply STOP to skip.\n"
)
rc, out, err = run_hook(make_payload(t1_msg))
check("t1. single decision item, 3 lines (at budget) -> QUIET", is_quiet(rc, out))

# t2. REGRESSION (DS-151 Skeptic Major finding 4, exact adversarial input):
# item count stays at 1 (never capped), but the single item sprawls to 40
# lines of narrative - the reported bug ("40 lines of narrative below it
# passes"). Must now be flagged as item sprawl, distinct from the volume
# check (which stops counting at the heading and never sees this content).
t2_msg = (
    IDENTITY_OK
    + "\n"
    + _nlines(3)
    + "\n## Operator decisions\n1. Proceed with X (Recommended)\n"
    + "\n".join(f"   Extra narrative line {i} that should not be here." for i in range(1, 41))
    + "\n"
)
rc, out, err = run_hook(make_payload(t2_msg))
check(
    "t2. single decision item sprawls to 40 lines -> ADVISORY (operator-decisions item sprawl)",
    is_advisory(rc, out, "operator-decisions item sprawl"),
)
check(
    "t2b. item-sprawl advisory names the item and its line count",
    "41 lines" in parse_output(out).get("hookSpecificOutput", {}).get("additionalContext", "")
    and "Proceed with X" in parse_output(out).get("hookSpecificOutput", {}).get("additionalContext", ""),
)

# t2c. REGRESSION (amendment A2, exact adversarial shape): fenced content
# inside a decision item must fold into that item's line count, not
# escape for free. heading + item + a closed 18-line fence -> the fence's
# 20 nonblank lines (18 prose + 2 delimiters) fold into the item (21 lines
# total), sprawl-flagging it; the SAME fenced content also participates in
# the aggregate fence pool at exactly the cap (fence_charge=0), so this
# fixture pins that the two accountings do not double free the content
# (see the module docstring's "Charge model" fence_charge scoping note).
t2c_fence = "\n".join(f"prose line {i}" for i in range(1, 19))
t2c_msg = IDENTITY_OK + "\n\n## Operator decisions\n1. Ship unit 3 now (Recommended)\n```\n" + t2c_fence + "\n```\n"
rc, out, err = run_hook(make_payload(t2c_msg))
check(
    "t2c (A2). fenced content inside a decision item folds into the item's "
    "line count -> ADVISORY (operator-decisions item sprawl)",
    is_advisory(rc, out, "operator-decisions item sprawl"),
)

# t3. many SHORT items (item count unbounded, per-item shape compliant) ->
# QUIET. Distinguishes "many items" (fine) from "one sprawling item" (t2,
# flagged) - both interact with the same unbounded-count guarantee but only
# the latter violates per-item shape.
t3_items = "\n".join(
    f"{i}. Action {i} (Recommended) - reason. Reply STOP to skip." for i in range(1, 21)
)
t3_msg = IDENTITY_OK + "\n" + _nlines(3) + "\n## Operator decisions\n" + t3_items + "\n"
rc, out, err = run_hook(make_payload(t3_msg))
check("t3. 20 short (1-line) decision items, none over per-item budget -> QUIET", is_quiet(rc, out))

# t4. one item at exactly the per-item budget among several compliant items
# -> QUIET, and one item ONE line over -> ADVISORY naming that specific item
# (not a different one), proving per-item (not aggregate) measurement.
t4_msg = (
    IDENTITY_OK
    + "\n"
    + _nlines(3)
    + "\n## Operator decisions\n"
    + "1. Short item (Recommended) - fine.\n"
    + "2. Sprawling item (Recommended)\n   reason line one, not bulleted.\n   reason line two, not bulleted.\n   reason line three, not bulleted.\n"
    + "3. Another short item (Recommended) - fine.\n"
)
rc, out, err = run_hook(make_payload(t4_msg))
check(
    "t4. one item over budget among compliant items -> ADVISORY naming '2. Sprawling item (Recommended)'",
    is_advisory(rc, out, "operator-decisions item sprawl")
    and "2. Sprawling item (Recommended)" in parse_output(out).get("hookSpecificOutput", {}).get("additionalContext", ""),
)


# ---------------------------------------------------------------------------
# u. DS-151 constant/boundary pins, now BEHAVIORAL (test-strategy item 3).
#    u1/u2 (bare BODY_BUDGET_ANSWER / BODY_BUDGET_ANSWER_WEAK_FALLBACK
#    constant pins) are DELETED along with the constants they pinned - both
#    were deleted-mechanism pins with no behavioral coupling, the exact
#    defect class named in the ticket. u3/u4 below assert the fence-cap and
#    per-item-cap BOUNDARIES through the hook's actual QUIET/ADVISORY
#    output; the module is imported only to SIZE the fixtures precisely at
#    the constants' current values, never to compare an integer directly.
# ---------------------------------------------------------------------------

_spec = importlib.util.spec_from_file_location("enforce_turn_shape", HOOK_PATH)
_hook_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_hook_mod)

# u3. fence-cap boundary, asserted behaviorally. Content of exactly
# FENCE_FREE_LINES nonblank lines inside a single closed fence, plus one
# completion-warrant line, stays fully free (charge 1) -> QUIET. Content
# comfortably over the cap (enough to also cross BASE_BODY_BUDGET on its
# own) -> ADVISORY. (A flat +1-line-over-cap probe would NOT necessarily
# flip under the new flat whole-message budget - s12/s12b already pin the
# tighter over/at-cap contrast for that reason.)
_u3_at_cap = "\n".join(f"boundary fence line {i}" for i in range(1, _hook_mod.FENCE_FREE_LINES + 1))
u3_at_msg = IDENTITY_COMPLETE + "\n```\n" + _u3_at_cap + "\n```\nTask is complete.\n"
rc, out, err = run_hook(make_payload(u3_at_msg))
check("u3a. fence content exactly AT FENCE_FREE_LINES -> QUIET (fully free)", is_quiet(rc, out))

_u3_over_cap = "\n".join(
    f"boundary fence line {i}" for i in range(1, _hook_mod.FENCE_FREE_LINES + _hook_mod.BASE_BODY_BUDGET + 5)
)
u3_over_msg = IDENTITY_COMPLETE + "\n```\n" + _u3_over_cap + "\n```\nTask is complete.\n"
rc, out, err = run_hook(make_payload(u3_over_msg))
check(
    "u3b. fence content well over FENCE_FREE_LINES (enough to also cross the "
    "flat budget) -> ADVISORY (turn volume exceeded)",
    is_advisory(rc, out, "turn volume exceeded"),
)

# u4. per-item-cap boundary, asserted behaviorally. An item of exactly
# MAX_LINES_PER_DECISION_ITEM lines is compliant (no sprawl finding); one
# line more triggers the sprawl finding for that item specifically.
_u4_item_at = "1. Item at the cap (Recommended)\n" + "\n".join(
    f"   continuation {i}" for i in range(1, _hook_mod.MAX_LINES_PER_DECISION_ITEM)
)
u4_at_msg = IDENTITY_OK + "\n\n## Operator decisions\n" + _u4_item_at + "\n"
rc, out, err = run_hook(make_payload(u4_at_msg))
check(
    "u4a. item at exactly MAX_LINES_PER_DECISION_ITEM lines -> no sprawl finding",
    "operator-decisions item sprawl" not in parse_output(out).get("hookSpecificOutput", {}).get("additionalContext", ""),
)

_u4_item_over = "1. Item over the cap (Recommended)\n" + "\n".join(
    f"   continuation {i}" for i in range(1, _hook_mod.MAX_LINES_PER_DECISION_ITEM + 1)
)
u4_over_msg = IDENTITY_OK + "\n\n## Operator decisions\n" + _u4_item_over + "\n"
rc, out, err = run_hook(make_payload(u4_over_msg))
check(
    "u4b. item ONE line over MAX_LINES_PER_DECISION_ITEM -> ADVISORY (operator-decisions item sprawl)",
    is_advisory(rc, out, "operator-decisions item sprawl"),
)


# ---------------------------------------------------------------------------
# Loop-guard tests (DS-122 fix: two-layer loop guard on the advisory)
# ---------------------------------------------------------------------------
# Mirrors test-enforce-no-abdication.py's counter-test patterns. The loop
# guard bounds how many times a flagged turn can re-invoke the model: Layer 1
# is the stop_hook_active flag (primary re-entrancy guard); Layer 2 is a
# per-cwd counter capped at CONSECUTIVE_BLOCK_CAP (backstop for CC bug
# #54360). All cases below include a cwd in the payload so the counter is
# engaged.

# Fixed contract value, mirrors CONSECUTIVE_BLOCK_CAP in enforce-turn-shape.py.
# The hook runs as a subprocess so we cannot import the constant.
CONSECUTIVE_BLOCK_CAP = 2
_COUNTER_BASENAME = ".turn-shape-guard-fire-count"


def _make_counter_state(cwd: str, count: int, last_user_msg_count: int) -> str:
    """Write the loop-guard counter file and return its path."""
    agentic_dir = os.path.join(cwd, ".agentic")
    os.makedirs(agentic_dir, exist_ok=True)
    counter_path = os.path.join(agentic_dir, _COUNTER_BASENAME)
    with open(counter_path, "w") as f:
        json.dump({"count": count, "last_user_msg_count": last_user_msg_count}, f)
    return counter_path


def _read_counter_state(cwd: str) -> dict:
    with open(os.path.join(cwd, ".agentic", _COUNTER_BASENAME)) as f:
        return json.load(f)


with tempfile.TemporaryDirectory() as lg_tmp_dir:
    lg_real = os.path.realpath(lg_tmp_dir)
    flagged_msg = "Done."

    # L1. Layer 1: stop_hook_active=true on a flagged message -> QUIET.
    rc, out, err = run_hook(
        make_payload(flagged_msg, cwd=lg_real, extra={"stop_hook_active": True})
    )
    check("L1. stop_hook_active=true on a flagged message -> QUIET (no advisory)", is_quiet(rc, out))

    # L2. Layer 2: consecutive flagged turns in the same cwd -> advisory,
    # advisory, then QUIET once count reaches CAP.
    cap_dir = os.path.join(lg_real, "cap_cwd")
    os.makedirs(os.path.join(cap_dir, ".agentic"), exist_ok=True)
    _make_counter_state(cap_dir, CONSECUTIVE_BLOCK_CAP - 1, 0)
    rc, out, err = run_hook(make_payload(flagged_msg, cwd=cap_dir))
    check("L2a. counter at 1/2 -> ADVISORY (fires, increments to 2)", is_advisory(rc, out, "identity"))
    check("L2b. counter incremented to 2", _read_counter_state(cap_dir)["count"] == 2)
    rc, out, err = run_hook(make_payload(flagged_msg, cwd=cap_dir))
    check("L2c. counter at CAP=2 -> QUIET (advisory halted)", is_quiet(rc, out))

    # L3. A new genuine user message resets the counter -> advisory fires again.
    reset_dir = os.path.join(lg_real, "reset_cwd")
    os.makedirs(os.path.join(reset_dir, ".agentic"), exist_ok=True)
    _make_counter_state(reset_dir, CONSECUTIVE_BLOCK_CAP, 1)  # at CAP, last_user_msg_count=1
    reset_transcript_path = _write_transcript(
        reset_dir,
        [
            {"role": "user", "content": [{"type": "text", "text": "Hello"}]},
            {"role": "assistant", "content": [{"type": "text", "text": IDENTITY_COMPLETE}]},
            {"role": "user", "content": [{"type": "text", "text": "Now proceed"}]},
            {"role": "assistant", "content": [{"type": "text", "text": flagged_msg}]},
        ],
    )
    rc, out, err = run_hook(
        json.dumps(
            {
                "cwd": reset_dir,
                "last_assistant_message": flagged_msg,
                "transcript_path": reset_transcript_path,
            }
        )
    )
    check("L3. new genuine user message (2>1) resets counter -> ADVISORY again", is_advisory(rc, out, "identity"))

    # L4. A clean turn resets the counter -> next flagged turn advisories
    # again. Seeded at CAP-1 (below the cap) so the clean turn is classifiable
    # and reaches the clean-turn reset; a clean turn at CAP would exit at the
    # CAP check before classification (the sibling hook's order), which is the
    # blocked-loop scenario, not the re-arming scenario this case pins.
    clean_reset_dir = os.path.join(lg_real, "clean_reset_cwd")
    os.makedirs(os.path.join(clean_reset_dir, ".agentic"), exist_ok=True)
    _make_counter_state(clean_reset_dir, CONSECUTIVE_BLOCK_CAP - 1, 0)  # count=1
    rc, out, err = run_hook(make_payload(IDENTITY_COMPLETE, cwd=clean_reset_dir))
    check("L4a. clean turn -> QUIET (no advisory)", is_quiet(rc, out))
    check("L4b. clean turn resets counter to 0", _read_counter_state(clean_reset_dir)["count"] == 0)
    rc, out, err = run_hook(make_payload(flagged_msg, cwd=clean_reset_dir))
    check("L4c. after clean-turn reset -> ADVISORY again", is_advisory(rc, out, "identity"))

    # L5. Counter write failure (unwritable .agentic/) -> QUIET, fail-open.
    unwrite_dir = os.path.join(lg_real, "unwritable_cwd")
    os.makedirs(unwrite_dir, exist_ok=True)
    unwrite_agentic = os.path.join(unwrite_dir, ".agentic")
    os.makedirs(unwrite_agentic, exist_ok=True)
    os.chmod(unwrite_agentic, 0o555)
    try:
        rc, out, err = run_hook(make_payload(flagged_msg, cwd=unwrite_dir))
        check("L5. unwritable .agentic/ (counter write fails) -> QUIET, fail-open", is_quiet(rc, out))
    finally:
        os.chmod(unwrite_agentic, 0o755)

    # L6. Never-block invariant under the loop guard: whatever the guard does,
    # it never emits a blocking decision (there is no such code path).
    rc, out, err = run_hook(make_payload(flagged_msg, cwd=cap_dir))
    check(
        "L6. loop-guard path never blocks (exit 0, no block decision)",
        rc == 0 and parse_output(out).get("decision") != "block",
    )


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

print()
if failed == 0:
    print(f"All {total} tests passed.")
    sys.exit(0)
else:
    print(f"{failed}/{total} test assertion(s) FAILED.")
    sys.exit(1)
