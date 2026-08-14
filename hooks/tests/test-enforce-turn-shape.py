# Run with: python3 hooks/tests/test-enforce-turn-shape.py
"""
Unit tests for hooks/enforce-turn-shape.py (DS-122).

Each case pipes a JSON payload into the hook via stdin and asserts:
  ADVISORY - exit 0, hookSpecificOutput.additionalContext starts with
             "TURN-SHAPE:" and contains the expected finding substring.
  QUIET    - exit 0, no stdout at all (silent allow).

The hook MUST NEVER emit a blocking decision under any input - there is no
{"decision": "block", ...} shape this hook can produce.

DS-155: the identity-line check is REMOVED (operator decision - see
hooks/enforce-turn-shape.py's module docstring "DS-155 round 3 history
note"). Cases a/a2/b/x (round-1/round-2 identity-check and
ticket-context-exemption coverage) are DELETED with the check they
tested, not merely renumbered - a deleted check should make this suite
SMALLER, not just different. `_IDENTITY_LINE_RE` itself is ALSO fully
DELETED (round 4: round 3's "retain it, the forced-yield check depends
on it" rationale was verified wrong by execution - _forced_yield_flag
reasons positionally via _body_after_identity_line, with no regex
dependency at all). It has zero occurrences anywhere in the hook source
now, and test "q" (which used to pin its catastrophic-backtracking fix)
is deleted along with it - see "r" below for the surviving regression
guard, which pins the check's absence rather than the regex's presence.

Test coverage (mirrors the 14-case spec in the DS-122 spawn brief, minus
the deleted identity-check cases):
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
  r. DS-155: well-formed vs. missing/malformed identity line produce the
     IDENTICAL verdict - pins that no code path still branches on the
     identity line's shape for a live finding (supersedes the
     round-1/round-2 versions of this test, which pinned the now-deleted
     finding's own worked-example text; test "q", which pinned
     _IDENTITY_LINE_RE's catastrophic-backtracking fix directly, is
     DELETED along with the regex itself in round 4 - there is nothing
     left to pin a performance guard for)
  w. DS-155 answer-warrant transcript bonus (_transcript_answer_bonus):
     genuine-question detection, the recency gate
     (_has_intervening_assistant_turn), and its corpus-measured fixes -
     w8/w8b (round 4: the assistant's own earlier narration-then-tool-call
     step must not count as a competing "intervening" turn), w9 (round 3:
     the mirror image - when the current turn's own entry is not yet on
     disk, a genuinely stale-by-one question must still be caught), and
     w10 (round 5: message.id-scoped tool_use attribution must not leak
     past the ONE text entry it explains and excuse an unrelated,
     genuinely separate completed turn elsewhere in the same window)
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
import subprocess
import sys
import tempfile

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


def is_blocking(returncode: int, stdout: str, contains: str | None = None) -> bool:
    """DS-156: _execution_prose_flag's BLOCKING finding shape - the process
    exit code is still 0 (per the module's Public API contract - the
    process never exits non-zero), but stdout carries {"decision":
    "block", "reason": "TURN-SHAPE: <finding>"}, the same shape
    hooks/enforce-no-abdication.py uses."""
    if returncode != 0:
        return False
    obj = parse_output(stdout)
    if obj.get("decision") != "block":
        return False
    reason = obj.get("reason", "")
    if not reason.startswith("TURN-SHAPE:"):
        return False
    if contains is not None and contains not in reason:
        return False
    return True


def check(label: str, condition: bool):
    global total, failed
    total += 1
    status = "PASS" if condition else "FAIL"
    if not condition:
        failed += 1
    print(f"  [{status}] {label}")


# DS-155 round 3: the identity-line check is REMOVED (operator decision -
# see hooks/enforce-turn-shape.py's module docstring "DS-155 round 3
# history note"). FLAGGED_STATUS_ONLY_MSG is kept as a fixture (it no
# longer flags anything post-DS-171 - see below) purely because deleting
# it would ripple through every historical comment that names it; it is
# no longer used to exercise any generic mechanism.
FLAGGED_STATUS_ONLY_MSG = (
    IDENTITY_OK + "\n"
    "Did a first thing.\n"
    "Did a second thing.\n"
    "Did a third thing.\n"
)

# DS-171: FLAGGED_SPRAWL_MSG replaces FLAGGED_STATUS_ONLY_MSG everywhere a
# generically-flagged (ADVISORY) message is needed to exercise a mechanism
# unrelated to the specific finding text (config toggle, loop guard,
# log_fire-once, exit-code checks) - the status-only check that used to
# supply that role is retired, so FLAGGED_STATUS_ONLY_MSG alone no longer
# produces ANY finding. FLAGGED_SPRAWL_MSG instead trips the sole
# surviving advisory check, `_decision_item_sprawl_flag`, via a single
# "## Operator decisions" item one line over ITEM_FREE_LINES.
FLAGGED_SPRAWL_MSG = (
    IDENTITY_OK + "\n"
    "\n"
    "## Operator decisions\n"
    "- Proceed with the migration now.\n"
    "  Continuation line one explaining why.\n"
    "  Continuation line two explaining why.\n"
    "  Continuation line three explaining why.\n"
)

# ---------------------------------------------------------------------------
# c. status-only flag: RETIRED (DS-171). See hooks/enforce-turn-shape.py's
#    Purpose section - the status-only rule now lives in the `dinostack`
#    output style, not this hook.
# ---------------------------------------------------------------------------

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
# DS-156 CORE REGRESSION TEST (the operator's founding complaint - see
# content/references/conductor-turn-format.md's "Worked non-example"): a
# decision-warrant turn whose status region carries narrative prose beyond
# the structured slots now BLOCKS, exactly this shape. Previously
# (pre-DS-156) the decision warrant alone suppressed the status-only
# check and this was QUIET - the assertion is flipped, not deleted.
check(
    "d. '## Operator decisions' heading present, but narrative prose in "
    "the status region -> BLOCKING (DS-156 core regression test)",
    is_blocking(rc, out, "unrecognized line in the status region"),
)

decision_compliant_msg = (
    IDENTITY_OK + "\n"
    "State: did a first thing.\n"
    "Running: doing a second thing.\n"
    "\n"
    "## Operator decisions\n"
    "- Proceed with X (Recommended)\n"
)
rc, out, err = run_hook(make_payload(decision_compliant_msg))
check(
    "d2. '## Operator decisions' heading present, status region uses only "
    "recognized slot lines -> QUIET",
    is_quiet(rc, out),
)

# ---------------------------------------------------------------------------
# e. completion warrant: '[phase: complete]' / explicit phrase pass;
#    bare done/shipped/merged does NOT count as completion
# ---------------------------------------------------------------------------

completion_explicit_msg = (
    IDENTITY_OK + "\n"
    "State: first thing done.\n"
    "Blocked: nothing.\n"
    "State: task is complete.\n"
)
rc, out, err = run_hook(make_payload(completion_explicit_msg))
check(
    "e1. explicit terminal phrase ('task is complete') on a recognized "
    "slot line -> QUIET (completion warrant recognized)",
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
    "e2. bare 'merged' does NOT satisfy completion warrant -> QUIET "
    "(DS-171: status-only check retired, so the zero-warrant fallback is "
    "now silent regardless; the underlying warrant-classification claim "
    "is covered directly by section e's other cases and the c-* corpus "
    "loop, both of which assert `_classify_warrants` without depending "
    "on the retired hook-level distinction)",
    is_quiet(rc, out),
)

bare_shipped_msg = (
    IDENTITY_OK + "\n"
    "First line of prose.\n"
    "Second line of prose.\n"
    "PR shipped, pulling main.\n"
)
rc, out, err = run_hook(make_payload(bare_shipped_msg))
check(
    "e3. bare 'shipped' does NOT satisfy completion warrant -> QUIET "
    "(DS-171: status-only check retired)",
    is_quiet(rc, out),
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
    "f. Waiting: line + extra prose, no other warrant -> BLOCKING (DS-156: "
    "_execution_prose_flag replaces the advisory forced-yield check)",
    is_blocking(rc, out, "sole-stoppage"),
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

# DS-171: "Done." no longer produces any finding at all (the status-only
# check it used to trip is retired), so a kill-switch test built on it
# would be vacuous - the switch could be entirely broken and this would
# still pass. Swapped to FLAGGED_SPRAWL_MSG (the sole surviving advisory
# check), with an h0 control proving the fixture is genuinely advisory
# with the switch OFF, so h1's QUIET is attributable to the switch.
rc, out, err = run_hook(make_payload(FLAGGED_SPRAWL_MSG))
check("h0. control: FLAGGED_SPRAWL_MSG without the kill switch -> ADVISORY", is_advisory(rc, out))

rc, out, err = run_hook(make_payload(FLAGGED_SPRAWL_MSG), env={"AE_TURN_SHAPE_GUARD_DISABLE": "1"})
check("h1. kill-switch set -> QUIET even on a flagged message", is_quiet(rc, out))

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
    rc, out, err = run_hook(make_payload(FLAGGED_SPRAWL_MSG, cwd=i1_cwd))
    check("i1. config.json absent -> guard ON (ADVISORY on flagged message)", is_advisory(rc, out, "operator-decisions item sprawl"))

    # i2. config.json present, key explicitly false -> guard OFF.
    i2_cwd = _fresh_cwd("i2")
    with open(os.path.join(i2_cwd, ".agentic", "config.json"), "w") as f:
        json.dump({"turn_shape_guard_enabled": False}, f)
    rc, out, err = run_hook(make_payload(FLAGGED_SPRAWL_MSG, cwd=i2_cwd))
    check("i2. turn_shape_guard_enabled=false -> QUIET (guard disabled)", is_quiet(rc, out))

    # i3. config.json present, key explicitly true -> guard ON.
    i3_cwd = _fresh_cwd("i3")
    with open(os.path.join(i3_cwd, ".agentic", "config.json"), "w") as f:
        json.dump({"turn_shape_guard_enabled": True}, f)
    rc, out, err = run_hook(make_payload(FLAGGED_SPRAWL_MSG, cwd=i3_cwd))
    check("i3. turn_shape_guard_enabled=true -> ADVISORY (guard on)", is_advisory(rc, out, "operator-decisions item sprawl"))

    # i4. config.json present but key absent -> guard stays ON.
    i4_cwd = _fresh_cwd("i4")
    with open(os.path.join(i4_cwd, ".agentic", "config.json"), "w") as f:
        json.dump({"some_other_key": True}, f)
    rc, out, err = run_hook(make_payload(FLAGGED_SPRAWL_MSG, cwd=i4_cwd))
    check("i4. config.json present, key absent -> guard ON", is_advisory(rc, out, "operator-decisions item sprawl"))

# ---------------------------------------------------------------------------
# j. output is ALWAYS exit 0 regardless of findings
# ---------------------------------------------------------------------------

rc_flagged, _, _ = run_hook(make_payload(FLAGGED_SPRAWL_MSG))
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
check(
    "l1. completion warrant + Waiting: line, but a non-slot/non-Waiting: "
    "narrative sentence is present too -> BLOCKING (DS-156: this is not "
    "sole-stoppage since completion also fired, so the GENERAL branch "
    "applies and the narrative sentence is an unrecognized status-region "
    "line - this is exactly the worked non-example the spec exists to "
    "catch)",
    is_blocking(rc, out, "unrecognized line in the status region"),
)

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
    "m. stoppage-only + one explanatory sentence -> BLOCKING (DS-156)",
    is_blocking(rc, out, "sole-stoppage"),
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
    "p. apostrophes do NOT satisfy the answer warrant -> QUIET (DS-171: "
    "status-only check retired, so this is silent regardless; kept as a "
    "regression pin that no code path re-derives the answer warrant from "
    "these apostrophes)",
    is_quiet(rc, out),
)

# ---------------------------------------------------------------------------
# Import the hook module directly (needed by "n"/"r" below). DS-155 round
# 4: test "q" (pinning _IDENTITY_LINE_RE's catastrophic-backtracking fix)
# is DELETED, not merely retargeted - the regex itself is now fully
# deleted from the hook (round 3's "retain it, nothing else depends on
# it" call was based on a wrong assumption about the forced-yield check;
# verified by execution that _forced_yield_flag reasons positionally via
# _body_after_identity_line, with no regex dependency at all), so there
# is nothing left for a performance regression guard to protect.
# ---------------------------------------------------------------------------

_spec = importlib.util.spec_from_file_location(
    "enforce_turn_shape", os.path.join(os.path.dirname(__file__), "..", "enforce-turn-shape.py")
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

# ---------------------------------------------------------------------------
# n. log_fire() called exactly once on a finding, not called on a clean turn
#    (patches _load_log_fire directly via module import, per spec)
# ---------------------------------------------------------------------------


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
_out_flagged = _run_main_with_stdin(make_payload(FLAGGED_SPRAWL_MSG), _calls_flagged)
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
# r. REGRESSION (DS-155 round 3, updated round 4 - _IDENTITY_LINE_RE
#    itself is now fully deleted, not merely unreferenced from main()):
#    a message whose first line is a well-formed identity line produces
#    the IDENTICAL result (QUIET) as the same message with a
#    missing/malformed first line, given the same downstream content -
#    proving the identity-line check is genuinely gone, not just
#    unreachable, and guarding against a future re-introduction of a live
#    branch on identity-line shape without an explicit design decision.
# ---------------------------------------------------------------------------

_r_with_identity = IDENTITY_OK + "\nTask is complete.\n"
_r_without_identity = "not an identity line at all\nTask is complete.\n"
_rc_a, _out_a, _ = run_hook(make_payload(_r_with_identity))
_rc_b, _out_b, _ = run_hook(make_payload(_r_without_identity))
# DS-156: this pair now BLOCKS (a completion-warrant execution turn whose
# status region contains a narrative sentence rather than a recognized
# slot/Waiting: line is exactly what _execution_prose_flag's general
# branch catches) - but the SAME verdict, for the SAME reason, regardless
# of the first line's shape, which is still the point of this regression
# guard: no code path branches on the identity line's SHAPE, only (DS-156)
# on its LENGTH.
check(
    "r. well-formed vs. missing identity line produce the SAME verdict "
    "(no live shape enforcement on the identity line)",
    is_blocking(_rc_a, _out_a, "unrecognized line in the status region")
    and is_blocking(_rc_b, _out_b, "unrecognized line in the status region"),
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
        "o1. transcript fallback, single string-content block -> BLOCKING (DS-156)",
        is_blocking(rc, out, "sole-stoppage"),
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
        "o2. transcript fallback, two-block content joined with newline -> "
        "BLOCKING (DS-156)",
        is_blocking(rc, out, "sole-stoppage"),
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


def _status_slot_lines(n: int, label: str = "State") -> str:
    """DS-156: recognized State:/Running:/Blocked: slot-line filler for
    tests that need N charged status-region lines on a GENERAL-branch
    execution turn (decision and/or completion present). Unlike
    _nlines()'s generic narrative sentences, each line here matches
    _STATUS_SLOT_LINE_RE and therefore passes _execution_prose_flag's
    shape whitelist while still charging 1 in the volume check (a slot
    line is never exempt the way a well-formed Waiting: line can be) -
    letting these fixtures keep pinning the SAME volume-charge math as
    before DS-156 without tripping the new BLOCKING shape check."""
    return "\n".join(f"{label}: filler {i}." for i in range(1, n + 1)) + "\n"


# s1. decision warrant, body AT the flat budget (10 lines) -> QUIET.
# (A9: relabeled - the old per-warrant DECISION budget of 3 no longer
# exists; this now pins the flat BASE_BODY_BUDGET boundary.) DS-156:
# filler is now recognized State: slot lines, not generic narrative
# ("Line N.") - the general branch of _execution_prose_flag would BLOCK
# unrecognized status-region prose before the volume check is ever
# reached; _status_slot_lines() preserves the identical charge (1 per
# line) while staying shape-compliant.
s1_msg = IDENTITY_OK + "\n" + _status_slot_lines(BASE_BODY_BUDGET) + "\n## Operator decisions\n- Proceed with X (Recommended)\n"
rc, out, err = run_hook(make_payload(s1_msg))
check("s1. decision warrant, body at flat budget (10 lines) -> QUIET", is_quiet(rc, out))

# s2. RETIRED (DS-171): pinned the flat-budget-plus-one-line ADVISORY via
# the now-deleted turn-charge volume check.

# s3. completion warrant, body AT the flat budget (10 lines) -> QUIET.
# (A9: relabeled from the old COMPLETION budget of 6.)
s3_msg = IDENTITY_COMPLETE + "\n" + _status_slot_lines(BASE_BODY_BUDGET, label="State")
rc, out, err = run_hook(make_payload(s3_msg))
check("s3. completion warrant, body at flat budget (10 lines) -> QUIET", is_quiet(rc, out))

# s4. FLIP (plan test-strategy table): under the deleted per-warrant model
# this 7-line completion turn was ADVISORY (over the old COMPLETION budget
# of 6) - this WAS the round-2 false positive. Under the flat 10-line
# budget it is QUIET; the assertion is inverted deliberately, not deleted,
# so a regression back to a tight per-warrant budget is caught.
s4_msg = IDENTITY_COMPLETE + "\n" + _status_slot_lines(7, label="State")
rc, out, err = run_hook(make_payload(s4_msg))
check(
    "s4. FLIP: completion warrant, 7-line body (was ADVISORY under the deleted "
    "per-warrant model - this WAS the round-2 FP) -> now QUIET under the flat budget",
    is_quiet(rc, out),
)

# s4b. RETIRED (DS-171): pinned the over-flat-budget ADVISORY via the now-
# deleted turn-charge volume check.

# ---------------------------------------------------------------------------
# c. DS-156 widened completion warrant (real-corpus-motivated, round 2 -
#    see hooks/tests/fixtures/turn-shape-completion-corpus.json for the
#    main-agent-only hand-labelled set and the measured before/after
#    numbers cited in _LEADING_COMPLETION_RE's docstring). Each `c*` case
#    below is built from the fixture's own `template` field, reconstructed
#    from a REAL main-agent transcript turn (sanitized to remove any
#    proprietary content), a round-1 regression pin, or an explicitly
#    labelled Skeptic-constructed adversarial probe - the fixture's own
#    `source` field states which, never a description of which regex
#    branch the case exercises. Matches this file's existing s/v/t-series
#    pattern of programmatically-built messages rather than embedding raw
#    corpus text inline here.
# ---------------------------------------------------------------------------

with open(
    os.path.join(os.path.dirname(__file__), "fixtures", "turn-shape-completion-corpus.json"),
    "r",
    encoding="utf-8",
) as _cf:
    _completion_fixture = json.load(_cf)

# DS-171: this loop previously routed each case through the hook and
# distinguished QUIET (completion warrant granted, execution turn stays
# under budget) from ADVISORY-status-only (completion warrant denied,
# zero-warrant fallback). With the turn-charge volume check AND the
# status-only check both retired, a completion turn is now QUIET
# regardless of length, and a zero-warrant turn is ALSO now QUIET (silent
# allow) - so the hook-level QUIET/ADVISORY distinction this loop depended
# on no longer exists, and routing through the hook would make every case
# assert the same (now-true) thing regardless of whether the corpus
# fixture's completion-warrant classification is actually correct. This
# loop now asserts `_classify_warrants`'s `completion` key directly
# against each case's own template text (no filler needed - filler
# existed only to route the message through the hook's QUIET/ADVISORY
# split, never to influence the warrant itself), which is the actual
# regression signal this corpus protects and is unaffected by DS-171.
for _case in _completion_fixture["cases"]:
    _expect_completion = _case["expected"] == "quiet"
    _case_warrants = _mod._classify_warrants(_case["template"])
    check(
        f"c-{_case['id']} ({_case['shape_class']}): {_case['source']} -> "
        f"completion warrant {'GRANTED' if _expect_completion else 'DENIED'} (expected)",
        _case_warrants["completion"] == _expect_completion,
    )

# s5/s6/s6b/s6c: RETIRED (DS-171). Pinned the separate, higher
# ANSWER_BODY_BUDGET=50 ceiling for Answer turns via the now-deleted
# turn-charge volume check.

# s5c. DS-156 CONTRAST (supersedes the deleted DS-151 "identical verdict"
# fixture - warrant composition changes the entire enforcement posture,
# not just a budget): an incidental quoted fragment does not just change
# which check would apply, it changes whether ANY structural shape check
# runs at all, because Answer always wins the shape question (§4). The
# SAME narrative body - "Also did thing N." lines, which are not a
# recognized State:/Running:/Blocked:/Waiting: slot line - is QUIET as an
# Answer turn (DS-171: no hook check inspects Answer-turn shape any more)
# but BLOCKS as a pure completion execution turn (routes to
# _execution_prose_flag's general branch, which rejects unrecognized
# status-region prose).
s5c_with_quote_msg = (
    IDENTITY_COMPLETE
    + "\n"
    + 'Merged "fix: resolve turn-shape gate regression" into main.\n'
    + _nlines(7, prefix="Also did thing")
)
rc, out, err = run_hook(make_payload(s5c_with_quote_msg))
check(
    "s5c. incidental quote grants the answer warrant, which wins the shape "
    "question -> QUIET (routes to _answer_relevance_flag, not the "
    "structural shape check)",
    is_quiet(rc, out),
)

s5c_no_quote_msg = (
    IDENTITY_COMPLETE
    + "\n"
    + "Merged the fix for the turn-shape gate regression into main.\n"
    + _nlines(7, prefix="Also did thing")
)
rc, out, err = run_hook(make_payload(s5c_no_quote_msg))
check(
    "s5c-b. same narrative body WITHOUT the quote, same completion warrant "
    "-> BLOCKING (DS-156: no answer warrant means this is a pure execution "
    "turn, and the narrative body is unrecognized status-region prose) - "
    "DIFFERENT verdict from s5c, proving warrant composition now changes "
    "the enforcement posture itself, not just the budget",
    is_blocking(rc, out, "unrecognized line in the status region"),
)

# s7. decisions-block exemption: a large number of decision items (10, well
# beyond the flat budget's line count if they were charged individually)
# does NOT count against the volume check by ITEM COUNT - only actual line
# count (short items, none over ITEM_FREE_LINES) is measured. Also pins
# that content/sections/02-delegation.md's ban on a decision-item cap is
# respected (no item-count limit is applied anywhere in this hook).
s7_decision_items = "\n".join(f"{i}. Action {i} - reason. Reply STOP to skip." for i in range(1, 11))
s7_msg = IDENTITY_OK + "\n" + _status_slot_lines(BASE_BODY_BUDGET) + "\n## Operator decisions\n" + s7_decision_items + "\n"
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
s8_msg = IDENTITY_COMPLETE + "\n" + _status_slot_lines(9, label="State") + "Waiting: nothing further.\n"
rc, out, err = run_hook(make_payload(s8_msg))
check(
    "s8. stoppage+completion combo, 10 lines (9 prose + 1 Waiting:, not sole "
    "stoppage so it charges) -> QUIET at the flat budget",
    is_quiet(rc, out),
)

# s8b. Re-derived (Skeptic Minor, round 1 finding): the deleted
# `_forced_yield_flag` concept made the old s8b assertion
# ('"forced-yield" not in additionalContext') pass VACUOUSLY, since s8 is
# QUIET and additionalContext is always "" on a quiet turn - it asserted
# nothing. The real claim s8b is meant to pin is that the combo turn is
# routed to `_execution_prose_flag`'s GENERAL branch (fence-aware status
# region), not the sole-stoppage branch (raw-line, fence-blind), because
# completion is also present. Prove it by adding a FENCED narrative aside
# after the Waiting: line: the general branch ignores fenced status-region
# lines and stays QUIET, whereas the sole-stoppage branch is fence-blind
# and would BLOCK on the identical aside (see ds156-f above, which pins
# exactly that BLOCKING behavior on a genuine sole-stoppage turn). This
# assertion was verified failing against the pre-fix vacuous form (it
# always passed) and is confirmed non-vacuous here (see round-2 report).
s8b_msg = (
    IDENTITY_COMPLETE
    + "\n" + _status_slot_lines(9, label="State") + "Waiting: nothing further.\n"
    + "```\nAn aside, fenced, that is still not a Waiting: line.\n```\n"
)
rc, out, err = run_hook(make_payload(s8b_msg))
check(
    "s8b. combo case with a fenced aside after the Waiting: line -> QUIET "
    "(routed to the general/fence-aware branch, not sole-stoppage, because "
    "completion is also present)",
    is_quiet(rc, out),
)

# s8-over: RETIRED (DS-171). Pinned the over-flat-budget ADVISORY via the
# now-deleted turn-charge volume check.

# s9. same combo, AT the flat budget (9 prose + 1 Waiting: = 10 lines) ->
# QUIET. (A9: relabeled from "at the completion budget (6 lines)" - the
# per-warrant COMPLETION budget no longer exists; this pins the flat
# 10-line boundary for the combo shape, identical to s8 above by
# construction - kept as a separate fixture per the plan's fixture table.)
s9_msg = IDENTITY_COMPLETE + "\n" + _status_slot_lines(9, label="State") + "Waiting: nothing further.\n"
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
# conductor-turn-format.md:64 states the Waiting: count is "unbounded, not
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
# DS-156: "Here is the diff." / "Applied cleanly." are recognized State:
# slot lines, not generic narrative - the general branch of
# _execution_prose_flag would BLOCK unrecognized status-region prose
# before the volume check ever runs. The fence content itself is
# unaffected (still excluded from the shape check's domain entirely).
s11_msg = (
    IDENTITY_OK
    + "\nState: here is the diff.\n```python\n"
    + s11_code_lines
    + "\n```\nState: applied cleanly.\n\n## Operator decisions\n- Proceed with X (Recommended)\n"
)
rc, out, err = run_hook(make_payload(s11_msg))
check(
    "s11. fenced code block excluded from volume count (2 real body lines) -> QUIET",
    is_quiet(rc, out),
)

# s12: RETIRED (DS-171). Pinned the over-FENCE_FREE_LINES ADVISORY via the
# now-deleted turn-charge volume check (that constant, too, is deleted).

# s12b. Fence content of FENCE_FREE_LINES lines (a local test-file sizing
# constant only - the hook's own FENCE_FREE_LINES is deleted, DS-171)
# stays fully excluded from the shape check -> QUIET. Post-DS-171 this is
# true of fenced content of ANY length (there is no longer a volume check
# to cross), so this fixture size is no longer a meaningful boundary - the
# fixture is kept at its historical size rather than resized, since the
# assertion (QUIET) is unconditionally true and still exercises the fence-
# exclusion behavior of `_execution_prose_flag`'s general branch.
s12b_fence_lines = "\n".join(f"Prose line {i}." for i in range(1, FENCE_FREE_LINES + 1))
s12b_msg = (
    IDENTITY_COMPLETE
    + "\nState: here is the summary.\n```\n"
    + s12b_fence_lines
    + "\n```\nState: done reporting.\n"
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
# DS-156 RE-DERIVATION: an unclosed fence's content is NOT fenced from
# _execution_prose_flag's general-branch perspective either (_segment
# fails closed on both consumers), so this now BLOCKS before the volume
# check is ever reached - the buffered "line_i = i" lines are unrecognized
# status-region prose regardless of the volume model's own "every buffered
# line counts at full weight" charge-model story, which never gets
# evaluated on an execution turn any more. Wrapper lines are still
# converted to State: slot lines for consistency (they no longer determine
# the outcome, since the fence body itself is what trips the finding).
s13_msg = IDENTITY_COMPLETE + "\nState: here is the diff.\nState: more prose here.\n```python\n" + s13_fence_body + "\n"
rc, out, err = run_hook(make_payload(s13_msg))
check(
    "s13. unclosed fence (15 lines) at true EOF -> BLOCKING (DS-156: the "
    "buffered fence body is unrecognized status-region prose, caught by "
    "the structural shape check before the volume model's own "
    "unclosed-fence charge story is ever reached)",
    is_blocking(rc, out, "unrecognized line in the status region"),
)

s13_closed_msg = (
    IDENTITY_COMPLETE
    + "\nState: here is the diff.\nState: more prose here.\n```python\n"
    + s13_fence_body
    + "\n```\nState: done reporting.\n"
)
rc, out, err = run_hook(make_payload(s13_closed_msg))
check(
    "s13-closed. IDENTICAL 15-line fence content, validly CLOSED -> QUIET "
    "(the contrast: unclosed still blocks, closed correctly excludes the "
    "fence from the shape check's domain)",
    is_quiet(rc, out),
)

# s13b/s13c DS-156 RE-DERIVATION: this used to be a boundary pair for the
# unclosed-fence VOLUME charge (exactly at budget vs. one over). That
# boundary no longer exists as a distinguishable outcome on an execution
# turn: _execution_prose_flag's general branch returns on the FIRST
# unrecognized line, so both the "at budget" and "one over" variants now
# produce the IDENTICAL verdict (BLOCKING) regardless of the buffered
# line count - the shape check fires unconditionally on any unrecognized
# content, before volume math is ever computed.
_s13b_prose = "\n".join(f"Prose line {i}." for i in range(1, 5))
_s13b_fence = "\n".join(f"fence line {i}" for i in range(1, 6))
s13b_msg = IDENTITY_COMPLETE + "\n" + _s13b_prose + "\n```\n" + _s13b_fence + "\n"
rc, out, err = run_hook(make_payload(s13b_msg))
check(
    "s13b. unclosed fence, buffered count at the OLD flat-budget boundary "
    "(10) -> BLOCKING (DS-156: the boundary is moot - unrecognized content "
    "blocks regardless of count)",
    is_blocking(rc, out, "unrecognized line in the status region"),
)

_s13c_fence = "\n".join(f"fence line {i}" for i in range(1, 7))
s13c_msg = IDENTITY_COMPLETE + "\n" + _s13b_prose + "\n```\n" + _s13c_fence + "\n"
rc, out, err = run_hook(make_payload(s13c_msg))
check(
    "s13c. unclosed fence, buffered count one line MORE than s13b -> "
    "IDENTICAL verdict (BLOCKING) - proving the old volume boundary "
    "distinction is genuinely moot now, not merely untested",
    is_blocking(rc, out, "unrecognized line in the status region"),
)


# ---------------------------------------------------------------------------
# v. DS-151 new regression fixtures (verified escapes under the OLD,
#    deleted per-warrant exclusion model). DS-171: v1-v4, v6, v6b, and v7
#    are DELETED - each pinned an outcome via the now-retired turn-charge
#    volume check (`is_advisory(rc, out, "turn volume exceeded")` or a
#    bare charge-count assertion), which no longer fires. v5/v5b/v7b/v8/
#    v8b/v9 are KEPT: their assertions are QUIET/BLOCKING outcomes of the
#    still-live `_execution_prose_flag`/`_decision_item_sprawl_flag`
#    checks, unaffected by the volume-check retirement.
# ---------------------------------------------------------------------------

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

# v7b. CONTRAST (not an escape fixture): 50 well-formed Waiting: lines,
# sole warrant -> QUIET. Confirms the free pool is genuinely unbounded by
# COUNT for well-formed lines, only bounded by CHARACTER LENGTH per line.
v7b_msg = IDENTITY_OK + "\n" + "\n".join(f"Waiting: item {i}." for i in range(1, 51)) + "\n"
rc, out, err = run_hook(make_payload(v7b_msg))
check("v7b. 50 well-formed Waiting: lines (sole warrant) -> QUIET", is_quiet(rc, out))

# v8 DS-156 RE-DERIVATION: this used to be a false-positive gate proving a
# realistic multi-line completion narrative stays QUIET. Under DS-156 this
# IS the shape the spec exists to catch - a completion-warrant turn with
# narrative prose beyond the structured slots - so the assertion is
# flipped to BLOCKING, not deleted; v8b below is the replacement
# false-positive gate, using the CORRECT (compliant) shape for the same
# real-world content.
v8_msg = (
    IDENTITY_COMPLETE
    + "\nShipped unit 3.\nRan lint, typecheck, tests - all green.\n"
    + "Merged to main via squash.\nPulled latest main locally.\n"
    + "Cleaned up the worktree.\nTask is complete.\n"
)
rc, out, err = run_hook(make_payload(v8_msg))
check(
    "v8. realistic 7-line completion NARRATIVE (the exact shape DS-156 "
    "targets) -> BLOCKING",
    is_blocking(rc, out, "unrecognized line in the status region"),
)

# v8b. The CORRECT shape for the same completion moment - a single State:
# status slot, nothing else - stays QUIET. This is the genuine
# false-positive gate DS-156 requires: a compliant, realistic execution
# turn must never be flagged.
v8b_msg = IDENTITY_COMPLETE + "\nState: unit 3 shipped, merged to main, worktree cleaned up.\n"
rc, out, err = run_hook(make_payload(v8b_msg))
check(
    "v8b. same completion moment, compliant single State: slot -> QUIET "
    "(false-positive gate)",
    is_quiet(rc, out),
)

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
    + _status_slot_lines(3)
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
    + _status_slot_lines(3)
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
t3_msg = IDENTITY_OK + "\n" + _status_slot_lines(3) + "\n## Operator decisions\n" + t3_items + "\n"
rc, out, err = run_hook(make_payload(t3_msg))
check("t3. 20 short (1-line) decision items, none over per-item budget -> QUIET", is_quiet(rc, out))

# t4. one item at exactly the per-item budget among several compliant items
# -> QUIET, and one item ONE line over -> ADVISORY naming that specific item
# (not a different one), proving per-item (not aggregate) measurement.
t4_msg = (
    IDENTITY_OK
    + "\n"
    + _status_slot_lines(3)
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
#    defect class named in the ticket. u3 (the fence-cap boundary,
#    FENCE_FREE_LINES/BASE_BODY_BUDGET) is likewise DELETED as of DS-171 -
#    both constants and the volume check that consumed them are gone. u4
#    below asserts the per-item-cap BOUNDARY, which still exists
#    (`_decision_item_sprawl_flag` is not retired), through the hook's
#    actual QUIET/ADVISORY output; the module is imported only to SIZE the
#    fixture precisely at the constant's current value, never to compare
#    an integer directly.
# ---------------------------------------------------------------------------

_spec = importlib.util.spec_from_file_location("enforce_turn_shape", HOOK_PATH)
_hook_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_hook_mod)

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
    # DS-155 round 3: flagged_msg must be something that reliably produces
    # an ADVISORY finding, not the bare "Done." these L. fixtures used
    # pre-DS-155 - "Done." was flagged by the now-fully-DELETED
    # identity-line check. DS-171: FLAGGED_STATUS_ONLY_MSG no longer
    # produces any finding at all (the status-only check it tripped is
    # retired) - swapped for FLAGGED_SPRAWL_MSG, which trips the sole
    # surviving advisory check (`_decision_item_sprawl_flag`). The
    # round-2-only scaffolding (_write_fake_git_branch calls) IS fully
    # reverted/removed here, per instruction - it existed solely to scope
    # that exemption.
    flagged_msg = FLAGGED_SPRAWL_MSG

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
    check("L2a. counter at 1/2 -> ADVISORY (fires, increments to 2)", is_advisory(rc, out, "operator-decisions item sprawl"))
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
    check("L3. new genuine user message (2>1) resets counter -> ADVISORY again", is_advisory(rc, out, "operator-decisions item sprawl"))

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
    check("L4c. after clean-turn reset -> ADVISORY again", is_advisory(rc, out, "operator-decisions item sprawl"))

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
# w. DS-155 answer-warrant transcript bonus (_transcript_answer_bonus).
#    A plain-prose reply with no quoted fragment and no other warrant must
#    satisfy the `answer` warrant (and so avoid the status-only flag) when
#    the operator's most recent GENUINE transcript message looks like a
#    direct question. Confirms the bonus is soft-fail (no question, no
#    transcript, or a non-genuine trailing message all fall back to
#    today's narrower behavior) and does NOT create an unbounded free-line
#    pool in the charge model.
# ---------------------------------------------------------------------------

PLAIN_PROSE_ANSWER = (
    IDENTITY_OK
    + "\nThe root cause is a stale cache entry keyed on mtime and size.\n"
    + "Clearing __pycache__ between runs fixes it.\n"
    + "No other change is needed.\n"
)
# PLAIN_PROSE_ANSWER averages exactly 8.0 words/unit (3 units, 24 words) -
# advisory-recall fix's second signal 2, `_status_only_prose_is_explanatory`.
# See w2/w3 below.

# Narrative-creep body (advisory-recall fix, w2b): ~3 words/unit, well below
# the 8.0 threshold - the shape signal 2 must NOT recall on, restoring what
# w2/w3 originally proved before signal 2 existed.
NARRATIVE_CREEP_BODY = (
    IDENTITY_OK
    + "\nFixed the bug.\n"
    + "Updated the doc.\n"
    + "Ran the tests.\n"
    + "Deployed the fix.\n"
)

# Boundary fixture (advisory-recall fix): pinned at exactly 7.9 words/unit
# (10 units, 79 words) - one word below PLAIN_PROSE_ANSWER's fragile exact
# 8.0, so a future text edit to either fixture cannot silently flip both
# across the threshold together.
BOUNDARY_PROSE_ANSWER = (
    IDENTITY_OK
    + "\nThe stale cache entry was keyed on mtime.\n"
    + "Clearing pycache between test runs fixes the issue.\n"
    + "No other structural change is actually needed here.\n"
    + "The fix is small and fully self contained.\n"
    + "Tests pass cleanly after the cache is cleared.\n"
    + "Nothing else in the pipeline needed adjustment today.\n"
    + "The root cause took a while to isolate.\n"
    + "Mutation testing confirmed the assertion catches it.\n"
    + "Docs did not need any updates this time.\n"
    + "This closes the ticket for the reported bug.\n"
)

with tempfile.TemporaryDirectory() as tmp_dir:
    # PLAIN_PROSE_ANSWER pin (advisory-recall fix, Skeptic Minor 2): this
    # constant sits at exactly _ANSWER_PROSE_AVG_WORDS_PER_SENTENCE
    # (8) words/unit (3 units, 24 words) - the same threshold signal 2 uses -
    # so a one-word edit to its text would silently flip w1/w2/w3 without
    # any assertion here ever failing. Pin the exact shape directly against
    # the module's own unit-splitting function so a future edit fails LOUDLY
    # here instead of silently changing what w1/w2/w3 actually test.
    _plain_units = _mod._answer_prose_units(_mod._body_after_identity_line(PLAIN_PROSE_ANSWER))
    _plain_total_words = sum(len(u.split()) for u in _plain_units)
    check(
        "PLAIN_PROSE_ANSWER pin: exactly 3 units / 24 words / 8.0 words-per-unit "
        "(sits exactly at the signal-2 threshold - w1/w2/w3 depend on this precise "
        "value; a text edit here must fail this assertion, not silently flip those)",
        (len(_plain_units), _plain_total_words) == (3, 24)
        and _plain_total_words / len(_plain_units) == 8.0,
    )

    # w1. Genuine last user message ends with "?" -> answer bonus granted,
    # plain-prose reply is QUIET (no status-only, under budget). Because
    # PLAIN_PROSE_ANSWER also independently satisfies signal 2 (8.0
    # words/unit, pinned above), the is_quiet() assertion below is
    # OVERDETERMINED - it would still pass with the bonus mechanism
    # stubbed to always return False, so it cannot by itself prove the
    # bonus fired. w1a pins the bonus mechanism directly (fails if the
    # bonus is disabled, unlike is_quiet() alone); corpus-replay
    # A1/A2 (see the corpus-replay gate further below, built on
    # NARRATIVE_CREEP_BODY - a body signal 2 does NOT recall) carry the
    # bonus's true differential QUIET/ADVISORY behavior end-to-end.
    question_transcript = _write_transcript(
        tmp_dir,
        [{"role": "user", "content": "Why did the cache test fail on the second run?"}],
    )
    check(
        "w1a. _transcript_answer_bonus fires directly on this transcript/text pair "
        "(non-vacuous: fails if the bonus mechanism is disabled, unlike w1 below)",
        _mod._transcript_answer_bonus(question_transcript, PLAIN_PROSE_ANSWER) is True,
    )
    rc, out, err = run_hook(
        json.dumps(
            {
                "last_assistant_message": PLAIN_PROSE_ANSWER,
                "transcript_path": question_transcript,
            }
        )
    )
    check(
        "w1. plain-prose reply to a genuine transcript question -> QUIET "
        "(overdetermined by signal 2 too - see w1a for the bonus-specific pin)",
        is_quiet(rc, out),
    )

    # w2. Same plain-prose reply, but the last genuine user message is a
    # STATEMENT (no "?") -> bonus withheld. PLAIN_PROSE_ANSWER averages
    # exactly 8.0 words/unit, so it now satisfies signal 2
    # (`_status_only_prose_is_explanatory`) independent of the transcript
    # bonus -> QUIET. (Advisory-recall fix: this fixture no longer proves
    # "the bonus does the work, not body shape" - w2b below restores that
    # original intent with a narrative-creep body signal 2 correctly
    # rejects.)
    statement_transcript = _write_transcript(
        tmp_dir,
        [{"role": "user", "content": "Go ahead and clear the cache between runs."}],
    )
    rc, out, err = run_hook(
        json.dumps(
            {
                "last_assistant_message": PLAIN_PROSE_ANSWER,
                "transcript_path": statement_transcript,
            }
        )
    )
    check(
        "w2. plain-prose reply (8.0 words/unit), transcript message is a statement -> "
        "QUIET (signal 2 recalls it independent of the transcript bonus)",
        is_quiet(rc, out),
    )

    # w2b. Companion to w2: narrative-creep body (~3 words/unit) with the
    # SAME statement (non-question) transcript -> signal 2 correctly
    # rejects it (average-words-per-unit stays below threshold) and the
    # transcript bonus is withheld (no question) -> still ADVISORY
    # (status-only). Restores what w2 originally proved before signal 2
    # existed: a terse, undeveloped body still nags regardless of body
    # shape being present at all.
    rc, out, err = run_hook(
        json.dumps(
            {
                "last_assistant_message": NARRATIVE_CREEP_BODY,
                "transcript_path": statement_transcript,
            }
        )
    )
    check(
        "w2b. narrative-creep body (~3 words/unit), statement transcript -> "
        "QUIET (DS-171: status-only check retired, so this is silent "
        "regardless of signal 2; kept as a regression pin that the "
        "bonus/signal-2 machinery itself is unaffected)",
        is_quiet(rc, out),
    )

    # w3. No transcript_path at all -> transcript bonus unavailable, but
    # PLAIN_PROSE_ANSWER's whole-body shape (8.0 words/unit) independently
    # satisfies signal 2 (`_status_only_prose_is_explanatory`) -> QUIET.
    # Pins signal 2 firing with NO transcript involved at all.
    rc, out, err = run_hook(json.dumps({"last_assistant_message": PLAIN_PROSE_ANSWER}))
    check(
        "w3. no transcript_path -> QUIET (signal 2 alone, no transcript bonus needed)",
        is_quiet(rc, out),
    )

    # w3b. Same no-transcript setup, but a narrative-creep body -> signal 2
    # does not recall it and there is no transcript bonus either -> stays
    # ADVISORY (status-only). Today's pre-fix behavior, preserved for a
    # body signal 2 correctly does not recognize as explanatory.
    rc, out, err = run_hook(json.dumps({"last_assistant_message": NARRATIVE_CREEP_BODY}))
    check(
        "w3b. no transcript_path, narrative-creep body -> QUIET (DS-171: "
        "status-only check retired)",
        is_quiet(rc, out),
    )

    # w3c. Boundary fixture pinned at exactly 7.9 words/unit (one word below
    # PLAIN_PROSE_ANSWER's fragile exact 8.0 threshold), no transcript ->
    # signal 2 must NOT recall it (avg_words >= 8 is False at 7.9) -> stays
    # ADVISORY (status-only).
    rc, out, err = run_hook(json.dumps({"last_assistant_message": BOUNDARY_PROSE_ANSWER}))
    check(
        "w3c. boundary body at 7.9 words/unit, no transcript -> QUIET "
        "(DS-171: status-only check retired)",
        is_quiet(rc, out),
    )

    # w4. A tool_result-only trailing "user" line (real CC transcripts record
    # every tool_result as type:"user") must NOT be mistaken for the
    # operator's question - loop_guard.last_genuine_user_text must skip it.
    tool_result_only_transcript = _write_transcript(
        tmp_dir,
        [
            {"role": "user", "content": "Why did the cache test fail on the second run?"},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "ok"}],
            },
        ],
    )
    rc, out, err = run_hook(
        json.dumps(
            {
                "last_assistant_message": PLAIN_PROSE_ANSWER,
                "transcript_path": tool_result_only_transcript,
            }
        )
    )
    check(
        "w4. trailing tool_result line does not mask an earlier genuine question -> QUIET",
        is_quiet(rc, out),
    )

    # w5. RETIRED (DS-171): this pinned that the transcript answer bonus
    # does not buy an unbounded free-line pool, via the now-deleted
    # ANSWER_BODY_BUDGET volume check. The volume rule now lives in the
    # `dinostack` output style, not this hook.

    # w6. REGRESSION (DS-155 round 2, Major 1 demonstrated repro): operator
    # asks a genuine question, then TWO intervening assistant TEXT turns
    # (a Waiting: turn, then a status-narration turn - mirroring "unit 1
    # merged, continuing with unit 2") happen, then the CURRENT turn is
    # pure narration (status-only, no warrant). Without the recency gate
    # this would incorrectly go QUIET under the now-stale original
    # question. The current turn's own text is NOT supplied via
    # last_assistant_message - it is pulled from the transcript tail (the
    # realistic Stop-time shape: the current turn's entry is already the
    # newest line on disk) so the recency scan sees exactly what a live
    # transcript would contain.
    stale_status_only = IDENTITY_OK + "\n" + _nlines(3, prefix="Note")
    stale_question_transcript = _write_transcript(
        tmp_dir,
        [
            {"role": "user", "content": "can you start on DS-155?"},
            {
                "role": "assistant",
                "content": IDENTITY_OK + "\nWaiting: engineer spawned, blocks merge.",
            },
            {
                "role": "user",
                "content": "<task-notification>Unit 1 complete</task-notification>",
            },
            {
                "role": "assistant",
                "content": IDENTITY_OK + "\nUnit 1 merged, continuing with unit 2.",
            },
            {"role": "assistant", "content": stale_status_only},
        ],
    )
    rc, out, err = run_hook(
        json.dumps({"last_assistant_message": "", "transcript_path": stale_question_transcript})
    )
    check(
        "w6. stale question (2 intervening assistant turns) -> QUIET (DS-171: "
        "status-only check retired; kept as a regression pin that the "
        "recency gate correctly withholds the bonus - w6a below pins the "
        "bonus directly)",
        is_quiet(rc, out),
    )
    check(
        "w6a. bonus withheld directly (_transcript_answer_bonus returns "
        "False for this stale-question transcript)",
        _mod._transcript_answer_bonus(stale_question_transcript, stale_status_only) is False,
    )

    # w6b. Companion positive control: IDENTICAL shape, but the current
    # turn is the IMMEDIATELY next assistant entry after the question (no
    # intervening assistant text turn - the harness-injected notification
    # does not count) -> the bonus IS granted -> QUIET. Proves w6 fails
    # because of staleness specifically, not because the transcript-tail
    # fallback path is broken.
    fresh_question_transcript = _write_transcript(
        tmp_dir,
        [
            {"role": "user", "content": "can you start on DS-155?"},
            {
                "role": "user",
                "content": "<task-notification>background check-in</task-notification>",
            },
            {"role": "assistant", "content": PLAIN_PROSE_ANSWER},
        ],
    )
    rc, out, err = run_hook(
        json.dumps({"last_assistant_message": "", "transcript_path": fresh_question_transcript})
    )
    check(
        "w6b. same question, NO intervening assistant turn -> QUIET (bonus granted)",
        is_quiet(rc, out),
    )

    # w7. REGRESSION (DS-155 round 2, Major 1 second half): the stale-
    # question leak also affected _forced_yield_flag, not just
    # _status_only_flag - a malformed Waiting: turn (extra prose beside
    # the Waiting: line, no other warrant) must still be flagged even
    # under a stale question, since the answer bonus must not paper over
    # a genuinely malformed forced-yield shape.
    stale_forced_yield = (
        IDENTITY_OK
        + "\nSome unrelated explanation sentence here.\n"
        + "Waiting: operator approval to proceed.\n"
    )
    stale_fy_transcript = _write_transcript(
        tmp_dir,
        [
            {"role": "user", "content": "can you start on DS-155?"},
            {
                "role": "assistant",
                "content": IDENTITY_OK + "\nWaiting: engineer spawned, blocks merge.",
            },
            {"role": "assistant", "content": stale_forced_yield},
        ],
    )
    rc, out, err = run_hook(
        json.dumps({"last_assistant_message": "", "transcript_path": stale_fy_transcript})
    )
    check(
        "w7. stale question does not mask a malformed sole-stoppage turn -> "
        "BLOCKING (DS-156)",
        is_blocking(rc, out, "sole-stoppage"),
    )

    # w8. REGRESSION (DS-155 round 4, Major fix - supersedes the round-3
    # version of this test, which hand-built a SAME-ENTRY mixed
    # [text, tool_use] array; corpus measurement (see
    # hooks/tests/fixtures/turn-shape-corpus-samples.json) found that
    # shape occurs 4 times in 169,745 real assistant entries (0.002%) and
    # is NOT what real transcripts actually do). This fixture instead uses
    # a REAL corpus-derived SEPARATE-entry span: thinking -> tool_use ->
    # tool_result -> text (sample-3, the simplest span containing the
    # pure-text-immediately-before-a-SEPARATE-tool_use pattern measured
    # 30,027 times). A genuine fresh answer turn with this real shape must
    # be QUIET, identical to the same final answer text delivered as a
    # single entry with no scaffolding at all.
    text_then_tool_transcript = _write_transcript(
        tmp_dir,
        [
            {"role": "user", "content": "Why did the cache test fail?"},
            {"role": "assistant", "content": [{"type": "thinking", "thinking": "Let me check the log."}]},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "log output"}],
            },
            {"role": "assistant", "content": PLAIN_PROSE_ANSWER},
        ],
    )
    rc, out, err = run_hook(
        json.dumps({"last_assistant_message": "", "transcript_path": text_then_tool_transcript})
    )
    check(
        "w8. corpus-derived split-entry (thinking->tool_use->tool_result->text) -> QUIET (not a false intervening turn)",
        is_quiet(rc, out),
    )

    # w8b. REGRESSION (DS-155 round 4): the SPLIT-entry shape this fix
    # actually targets - a PURE-TEXT entry immediately followed by a
    # SEPARATE tool_use entry (not merged into one array). This is the
    # shape round 3's same-entry-only check could never catch (measured
    # 30,027 times in the corpus vs. 4 same-entry occurrences) and is the
    # literal ticket symptom: the model narrates in plain text, THEN
    # separately calls a tool, then answers.
    split_text_then_tool_transcript = _write_transcript(
        tmp_dir,
        [
            {"role": "user", "content": "Why did the cache test fail?"},
            {"role": "assistant", "content": [{"type": "text", "text": "Let me check the log."}]},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t1", "name": "Bash", "input": {}}],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "log output"}],
            },
            {"role": "assistant", "content": PLAIN_PROSE_ANSWER},
        ],
    )
    rc, out, err = run_hook(
        json.dumps(
            {"last_assistant_message": "", "transcript_path": split_text_then_tool_transcript}
        )
    )
    check(
        "w8b. pure-text entry immediately followed by a SEPARATE tool_use entry -> QUIET",
        is_quiet(rc, out),
    )

    # w9. REGRESSION (DS-155 round 3, Minor fix - the mirror image of w8):
    # when the CURRENT turn's own assistant entry is NOT yet on disk at
    # Stop time (last_assistant_message supplied directly and does NOT
    # match anything in the transcript), the one genuinely earlier
    # completed turn in the transcript must NOT be silently skipped as if
    # it were "this turn's own entry" - the question is stale-by-one and
    # must be correctly detected.
    stale_by_one_transcript = _write_transcript(
        tmp_dir,
        [
            {"role": "user", "content": "can you start on DS-155?"},
            {
                "role": "assistant",
                "content": IDENTITY_OK + "\nWaiting: engineer spawned, blocks merge.",
            },
        ],
    )
    rc, out, err = run_hook(
        json.dumps(
            {
                "last_assistant_message": stale_status_only,
                "transcript_path": stale_by_one_transcript,
            }
        )
    )
    check(
        "w9. current turn's own entry not yet on disk -> QUIET (DS-171: "
        "status-only check retired; kept as a regression pin that the "
        "staleness classification itself is unaffected)",
        is_quiet(rc, out),
    )

    # w10. REGRESSION (DS-155 round 4): the tool_use-pending flag must be
    # scoped to AT MOST ONE preceding text entry, not leak forward and
    # excuse an EARLIER, genuinely separate completed turn that has no
    # tool_use of its own. Shape: [Q] [turn A - a genuinely separate
    # completed pure-text turn, no tool_use] [turn B's own pre-tool
    # narration] [turn B's tool_use] [tool_result] [turn B's final answer
    # = CURRENT]. Turn A must still be detected as an intervening turn
    # (ADVISORY) even though a tool_use exists later in the same window -
    # that tool_use belongs to turn B's own narration step, not to turn A.
    scoping_transcript = _write_transcript(
        tmp_dir,
        [
            {"role": "user", "content": "can you start on DS-155?"},
            {
                "role": "assistant",
                "content": "genuinely separate turn A final message, no tool use here",
            },
            {"role": "assistant", "content": "Let me check something before answering."},
            {
                "role": "assistant",
                "content": [{"type": "tool_use", "id": "t2", "name": "Bash", "input": {}}],
            },
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": "t2", "content": "ok"}],
            },
            # NARRATIVE_CREEP_BODY (not PLAIN_PROSE_ANSWER, advisory-recall
            # fix): this test proves the transcript-derived staleness
            # scoping, not body shape - PLAIN_PROSE_ANSWER's 8.0 words/unit
            # would independently satisfy signal 2 regardless of staleness
            # and collapse this assertion to QUIET for the wrong reason.
            {"role": "assistant", "content": NARRATIVE_CREEP_BODY},
        ],
    )
    rc, out, err = run_hook(
        json.dumps({"last_assistant_message": "", "transcript_path": scoping_transcript})
    )
    check(
        "w10. tool_use attribution is scoped to ONE preceding text entry, not the whole window "
        "-> QUIET (DS-171: status-only check retired; kept as a "
        "regression pin that turn A is still detected as intervening)",
        is_quiet(rc, out),
    )

    # ---------------------------------------------------------------------
    # CORPUS-REPLAY GATE (DS-155 round 5, Major 2 - structural requirement,
    # not optional). Fixtures MUST be corpus-derived, not hand-assumed:
    # this replays every sample in
    # hooks/tests/fixtures/turn-shape-corpus-samples.json - real assistant/
    # tool-result entry SHAPES, INCLUDING message.id sharing structure
    # (relabeled opaque placeholders, not real ids - see the fixture's own
    # "_purpose" note), STRATIFIED BY SHAPE CLASS (single_direct,
    # own_message_split, genuinely_separate, deep_chain - see the
    # fixture's "_measurement.shape_classes_covered") rather than by raw
    # assistant-entry count. Round 4's count-stratified sampling covered
    # the genuinely_separate class in only 2 of 8 samples and asserted
    # QUIET on every sample - structurally blind to the over-permissive
    # ADVISORY direction, which is the direction ALL of round 4's 43 real
    # corpus mismatches ran. This gate now asserts each sample's OWN
    # `expected` verdict (quiet or advisory), covering both directions.
    # Verified (see the round-5 commit message) to reproduce the expected
    # direction against BOTH round 3 (1e31bbd9: mismatches B1/B2, the
    # split-entry shape it never learned) and round 4 (69ef2e7a: mismatches
    # C1, the genuinely-separate-turn shape its positional-only rule
    # over-exempts).
    # ---------------------------------------------------------------------

    _FIXTURES_PATH = os.path.join(os.path.dirname(__file__), "fixtures", "turn-shape-corpus-samples.json")
    with open(_FIXTURES_PATH, "r", encoding="utf-8") as _f:
        _corpus_fixture = json.load(_f)

    def _build_synthetic_span_entry(block_types: list, message_id, tool_id_box: list) -> dict:
        """Build a synthetic (content-free) transcript entry matching the
        given block-type sequence and message.id. Never embeds any real
        corpus content - every string here is a fixed synthetic
        placeholder; `message_id` is the fixture's own relabeled opaque
        placeholder (e.g. "m1"), never a real API-issued id."""
        blocks = []
        for bt in block_types:
            if bt == "text":
                blocks.append({"type": "text", "text": "Synthetic scaffolding narration before continuing."})
            elif bt == "thinking":
                blocks.append({"type": "thinking", "thinking": "Synthetic internal reasoning."})
            elif bt == "tool_use":
                tool_id_box[0] += 1
                blocks.append(
                    {"type": "tool_use", "id": f"synthetic-tool-{tool_id_box[0]}", "name": "Bash", "input": {}}
                )
            elif bt == "tool_result":
                blocks.append(
                    {
                        "type": "tool_result",
                        "tool_use_id": f"synthetic-tool-{tool_id_box[0]}",
                        "content": "synthetic tool output",
                    }
                )
            else:
                blocks.append({"type": bt})
        entry = {"content": blocks}
        if message_id is not None:
            entry["message"] = {"id": message_id}
        return entry

    def _build_corpus_replay_transcript(tmp_dir_inner: str, sample: dict, final_answer_text: str) -> str:
        tool_id_box = [0]
        lines = [
            {
                "role": "user",
                "content": "Synthetic operator question derived from a real corpus span shape?",
            }
        ]
        span = sample["span"]
        for i, entry_spec in enumerate(span):
            is_last_final_text = (
                i == len(span) - 1
                and entry_spec["role"] == "assistant"
                and entry_spec["block_types"] == ["text"]
            )
            message_id = entry_spec.get("message_id")
            if is_last_final_text:
                built = {"role": "assistant", "content": [{"type": "text", "text": final_answer_text}]}
                if message_id is not None:
                    built["message"] = {"id": message_id}
            else:
                built = _build_synthetic_span_entry(entry_spec["block_types"], message_id, tool_id_box)
                built["role"] = entry_spec["role"]
            lines.append(built)
        return _write_transcript(tmp_dir_inner, lines)

    # Advisory-recall fix: this gate exists to test the TRANSCRIPT-derived
    # staleness classification (_has_intervening_assistant_turn), not body
    # shape or hook-level advisory posture. NARRATIVE_CREEP_BODY (not
    # PLAIN_PROSE_ANSWER) is used as the final answer text so signal 2
    # (the retired `_status_only_prose_is_explanatory`) never independently
    # recalls it either way.
    #
    # DS-171: previously this asserted the hook's QUIET/ADVISORY(status-
    # only) posture, which distinguished "bonus granted" from "bonus
    # withheld" only because the withheld case fell through to the
    # (now-retired) status-only advisory. With that advisory gone, both
    # outcomes at the hook level would be QUIET regardless of the bonus,
    # which would make this gate vacuous - so it now asserts
    # `_transcript_answer_bonus` directly, which is the actual signal this
    # gate exists to protect and is unaffected by DS-171.
    for _sample in _corpus_fixture["samples"]:
        _replay_transcript = _build_corpus_replay_transcript(tmp_dir, _sample, NARRATIVE_CREEP_BODY)
        _expect_bonus = _sample["expected"] == "quiet"
        _bonus_granted = _mod._transcript_answer_bonus(_replay_transcript, NARRATIVE_CREEP_BODY)
        check(
            f"corpus-replay {_sample['id']} ({_sample['shape_class']}) -> "
            f"answer bonus {'GRANTED' if _expect_bonus else 'WITHHELD'} (expected)",
            _bonus_granted == _expect_bonus,
        )


# ---------------------------------------------------------------------------
# DS-156. Required §9 hook-contract coverage: _execution_prose_flag
# (BLOCKING), STATUS_LINE_MAX_CHARS, and the false-positive discipline the
# module docstring's governing principle demands (a guard that fires on
# correct, fully-warranted turns is worse than no hook at all).
# DS-171: `_answer_relevance_flag`/ANSWER_BODY_BUDGET coverage below is
# retired along with the check itself - the relevance/volume rules now
# live in the `dinostack` output style, not this hook.
# ---------------------------------------------------------------------------

# n3. log_fire() logs decision='deny' (not 'allow_advisory') on a
# BLOCKING _execution_prose_flag finding.
_calls_deny: list = []
_deny_msg = IDENTITY_OK + "\nSome narrative sentence.\n\n## Operator decisions\n- Proceed with X (Recommended)\n"
_out_deny = _run_main_with_stdin(make_payload(_deny_msg), _calls_deny)
check(
    "n3. log_fire called with decision='deny' on a BLOCKING finding",
    len(_calls_deny) == 1
    and _calls_deny[0][0] == "enforce-turn-shape"
    and _calls_deny[0][1] == "deny",
)
check(
    "n3b. main() emits {\"decision\": \"block\", ...} on the same input via the module import path",
    json.loads(_out_deny).get("decision") == "block",
)

# ds156-a. Answer turn with a long, substantive body -> QUIET, proving
# length alone does not charge - DS-171 (the volume check that produced
# this proof is retired; a hook-level advisory can no longer fire on
# length at all, which is a strictly stronger version of the same claim).
ds156_a_msg = (
    IDENTITY_OK
    + '\n"The root cause is a stale cache entry keyed on mtime and size."\n'
    + _nlines(15, prefix="Supporting detail")
)
rc, out, err = run_hook(make_payload(ds156_a_msg))
check("ds156-a. answer turn, 16-line substantive body -> QUIET (length alone does not charge)", is_quiet(rc, out))

# ds156-b/ds156-c (relevance bans 2/5 on an Answer turn): RETIRED (DS-171).
# `_answer_relevance_flag` and the `_OPENING_FILLER_RE`/`_CLOSING_RECAP_RE`
# phrase lists it consumed are deleted - the relevance rule now lives in
# the `dinostack` output style. See hooks/enforce-turn-shape.py's Purpose
# section.

# ds156-d. Answer+Decision combo: prose above, '## Operator decisions'
# last -> QUIET, proving the precedence rule (Answer always wins the
# shape question, so the prose above the heading is never shape-checked).
ds156_d_msg = (
    IDENTITY_OK
    + '\n"Yes, PR #612 is ready to merge - CI is green and sign-off is in."\n'
    + "\n## Operator decisions\n1. Merge PR #612 (Recommended) - all checks passing. Reply STOP to hold.\n"
)
rc, out, err = run_hook(make_payload(ds156_d_msg))
check(
    "ds156-d. Answer+Decision combo, prose above and decisions last -> QUIET "
    "(Answer wins the shape question)",
    is_quiet(rc, out),
)

# ds156-e. Decision-only turn with one narrative sentence beyond the
# structured slots -> BLOCKING. This is the core regression test for the
# operator's founding complaint - already pinned above as case "d", but
# restated here under its own name per the spec's explicit test list.
ds156_e_msg = (
    IDENTITY_OK
    + "\nState: unit 2 merged, unit 3 in review.\n"
    + "One more thing worth mentioning here that is not a status slot.\n"
    + "\n## Operator decisions\n1. Merge unit 3 (Recommended) - CI green. Reply STOP to hold.\n"
)
rc, out, err = run_hook(make_payload(ds156_e_msg))
check(
    "ds156-e. decision-only turn, one narrative sentence beyond the "
    "structured slots -> BLOCKING",
    is_blocking(rc, out, "unrecognized line in the status region"),
)

# ds156-f. Sole-stoppage turn: a Waiting: line plus a FENCED narrative
# aside -> still flagged, proving the sole-stoppage domain is the raw
# RAW-line domain (fence-blind), not the fence-aware status region.
ds156_f_msg = (
    IDENTITY_OK
    + "\nWaiting: engineer - unit 3 review.\n"
    + "```\nAn aside, fenced, that is still not a Waiting: line.\n```\n"
)
rc, out, err = run_hook(make_payload(ds156_f_msg))
check(
    "ds156-f. sole-stoppage turn, Waiting: line + FENCED narrative aside -> "
    "BLOCKING (fence-blind raw-line domain)",
    is_blocking(rc, out, "sole-stoppage"),
)

# ds156-g. Execution turn whose State: line exceeds STATUS_LINE_MAX_CHARS
# (200) -> flagged.
ds156_g_msg = IDENTITY_COMPLETE + "\nState: " + ("x" * 210) + "\n"
rc, out, err = run_hook(make_payload(ds156_g_msg))
check(
    "ds156-g. execution turn, State: line over 200 chars -> BLOCKING",
    is_blocking(rc, out, "status slot line is"),
)

# ds156-h. Execution turn whose POSITION-1 (identity) line exceeds
# STATUS_LINE_MAX_CHARS (200) -> flagged, on BOTH branches.
ds156_h_general_msg = (
    "unit-1 · " + ("x" * 210) + " · [phase: complete]\nState: done.\n"
)
rc, out, err = run_hook(make_payload(ds156_h_general_msg))
check(
    "ds156-h1. general branch: identity line over 200 chars -> BLOCKING",
    is_blocking(rc, out, "identity line is"),
)

ds156_h_sole_msg = (
    "unit-1 · " + ("x" * 210) + " · [phase: implement]\nWaiting: engineer - unit 3.\n"
)
rc, out, err = run_hook(make_payload(ds156_h_sole_msg))
check(
    "ds156-h2. sole-stoppage branch: identity line over 200 chars -> BLOCKING",
    is_blocking(rc, out, "identity line is"),
)

# ds156-i. A 140-char Waiting: line on a sole-stoppage turn -> NOT flagged
# by the shape check (WAITING_LINE_MAX_CHARS is a volume-check-only bound,
# never imported into the shape check).
ds156_i_msg = IDENTITY_OK + "\nWaiting: " + ("y" * 135) + "\n"
rc, out, err = run_hook(make_payload(ds156_i_msg))
check(
    "ds156-i. 140-char Waiting: line, sole-stoppage turn -> QUIET (no length "
    "bound on Waiting: lines in the shape check)",
    is_quiet(rc, out),
)

# ds156-i2. A 140-char Waiting: line on a GENERAL-branch turn (decision
# present alongside stoppage) -> also NOT flagged by the shape check. Same
# WAITING_LINE_MAX_CHARS-is-volume-only rule as ds156-i, pinned separately
# because the general branch (hooks/enforce-turn-shape.py's status-region
# `_WAITING_LINE_RE.match(line): continue`) is a DIFFERENT code path from
# the sole-stoppage branch ds156-i exercises, and had no regression pin of
# its own (Skeptic Minor, round 1 finding).
ds156_i2_msg = (
    IDENTITY_OK
    + "\nWaiting: " + ("z" * 135) + "\n"
    + "\n## Operator decisions\n1. Merge unit 3 (Recommended) - CI green. Reply STOP to hold.\n"
)
rc, out, err = run_hook(make_payload(ds156_i2_msg))
check(
    "ds156-i2. 140-char Waiting: line, general branch (decision present) "
    "-> QUIET (no length bound on Waiting: lines in the shape check)",
    is_quiet(rc, out),
)

# ---------------------------------------------------------------------------
# False-positive discipline (mandatory pre-completion adversarial check,
# per the spawn brief): the legitimate turns most likely to trip
# _execution_prose_flag must pass.
# ---------------------------------------------------------------------------

# fp1. A multi-ticket State: line (long but under 200 chars, compliant shape).
fp1_msg = (
    IDENTITY_OK
    + "\nState: DS-140 unit 2 merged, DS-141 unit 1 in review, DS-142 blocked on credentials.\n"
)
rc, out, err = run_hook(make_payload(fp1_msg))
check("fp1. multi-ticket State: line -> QUIET", is_quiet(rc, out))

# fp2. A long branch name in the identity line (under 200 chars) -> QUIET.
fp2_msg = (
    "DS-156 · fix/ds-156-turn-shape-hook-implementation-with-a-fairly-long-descriptive-name · [phase: implement]\n"
    + "State: engineer spawned, awaiting result.\n"
)
rc, out, err = run_hook(make_payload(fp2_msg))
check("fp2. long (but compliant-length) branch name in identity line -> QUIET", is_quiet(rc, out))

# fp3. Forced-yield turn with many Waiting: lines (already pinned as
# s10/s10c above; restated here under the false-positive-discipline name).
fp3_msg = IDENTITY_OK + "\n" + "\n".join(f"Waiting: agent-{i} - unit {i} review." for i in range(1, 8)) + "\n"
rc, out, err = run_hook(make_payload(fp3_msg))
check("fp3. forced-yield turn with 7 Waiting: lines -> QUIET", is_quiet(rc, out))

# fp4. Answer+Decision combo (restated here under the false-positive-
# discipline name; already pinned above as ds156-d).
rc, out, err = run_hook(make_payload(ds156_d_msg))
check("fp4. Answer+Decision combo -> QUIET", is_quiet(rc, out))

# ---------------------------------------------------------------------------
# y. DS-157: RETIRED (DS-171). This section tested
#    `_has_body_completion_declaration`, which suppressed the status-only
#    ADVISORY on a genuine body-paragraph completion declaration. Both
#    the function and the status-only check it fed are deleted - see
#    hooks/enforce-turn-shape.py's Purpose section. The blocking-path
#    safety property this section also verified (a body completion
#    declaration must never grant the `completion` WARRANT) remains
#    covered directly via `_classify_warrants` in section z below (z4b/
#    z4c/z4d), which tests that property without depending on the
#    retired function.
# ---------------------------------------------------------------------------
# z. DS-159: identity-line TRAILING bare completion sentence used to
#    suppress the status-only ADVISORY without granting the `completion`
#    WARRANT (same posture as DS-157's y-block above, for the sibling gap
#    where the completion is the identity line's own second sentence, not
#    the body's first paragraph). DS-171: the status-only check and its
#    suppression helper (formerly documented in
#    _identity_line_trailing_completion's docstring) are RETIRED - see
#    hooks/enforce-turn-shape.py's Purpose section. The blocking-path safety
#    property this section verifies (a trailing bare-completion sentence
#    must never grant the `completion` WARRANT) is unaffected by that
#    retirement and remains checked directly via _classify_warrants below.
# ---------------------------------------------------------------------------

# z1. The reported symptom, reproduced verbatim: identity line "All three
# shipped. Done." does NOT match _LEADING_COMPLETION_RE at position 0 (the
# `\A` anchor never scans past "All three shipped." to reach the second
# sentence "Done."), and the first BODY paragraph is a markdown table, not
# prose. Pre-DS-171 this also missed the now-deleted
# _has_body_completion_declaration's DS-157 body-paragraph check; post-
# DS-171 the status-only check itself is gone, so the turn is QUIET
# regardless of that mechanism. Must be QUIET (was ADVISORY pre-fix, still
# QUIET post-DS-171 retirement).
z1_msg = (
    "All three shipped. Done.\n"
    "\n"
    "| ticket | what landed |\n"
    "|---|---|\n"
    "| **DS-156** | Conductor turn shape bound to warrant. |\n"
    "| **DS-157** | Body-paragraph completion detection. |\n"
)
rc, out, err = run_hook(make_payload(z1_msg))
check(
    "z1. DS-159 reported symptom - identity line's SECOND sentence is a "
    "bare completion declaration, first body paragraph is a table -> "
    "QUIET (was ADVISORY pre-fix)",
    is_quiet(rc, out),
)

# z2. REGRESSION (measured false positive, non-bare trailing sentence):
# "Both mechanical fixes are done." as a MIDDLE sentence followed by "Now
# finalizing..." on the same identity line must NOT be recognised - the
# bare-word-only shape (_BARE_TRAILING_COMPLETION_RE) requires the FINAL
# sentence to be nothing but the completion word itself, and this sentence
# both has extra leading words ("Both mechanical fixes are") and is not
# the identity line's last sentence.
z2_msg = (
    "PR pushed successfully. Both mechanical fixes are done. Now "
    "finalizing state files and the run summary.\n"
    "\n"
    "Extra detail line one.\n"
    "Extra detail line two.\n"
    "Extra detail line three.\n"
)
rc, out, err = run_hook(make_payload(z2_msg))
check(
    "z2. non-bare, non-final trailing sentence ('Both mechanical fixes "
    "are done. Now finalizing...') is NOT suppressed -> QUIET (DS-171: "
    "status-only check retired, so this is now silent regardless; kept "
    "as a regression pin that no code path re-derives a completion "
    "warrant from this shape)",
    is_quiet(rc, out),
)

# z3. REGRESSION (measured false positive, partial-word absorption): "Status
# while it completes:" would match _LEADING_COMPLETION_RE.match (the regex's
# optional trailing-word group silently absorbs the "s" in "completes"
# before the terminal ":"). Pre-DS-171 the now-deleted
# _BARE_TRAILING_COMPLETION_RE's closed single-word vocabulary correctly
# rejected it as a suppression trigger - "completes" is not "complete"/
# "completed"/"done"/"finished". Post-DS-171 the status-only check that
# consumed that regex is gone, so the turn is QUIET regardless of that
# mechanism; kept as a regression pin on the underlying `completion`
# classification, not on the deleted regex.
z3_msg = (
    "Validation still running. Status while it completes:\n"
    "\n"
    "Wave 1 complete: 63 components authored.\n"
    "Extra detail line one.\n"
    "Extra detail line two.\n"
)
rc, out, err = run_hook(make_payload(z3_msg))
check(
    "z3. 'Status while it completes:' (partial-word, not a bare "
    "completion token) is NOT suppressed -> QUIET (DS-171: status-only "
    "check retired, so this is now silent regardless; kept as a "
    "regression pin on the underlying classification)",
    is_quiet(rc, out),
)

# z4. BLOCKING-PATH SAFETY REGRESSION (this ticket's central concern,
# mirrors y6 above): the z1 shape must NEVER grant the `completion`
# WARRANT. DS-171: z4a (which pinned `_has_body_completion_declaration(
# z1_msg) is True` as the precondition for z4b/z4c) is DELETED along with
# that retired function - see hooks/enforce-turn-shape.py's Purpose
# section. z4b/z4c/z4d below test `_classify_warrants`/
# `_execution_prose_flag` directly and are unaffected.
_z1_warrants = _mod._classify_warrants(z1_msg)
check(
    "z4b. the `completion` warrant key is NOT granted for the z1 fixture",
    _z1_warrants["completion"] is False,
)
# z4c REVISED (markup-blindspot fix, real-corpus turn_0314): the ORIGINAL
# z1_msg's table-shaped first body paragraph is no longer proof of
# blocking-path danger, because this fix's table-row exemption (see
# _TABLE_ROW_RE) makes a synthetic completion=True grant for that EXACT
# shape now return None (quiet) - the table rows are all recognized
# structure now, not unrecognized prose. See z4d below for that changed
# outcome pinned directly. The underlying "do not widen the completion
# warrant" conclusion still holds for content this fix does not touch:
# re-targeted at a non-table (bulleted-list) variant of the same z1
# identity line, matching the bulleted-detail shape
# _has_body_completion_declaration's own docstring names as a confirmed
# true positive (see also y6c above, whose bulleted-list body already
# demonstrates the same still-live danger).
_z4c_bullet_msg = (
    "All three shipped. Done.\n"
    "\n"
    "- Killed any dev servers still running from testing.\n"
    "- Removed both agent worktrees.\n"
    "- Confirmed the branch is deleted upstream.\n"
)
_z4c_warrants = _mod._classify_warrants(_z4c_bullet_msg)
_z4c_warrants_if_granted = dict(_z4c_warrants)
_z4c_warrants_if_granted["completion"] = True
check(
    "z4c. _execution_prose_flag BLOCKS a non-table (bulleted-list) "
    "variant of the z1 identity line under a synthetic completion=True "
    "warrant dict - shows the general danger z4b's fix must NOT widen "
    "the warrant into still holds for content the table-row exemption "
    "does not cover",
    _mod._execution_prose_flag(_z4c_bullet_msg, _z4c_warrants_if_granted) is not None,
)
# z4d. Direct pin of the table-exemption's effect on the ORIGINAL z1
# shape: a synthetic completion=True grant no longer blocks it, because
# every line of its first body paragraph is a recognized table row.
_z1_warrants_if_granted = dict(_z1_warrants)
_z1_warrants_if_granted["completion"] = True
check(
    "z4d. _execution_prose_flag does NOT block the z1 fixture under a "
    "synthetic completion=True warrant dict now that its table body is "
    "recognized structure (contrast with z4c's bulleted-list variant, "
    "which still blocks)",
    _mod._execution_prose_flag(z1_msg, _z1_warrants_if_granted) is None,
)

# ---------------------------------------------------------------------------
# DS-158: two operator-reported false positives on the execution-prose
# check, plus the discriminator's regression coverage.
# ---------------------------------------------------------------------------

# ds158-a. FALSE POSITIVE A (operator report): identity line + well-formed
# State:/Running:/Blocked: slot lines + one genuine multi-sentence
# answer/explanation paragraph + a completion warrant -> was BLOCKING
# pre-fix, must be ADVISORY (downgraded) post-fix, never QUIET (the
# unrecognized content is still flagged, just not as a hard block).
ds158_a_msg = (
    IDENTITY_COMPLETE + "\n"
    "State: implementing.\n"
    "Running: none.\n"
    "Blocked: none.\n"
    "The reason the guard misfires here is that the status-region prose "
    "classifier treats the entire body as the status region regardless "
    "of warrant type. Any explanatory paragraph placed there trips the "
    "unrecognized-line check even though it is genuinely part of the "
    "answer the operator asked for, which is exactly the false positive "
    "this fix addresses.\n"
)
rc, out, err = run_hook(make_payload(ds158_a_msg))
check(
    "ds158-a. status slot lines + a genuine multi-sentence explanation "
    "paragraph, completion warrant -> ADVISORY (downgraded), not BLOCKING",
    is_advisory(rc, out, "downgraded to advisory"),
)
check(
    "ds158-a2. same fixture is NOT blocking",
    not is_blocking(rc, out),
)

# ds158-b. FALSE POSITIVE B (operator report): a Waiting: line combined
# with plain, well-formed State:/Running:/Blocked: lines -> was BLOCKING
# pre-fix via the sole-stoppage branch's Waiting:-only requirement, must
# be QUIET post-fix.
ds158_b_msg = (
    IDENTITY_OK + "\n"
    "State: implementing unit 2.\n"
    "Running: unit 2 build.\n"
    "Blocked: none.\n"
    "Waiting: operator sign-off on the plan.\n"
)
rc, out, err = run_hook(make_payload(ds158_b_msg))
check(
    "ds158-b. sole-stoppage turn, Waiting: line + well-formed status slot "
    "lines -> QUIET",
    is_quiet(rc, out),
)

# ds158-c. sole-stoppage branch still BLOCKS a genuinely unrecognized line
# (not a slot line, not a Waiting: line) alongside a Waiting: line -
# proves the widening in ds158-b is scoped to recognized slot lines, not
# a blanket pass.
ds158_c_msg = (
    IDENTITY_OK + "\n"
    "State: implementing unit 2.\n"
    "Some free-floating narrative aside that is not a recognized slot.\n"
    "Waiting: operator sign-off on the plan.\n"
)
rc, out, err = run_hook(make_payload(ds158_c_msg))
check(
    "ds158-c. sole-stoppage turn, Waiting: + status slot + one genuinely "
    "unrecognized line -> still BLOCKING",
    is_blocking(rc, out, "sole-stoppage"),
)

# ds158-d. narrative-creep MUST still BLOCK: re-confirms s5c-b's verdict
# directly against the new tuple-returning _execution_prose_flag, proving
# the discriminator does not make everything advisory. Same fixture as
# s5c-b above.
ds158_d_msg = (
    IDENTITY_COMPLETE + "\n"
    "Merged the fix for the turn-shape gate regression into main.\n"
    + _nlines(7, prefix="Also did thing")
)
rc, out, err = run_hook(make_payload(ds158_d_msg))
check(
    "ds158-d. narrative-creep (many short templated pings) -> still "
    "BLOCKING, not downgraded",
    is_blocking(rc, out, "unrecognized line in the status region"),
)
check(
    "ds158-d2. narrative-creep finding is NOT tagged 'downgraded to "
    "advisory'",
    "downgraded to advisory" not in parse_output(out).get("reason", ""),
)

# ds158-e. _is_answer_shaped_prose unit coverage. DS-159: the
# multi-sentence floor moved OUT of this function into
# _execution_prose_flag's whole-turn aggregate (see ds156-e above, still
# BLOCKING end-to-end - the live regression this function no longer
# guards alone). _is_answer_shaped_prose itself now checks ONLY the
# average-words-per-unit condition, per block.
check(
    "ds158-e1 (DS-159 REVISED). a single 12-word sentence's own PER-BLOCK "
    "average clears the words threshold (12 words / 1 unit >= 8) - IS "
    "answer-shaped at the per-block level; the multi-sentence floor that "
    "still blocks ds156-e's identical sentence end-to-end now lives in "
    "_execution_prose_flag's whole-turn aggregate, not here",
    _mod._is_answer_shaped_prose(
        "One more thing worth mentioning here that is not a status slot."
    )
    is True,
)
check(
    "ds158-e2. two short templated sentences (well under the "
    "words-per-sentence average) are NOT answer-shaped",
    _mod._is_answer_shaped_prose("Also did thing 1. Also did thing 2.") is False,
)
check(
    "ds158-e3. two genuinely developed sentences (over the "
    "words-per-sentence average) ARE answer-shaped",
    _mod._is_answer_shaped_prose(
        "This is a genuinely developed explanatory sentence with real "
        "content in it. Here is a second one that also carries real "
        "explanatory weight and detail."
    )
    is True,
)
check(
    "ds158-e4. empty text is NOT answer-shaped",
    _mod._is_answer_shaped_prose("") is False,
)

# ---------------------------------------------------------------------------
# DS-158 round 2 (Skeptic Major 1 - laundering bypass; residual
# false-positive rate). Round 1's _is_answer_shaped_prose classified the
# WHOLE status region as one joined blob, so a single developed paragraph
# anywhere in the region could downgrade an arbitrarily large,
# NON-ADJACENT narrative-creep sprawl riding alongside it. Round 2
# classifies PER CONTIGUOUS BLOCK instead (a recognized slot/Waiting:
# line, or a fence, breaks contiguity) and blocks unless EVERY block
# passes the discriminator.
# ---------------------------------------------------------------------------

_creep8_lines = ["Also did thing {}.".format(i) for i in range(1, 9)]
_pad_lines = [
    "This is a genuinely developed explanatory sentence with real "
    "content in it, written the way a real conductor answer to a real "
    "operator question would actually read, at real length.",
    "Here is a second one that also carries real explanatory weight "
    "and detail, deliberately long enough that its own average pulls "
    "a mixed contiguous block above the answer-shaped threshold.",
    "And a third one, for the same reason, so the combined contiguous "
    "block's average genuinely clears the discriminator on its own "
    "arithmetic merits rather than by a hand-tuned coincidence.",
]

# ds158-f. THE LAUNDERING BYPASS FIXTURE (Skeptic Major 1's exact repro
# shape): creep8 (narrative-creep, fails the discriminator alone) plus a
# genuine answer-shaped pad paragraph, separated by a recognized State:
# line - two DIFFERENT, NON-CONTIGUOUS blocks. Round 1 flattened both
# into one union and the pad's high word average laundered the creep8
# block to advisory; round 2 classifies each block independently, so the
# creep8 block alone still fails and the whole finding stays BLOCKING.
ds158_f_msg = (
    IDENTITY_COMPLETE + "\n"
    + "\n".join(_creep8_lines) + "\n"
    + "State: unrelated status update.\n"
    + "\n".join(_pad_lines) + "\n"
)
rc, out, err = run_hook(make_payload(ds158_f_msg))
check(
    "ds158-f. non-contiguous creep8 + State: + pad -> still BLOCKING "
    "(laundering bypass closed, Skeptic Major 1)",
    is_blocking(rc, out, "unrecognized line in the status region"),
)

# ds158-f2. CONTRAST: the SAME creep8 + pad content, but CONTIGUOUS (no
# recognized line splitting them into two blocks) - this is genuinely
# ONE block by the spec's own "contiguous block" language, and its
# combined average legitimately clears the discriminator. This is NOT a
# laundering bypass - unlike ds158-f, there is no separate, non-adjacent
# narrative-creep block riding along; it is one literal contiguous run
# of text.
ds158_f2_msg = (
    IDENTITY_COMPLETE + "\n"
    + "\n".join(_creep8_lines) + "\n"
    + "\n".join(_pad_lines) + "\n"
)
rc, out, err = run_hook(make_payload(ds158_f2_msg))
check(
    "ds158-f2. contiguous creep8 + pad (one literal block) -> DOWNGRADE "
    "(contrast case: this is not laundering, it is one genuine block)",
    is_advisory(rc, out, "downgraded to advisory"),
)

# ds158-f3. Direct unit-level pin of the per-block boolean itself:
# _is_answer_shaped_prose(creep8 alone) is False (fails on its own),
# proving ds158-f's BLOCK verdict traces to the creep8 block failing
# independently, not to some other mechanism.
check(
    "ds158-f3. creep8 alone is NOT answer-shaped (the block that must "
    "fail independently in ds158-f)",
    _mod._is_answer_shaped_prose(_creep8_lines) is False,
)

# ---------------------------------------------------------------------------
# DS-158 round 2: residual-false-positive fix. The round-1 discriminator
# reused _SENTENCE_BOUNDARY_RE (splits on `.`/`!`/`:`), so a colon-led
# clause, "e.g."/"i.e.", or a decimal/version number each inflated the
# unit count and sank the average below threshold; and a bullet/numbered
# list item with no terminal punctuation collapsed an entire list into
# ONE unit, failing the multi-unit floor even though bullets are the most
# common conductor answer shape. Round 2 fixes both - see
# _answer_prose_units / _ANSWER_SENTENCE_SPLIT_RE / _ANSWER_ABBREVIATION_RE.
# ---------------------------------------------------------------------------

check(
    "ds158-g1. a 3-item bullet list with NO terminal punctuation is "
    "answer-shaped (each bullet is its own unit)",
    _mod._is_answer_shaped_prose(
        [
            "- Rewrote the discriminator to stop splitting on colons",
            "- Added abbreviation masking for e.g. and i.e.",
            "- Treated each bullet item as its own answer unit",
        ]
    )
    is True,
)
check(
    "ds158-g2. a 3-item NUMBERED list with no terminal punctuation is "
    "answer-shaped (numbered items are recognized the same as bullets)",
    _mod._is_answer_shaped_prose(
        [
            "1. Rewrote the discriminator to stop splitting on colons",
            "2. Added abbreviation masking for e.g. and i.e.",
            "3. Treated each bullet item as its own answer unit",
        ]
    )
    is True,
)
check(
    "ds158-g3. a genuinely short 2-item bullet list stays NOT "
    "answer-shaped (disclosed residual - low word count per item, not a "
    "regression: see conductor-turn-format.md's residual list)",
    _mod._is_answer_shaped_prose(["- Fixed the bug", "- Added a test"]) is False,
)

_ds158_h1_text = (
    "Two things changed in this pass: the sentence splitter no "
    "longer treats a colon as a boundary, and bullet items now "
    "count on their own regardless of punctuation. Both fixes are "
    "covered by new regression fixtures."
)
check(
    "ds158-h1. a colon-led clause inside a genuine 2-sentence answer "
    "does not inflate the unit count (colon is no longer a unit "
    "boundary)",
    _mod._is_answer_shaped_prose(_ds158_h1_text)
    is True,
)
check(
    "ds158-h2. 'e.g.' inside a genuine 2-sentence answer does not "
    "inflate the unit count (abbreviation masking)",
    _mod._is_answer_shaped_prose(
        "We considered a few mitigations, e.g. rate limiting and "
        "request coalescing, and settled on coalescing because it "
        "needed no client changes. The rollout is staged behind a "
        "feature flag."
    )
    is True,
)
check(
    "ds158-h3. 'i.e.' inside a genuine 2-sentence answer does not "
    "inflate the unit count (abbreviation masking)",
    _mod._is_answer_shaped_prose(
        "The fix only touches the general branch, i.e. the "
        "sole-stoppage branch is untouched by this change and keeps "
        "its existing shape. Both branches share the same length bound "
        "on the identity line."
    )
    is True,
)
check(
    "ds158-h4. a version number ('3.10 to 3.11') does not split as a "
    "sentence boundary",
    _mod._is_answer_shaped_prose(
        "Bumped the dependency from 3.10 to 3.11 to pick up the "
        "upstream fix for the regression we were chasing. Reran the "
        "full suite afterward to confirm nothing else broke."
    )
    is True,
)

# ds158-i. Hook-level regression pin (not just the unit-level function):
# a realistic bullet-list answer beside status slots, no other warrant
# complication, downgrades end-to-end through _execution_prose_flag and
# main().
ds158_i_msg = (
    IDENTITY_COMPLETE + "\n"
    "State: implementing.\n"
    "Running: none.\n"
    "Blocked: none.\n"
    "- Rewrote the sentence-boundary regex so it no longer splits on a "
    "colon, which was inflating the unit count on ordinary explanatory "
    "answers\n"
    "- Added abbreviation masking so e.g. and i.e. no longer count as "
    "sentence boundaries either\n"
)
rc, out, err = run_hook(make_payload(ds158_i_msg))
check(
    "ds158-i. realistic bullet-list answer beside status slots -> "
    "ADVISORY (downgraded), hook-level end-to-end pin",
    is_advisory(rc, out, "downgraded to advisory"),
)

# ---------------------------------------------------------------------------
# DS-158 round 3 (Skeptic Major): the round-2 discriminator REGRESSED
# three realistic shapes from DOWNGRADE to BLOCK - a first sentence
# ending in "no." (masked as an abbreviation, merging it into the next
# sentence and dropping the unit count below the floor), a first
# sentence ending in a version number ("3.11.") or a plain count
# ("174.") (the old digit lookbehind suppressed the boundary after ANY
# digit-final token, not just inside a decimal). Confirmed via
# `git stash` against cd5b0666: all three collapsed to 1 unit there
# (shaped=False); a "negative" control (same shape, no digit/no-token
# involved) correctly split into 2 units and stayed shaped=True at BOTH
# commits - proving the regression was specific to "no."/digits, not a
# general break.
# ---------------------------------------------------------------------------

_ds158_j_no = (
    "The answer is no. We are not proceeding with that approach for "
    "the current release, given the regression risk it carries."
)
_ds158_j_version = (
    "We upgraded the dependency to version 3.11. The regression is "
    "confirmed fixed on that release after a full suite re-run."
)
_ds158_j_count = (
    "The measured value came out to 174. That confirms the earlier "
    "estimate was accurate to within the expected margin of error."
)
_ds158_j_control = (
    "The answer is negative. We are not proceeding with that approach "
    "for the current release, given the regression risk it carries."
)

check(
    "ds158-j1. first sentence ends in 'no.' -> answer-shaped (round-3 "
    "regression fix: 'no' removed from the abbreviation mask)",
    _mod._is_answer_shaped_prose(_ds158_j_no) is True,
)
check(
    "ds158-j2. first sentence ends in a version number ('3.11.') -> "
    "answer-shaped (round-3 regression fix: digit lookbehind removed "
    "from the split regex)",
    _mod._is_answer_shaped_prose(_ds158_j_version) is True,
)
check(
    "ds158-j3. first sentence ends in a plain count ('174.') -> "
    "answer-shaped (same digit-lookbehind regression fix)",
    _mod._is_answer_shaped_prose(_ds158_j_count) is True,
)
check(
    "ds158-j4. control: same shape with 'negative' instead of 'no' -> "
    "answer-shaped at both round 2 and round 3 (proves the regression "
    "was specific to the digit/'no.' handling, not a general split "
    "failure)",
    _mod._is_answer_shaped_prose(_ds158_j_control) is True,
)

# ds158-j5. Hook-level end-to-end pin for one of the round-3 regression
# shapes (version number), beside status slots with a completion warrant.
ds158_j5_msg = (
    IDENTITY_COMPLETE + "\n"
    "State: implementing.\n"
    "Running: none.\n"
    "Blocked: none.\n"
    + _ds158_j_version + "\n"
)
rc, out, err = run_hook(make_payload(ds158_j5_msg))
check(
    "ds158-j5. version-number-ending sentence beside status slots -> "
    "ADVISORY (downgraded), hook-level end-to-end pin",
    is_advisory(rc, out, "downgraded to advisory"),
)

# ds158-j6. decimal number MID-sentence (not at a sentence boundary)
# still does not spuriously split - "3.11" between two words never
# produces a stray unit at the internal decimal point (the \s+
# requirement alone prevents this, since no whitespace follows the
# internal dot).
check(
    "ds158-j6. a mid-sentence decimal ('bumped from 3.10 to 3.11 to') "
    "does not spuriously split at the internal decimal point",
    len(
        _mod._answer_prose_units(
            ["Bumped the dependency from 3.10 to 3.11 to fix the bug."]
        )
    )
    == 1,
)

# ---------------------------------------------------------------------------
# DS-158 round 3 (Skeptic Minor 2): a blank line must break contiguity
# too, not just a recognized slot/Waiting: line or a fence boundary.
# Pre-fix, `_execution_prose_flag`'s general branch `continue`d on a
# blank line without flushing `current_block`, so creep8 + a blank line
# + pad was still ONE block and its combined average could downgrade -
# even though a blank line is the canonical markdown paragraph/block
# separator and every prose statement of the contiguity rule lists it.
# ---------------------------------------------------------------------------

ds158_k_msg = (
    IDENTITY_COMPLETE + "\n"
    + "\n".join(_creep8_lines) + "\n"
    + "\n"
    + "\n".join(_pad_lines) + "\n"
)
rc, out, err = run_hook(make_payload(ds158_k_msg))
check(
    "ds158-k. creep8 + BLANK LINE + pad -> still BLOCKING (blank line "
    "breaks contiguity, Skeptic Minor 2 - creep8 must be classified "
    "independently from the pad paragraph that follows the blank line)",
    is_blocking(rc, out, "unrecognized line in the status region"),
)

# ds158-k2. CONTRAST: two genuinely separate, blank-line-separated
# paragraphs that are BOTH independently answer-shaped still downgrade -
# the blank-line boundary is a free tightening, not a new false positive.
# Paragraph 1 is the full 3-line pad block (3 units, well over
# threshold); paragraph 2 reuses ds158-h1's colon-led 2-sentence answer
# (2 units, over threshold) - each block independently clears the
# discriminator on its own.
ds158_k2_msg = (
    IDENTITY_COMPLETE + "\n"
    + "\n".join(_pad_lines) + "\n"
    + "\n"
    + _ds158_h1_text + "\n"
)
rc, out, err = run_hook(make_payload(ds158_k2_msg))
check(
    "ds158-k2. two blank-line-separated paragraphs, EACH independently "
    "answer-shaped -> DOWNGRADE (blank-line boundary is a free "
    "tightening, not a new false positive)",
    is_advisory(rc, out, "downgraded to advisory"),
)

# ---------------------------------------------------------------------------
# DS-158 round 4 (Skeptic Minor): "etc" remained in
# _ANSWER_ABBREVIATION_RE and the round-3 comment justifying it claimed
# none of the retained entries "end an English sentence on their own
# (unlike 'no')" - false for "etc.", which routinely does. This is a
# RESIDUAL (identical BLOCK at 05fe944d, cd5b0666, and main), not a
# round-3 regression.
# ---------------------------------------------------------------------------

_ds158_l_etc = (
    "We covered lint, typecheck, tests, etc. Everything else was "
    "already green before this change ever landed."
)
check(
    "ds158-l1. a sentence ending in 'etc.' followed by a second "
    "sentence is answer-shaped ('etc' removed from the abbreviation "
    "mask, Skeptic round-4 Minor)",
    _mod._is_answer_shaped_prose(_ds158_l_etc) is True,
)

# ds158-l2. Hook-level end-to-end pin, the Skeptic's exact measured
# sentence beside status slots.
ds158_l2_msg = (
    IDENTITY_COMPLETE + "\n"
    "State: implementing.\n"
    "Running: none.\n"
    "Blocked: none.\n"
    + _ds158_l_etc + "\n"
)
rc, out, err = run_hook(make_payload(ds158_l2_msg))
check(
    "ds158-l2. 'etc.'-ending sentence beside status slots -> ADVISORY "
    "(downgraded), hook-level end-to-end pin (was BLOCKING before this "
    "fix)",
    is_advisory(rc, out, "downgraded to advisory"),
)

# ---------------------------------------------------------------------------
# DS-159: the operator's live complaint. A plain multi-paragraph prose
# answer with ZERO status lines blocked at DS-158 round 3/round 4 HEAD,
# because _execution_prose_flag's general branch required
# _ANSWER_PROSE_MIN_SENTENCES (>=2 units) INSIDE EVERY INDIVIDUAL
# contiguous block - and a terse, blank-line-separated conductor answer
# (this repo's own mandated "1-3 lines per turn" style) routinely
# produces several genuinely single-sentence paragraphs, each its own
# block. The fix: the average-words-per-unit condition stays PER BLOCK
# (unchanged, still the axis narrative-creep launders through), but the
# minimum-unit-count floor is now a WHOLE-TURN AGGREGATE across every
# block that already passed the average-words check.
# ---------------------------------------------------------------------------

# ds159-a. The reported repro shape: a completion-warrant turn with NO
# status slot lines at all, just several blank-line-separated
# single-sentence paragraphs (the operator's actual complaint) -> must
# now DOWNGRADE (was BLOCKING at DS-158 round 4 HEAD, fadfcbf6).
ds159_a_msg = (
    IDENTITY_COMPLETE + "\n"
    "This is a genuinely single-sentence paragraph explaining what "
    "happened here today, written the way a real terse conductor answer "
    "actually reads.\n"
    "\n"
    "This is a second, similarly single-sentence paragraph carrying a "
    "different but equally real piece of explanatory detail.\n"
    "\n"
    "This is a third single-sentence paragraph, again just one sentence "
    "but with real substantive content behind it.\n"
)
rc, out, err = run_hook(make_payload(ds159_a_msg))
check(
    "ds159-a. multi-paragraph answer, EVERY paragraph a single sentence, "
    "no status lines at all -> DOWNGRADE (was BLOCKING pre-DS-159, the "
    "operator's founding complaint for this fix)",
    is_advisory(rc, out, "downgraded to advisory (DS-159)"),
)

# ds159-b. The exact shape the spec requires: a single-sentence
# paragraph SANDWICHED inside an otherwise excellent multi-paragraph
# answer. Paragraph 1 and paragraph 3 are genuinely developed
# (multi-sentence, reusing _pad_lines[0] and _pad_lines[1] - each
# independently clears the OLD per-block floor on its own); paragraph 2
# is a single well-formed sentence that alone could never clear a
# per-block floor of 2. Pre-DS-159 this BLOCKED the whole turn over
# paragraph 2 alone; post-DS-159 the aggregate (2 + 1 + 2 = 5 units)
# clears the floor and the whole turn downgrades.
ds159_b_msg = (
    IDENTITY_COMPLETE + "\n"
    + _pad_lines[0] + "\n"
    "\n"
    "This one paragraph is only a single sentence, unlike its "
    "neighbors.\n"
    "\n"
    + _pad_lines[1] + "\n"
)
rc, out, err = run_hook(make_payload(ds159_b_msg))
check(
    "ds159-b. single-sentence paragraph SANDWICHED inside two "
    "genuinely-developed paragraphs -> DOWNGRADE (the exact shape "
    "DS-159 fixes: one weak paragraph no longer sinks an otherwise "
    "answer-shaped multi-paragraph turn)",
    is_advisory(rc, out, "downgraded to advisory (DS-159)"),
)

# ds159-b2. CONTRAST at the per-block level: paragraph 2 alone still
# fails _is_answer_shaped_prose's per-block AVERAGE check on its own
# arithmetic (few words, but that's not what makes ds159-b downgrade -
# it downgrades because paragraph 2's own average clears 8 words/unit
# too; this direct check confirms paragraph 2 individually passes the
# per-block predicate, which is a precondition for ds159-b's aggregate
# math to be meaningful rather than accidental).
check(
    "ds159-b2. the sandwiched single sentence individually clears the "
    "per-block average-words check on its own merits (precondition for "
    "ds159-b's aggregate downgrade to be meaningful)",
    _mod._is_answer_shaped_prose(
        "This one paragraph is only a single sentence, unlike its "
        "neighbors."
    )
    is True,
)

# ds159-c. THE BLANK-LINE-ONLY LAUNDERING BYPASS (required by the spawn
# brief - ds158-f/f2 only ever separated creep from pad with a
# recognized State: line, never with JUST a blank line and no other
# separator). Narrative-creep sprawl (8 short pings, ALL on one single
# physical line so no State:/Waiting:/fence line ever intervenes)
# immediately followed by a blank line then one genuine answer-shaped
# paragraph. This must still BLOCK: the creep block's own average-words
# check fails regardless of DS-159, and DS-159's aggregate only ever
# sums units from blocks that already independently passed that check -
# a failing block contributes zero units and keeps `all(...)` False.
ds159_c_creep_line = " ".join("Also did thing {}.".format(i) for i in range(1, 9))
ds159_c_msg = (
    IDENTITY_COMPLETE + "\n"
    "Done and shipped. PR merged cleanly.\n"
    "\n"
    + ds159_c_creep_line + "\n"
    "\n"
    + _pad_lines[0] + "\n"
    + _pad_lines[1] + "\n"
    + _pad_lines[2] + "\n"
)
rc, out, err = run_hook(make_payload(ds159_c_msg))
check(
    "ds159-c. narrative-creep sprawl + BLANK LINE (no other separator) + "
    "genuine answer-shaped paragraph -> still BLOCKING (the blank-line-"
    "only laundering shape DS-158's own fixtures never exercised)",
    is_blocking(rc, out, "unrecognized line in the status region"),
)
check(
    "ds159-c2. the finding is NOT tagged 'downgraded to advisory' (proves "
    "ds159-c blocks for the right reason, not by accident)",
    "downgraded to advisory" not in parse_output(out).get("reason", ""),
)

# ds159-d. Direct unit-level pin of the aggregate arithmetic itself,
# bypassing subprocess/JSON entirely: three blocks, each with exactly 1
# unit that individually passes the average-words check, must produce a
# combined total of 3 units - proving the aggregation genuinely SUMS
# across blocks rather than, say, taking a max or re-testing only the
# last block.
_ds159_units_per_block = [
    len(_mod._answer_prose_units([line]))
    for line in [
        "This first single-sentence block carries real explanatory "
        "weight and enough words to clear the per-block average easily.",
        "This second single-sentence block also carries real "
        "explanatory weight and clears the same per-block average.",
        "This third single-sentence block likewise carries real "
        "explanatory weight and clears the same per-block average too.",
    ]
]
check(
    "ds159-d. three independent single-sentence blocks each contribute "
    "exactly 1 unit (3 blocks x 1 unit = 3, precondition for the "
    "aggregate floor of 2 to be meaningfully exercised by ds159-a/b "
    "above, not accidentally satisfied by a single oversized block)",
    _ds159_units_per_block == [1, 1, 1],
)

# ---------------------------------------------------------------------------
# Markup-blindspot fix (real-corpus 320-turn extraction from
# ~/.claude/projects at DS-159 HEAD - see
# content/references/conductor-turn-format.md's residual-false-positive
# list). Four classes, each reproduced from a real BLOCKed turn:
#   mb1 - markdown ATX heading forms its own low-word block
#   mb2 - markdown table forms its own low-word block
#   mb3 - sole-stoppage branch had NO downgrade path at all
#   mb4 - identity-line length check was unconditionally BLOCKING
# Each class also gets a negative counterpart proving the exemption
# cannot itself be used to launder narrative creep past the STRUCTURAL
# check for free - see _MARKDOWN_HEADING_RE/_TABLE_ROW_RE's own "can a
# creep author defeat this" analysis: a heading/table sprawl still
# charges through the separate ADVISORY volume check.
# ---------------------------------------------------------------------------

# mb1. Real-corpus turn_0267 shape: a completion turn whose status region
# opens with a markdown heading ("## /ds-wrap complete") as its own
# blank-line-separated block, alongside a genuinely developed paragraph.
# Pre-fix: BLOCKING (the heading's 3 words/unit sank it below the
# average-words threshold). Post-fix: the heading is recognized structure
# and skipped, so only the genuine paragraph is classified -> QUIET (it
# individually clears both the average-words check and, since there is no
# OTHER competing warrant-worthy content, this whole turn is Answer-free
# completion prose that must still pass the general branch legitimately).
mb1_msg = (
    IDENTITY_COMPLETE + "\n"
    "\n"
    "## /ds-wrap complete\n"
    "\n"
    + _pad_lines[0] + "\n"
    "\n"
    + _pad_lines[1] + "\n"
)
rc, out, err = run_hook(make_payload(mb1_msg))
check(
    "mb1. markdown heading forming its own block + a genuine answer-shaped "
    "paragraph -> not BLOCKING (heading recognized as structure, real-"
    "corpus turn_0267 shape)",
    not is_blocking(rc, out),
)

# mb1-neg. The heading regex alone, unit-level: a heading line is
# recognized (matches _MARKDOWN_HEADING_RE) at 1-6 hashes, but ordinary
# prose that merely starts with a literal '#' character mid-sentence (no
# following whitespace) must NOT be mistaken for a heading.
check(
    "mb1-neg1. '## Heading text' matches _MARKDOWN_HEADING_RE",
    bool(_mod._MARKDOWN_HEADING_RE.match("## Heading text")),
)
check(
    "mb1-neg2. '#nofollowingspace' does NOT match _MARKDOWN_HEADING_RE "
    "(no whitespace after the hash run)",
    not bool(_mod._MARKDOWN_HEADING_RE.match("#nofollowingspace")),
)

# mb1-creep. A heading exemption cannot itself launder an UNBOUNDED
# sprawl of heading-formatted narrative-creep past the STRUCTURAL check
# for free: 8 short pings, each disguised as its own heading, all become
# recognized/skipped, so _execution_prose_flag returns None (quiet).
# DS-171: mb1-creep2 (which pinned that the separate turn-charge volume
# check still caught this sprawl) is DELETED along with that check - see
# hooks/enforce-turn-shape.py's Purpose section and its markdown-heading
# comment block, which now discloses this axis as genuinely unbounded by
# any hook-level check (the rule moved to the `dinostack` output style).
mb1_creep_lines = ["## Also did thing {}.".format(i) for i in range(1, 13)]
mb1_creep_msg = IDENTITY_COMPLETE + "\n" + "\n".join(mb1_creep_lines) + "\n"
_mb1_creep_warrants = _mod._classify_warrants(mb1_creep_msg)
check(
    "mb1-creep1. _execution_prose_flag does NOT block a heading-formatted "
    "narrative-creep sprawl (the structural check alone cannot see it)",
    _mod._execution_prose_flag(mb1_creep_msg, _mb1_creep_warrants) is None,
)

# mb2. Real-corpus turn_0314 shape: a completion turn whose status region
# contains a compact markdown table (header row + separator + 4 data
# rows), alongside ordinary prose paragraphs. Pre-fix: BLOCKING (6 rows,
# 6.33 words/row average, below threshold). Post-fix: every table/
# separator row is recognized and skipped.
mb2_msg = (
    IDENTITY_COMPLETE + "\n"
    "\n"
    + _pad_lines[0] + "\n"
    "\n"
    "| | |\n"
    "|---|---|\n"
    "| **Ticket** | Todo, unstarted |\n"
    "| **Plan** | signed off, ready for engineer spawn |\n"
    "\n"
    + _pad_lines[1] + "\n"
)
rc, out, err = run_hook(make_payload(mb2_msg))
check(
    "mb2. markdown table forming its own block, sandwiched between two "
    "genuine answer-shaped paragraphs -> not BLOCKING (table rows "
    "recognized as structure, real-corpus turn_0314 shape)",
    not is_blocking(rc, out),
)

# mb2-neg. Unit-level table-row regex checks: a genuine pipe-delimited
# row/separator matches; an ordinary sentence that merely CONTAINS a
# literal '|' character (e.g. a pasted shell pipeline) does NOT, because
# it lacks the required trailing '|'.
check(
    "mb2-neg1. '| a | b |' matches _TABLE_ROW_RE",
    bool(_mod._TABLE_ROW_RE.match("| a | b |")),
)
check(
    "mb2-neg2. '|---|---|' (separator row) matches _TABLE_ROW_RE",
    bool(_mod._TABLE_ROW_RE.match("|---|---|")),
)
check(
    "mb2-neg3. 'ran cmd | grep foo' (a pasted shell pipeline, no "
    "trailing pipe) does NOT match _TABLE_ROW_RE",
    not bool(_mod._TABLE_ROW_RE.match("ran cmd | grep foo")),
)

# mb2-creep. Same laundering-bound proof as mb1-creep, for table rows: a
# table-formatted creep sprawl escapes the structural check. DS-171:
# mb2-creep2 (turn-charge volume check) is deleted - see mb1-creep's note
# above.
mb2_creep_lines = ["| Also did thing {} | done |".format(i) for i in range(1, 13)]
mb2_creep_msg = IDENTITY_COMPLETE + "\n" + "\n".join(mb2_creep_lines) + "\n"
_mb2_creep_warrants = _mod._classify_warrants(mb2_creep_msg)
check(
    "mb2-creep1. _execution_prose_flag does NOT block a table-formatted "
    "narrative-creep sprawl",
    _mod._execution_prose_flag(mb2_creep_msg, _mb2_creep_warrants) is None,
)

# mb1-len / mb2-len (Skeptic Major 1). A SINGLE arbitrarily long
# narrative line prefixed "## " or wrapped in "| ... |" must NOT pass
# with no block and no advisory - it is a length violation, closed the
# same way an over-length State:/Running:/Blocked: slot line already
# is: BLOCKING immediately, not silently recognized as exempt
# structure. Pre-Skeptic-Major-1-fix this passed completely invisibly
# (neither the structural check nor the line-count volume check ever
# saw it, since it was one recognized/skipped line).
_giant_narrative = (
    "This is a genuinely long narrative paragraph disguised as "
    "recognized markup. " * 18
).strip()
assert len(_giant_narrative) > _mod.STATUS_LINE_MAX_CHARS

mb1_len_msg = IDENTITY_COMPLETE + "\n## " + _giant_narrative + "\n"
rc, out, err = run_hook(make_payload(mb1_len_msg))
check(
    "mb1-len. general branch: an over-length markdown HEADING line "
    "BLOCKS on length, exactly like an over-length slot line does "
    "(real-corpus-adjacent stress case, general branch)",
    is_blocking(rc, out, "markdown heading/table row is"),
)

mb2_len_msg = IDENTITY_COMPLETE + "\n| " + _giant_narrative + " |\n"
rc, out, err = run_hook(make_payload(mb2_len_msg))
check(
    "mb2-len. general branch: an over-length markdown TABLE ROW "
    "BLOCKS on length, exactly like an over-length slot line does",
    is_blocking(rc, out, "markdown heading/table row is"),
)

mb2_len_sole_msg = (
    IDENTITY_OK + "\n"
    "Waiting: engineer - unit 3.\n"
    "| " + _giant_narrative + " |\n"
)
rc, out, err = run_hook(make_payload(mb2_len_sole_msg))
check(
    "mb2-len-sole. sole-stoppage branch: an over-length markdown TABLE "
    "ROW also BLOCKS on length (the length bound applies on BOTH "
    "branches, mirroring the slot-line length check)",
    is_blocking(rc, out, "sole-stoppage"),
)

# mb1-len2/mb2-len2. Reference control: an over-length State: slot line
# already blocked before this fix - direct comparison proving the new
# heading/table length check now produces the SAME verdict class on the
# same input shape (both BLOCK on a length-violation finding), not a
# coincidentally-similar but different code path.
mb_slot_len_msg = IDENTITY_COMPLETE + "\nState: " + _giant_narrative + "\n"
rc, out, err = run_hook(make_payload(mb_slot_len_msg))
check(
    "mb-slot-len (reference). an over-length State: slot line BLOCKS "
    "on length - unchanged reference point for mb1-len/mb2-len above",
    is_blocking(rc, out, "status slot line is"),
)

# mb3. Real-corpus turn_0093 shape: a sole-stoppage turn (a "Waiting:"
# line is the ONLY warrant) followed by a genuine two-sentence
# explanatory paragraph. Pre-fix: the sole-stoppage branch had NO
# downgrade path at all - ANY line other than Waiting:/a status slot
# BLOCKED unconditionally. Post-fix: extended to the same
# contiguous-block + answer-shaped-prose mechanism the general branch
# already uses.
mb3_msg = (
    IDENTITY_OK + "\n"
    "Waiting: engineer - implementing the fix (fresh attempt, background)\n"
    "\n"
    "The first attempt died to a transient harness connection error "
    "before writing anything, so a fresh attempt was respawned with the "
    "same brief. Skeptic review follows when it returns.\n"
)
rc, out, err = run_hook(make_payload(mb3_msg))
check(
    "mb3. sole-stoppage turn (Waiting: is the only warrant) + a genuine "
    "two-sentence explanatory paragraph -> ADVISORY, not BLOCKING "
    "(real-corpus turn_0093 shape - the sole-stoppage branch previously "
    "had no downgrade path at all)",
    is_advisory(rc, out, "downgraded to advisory"),
)

# mb3-neg. The SAME sole-stoppage domain must still BLOCK on genuine
# narrative-creep (a sprawl of short templated pings), proving the
# downgrade mechanism did not simply disable the sole-stoppage check.
mb3_creep_msg = (
    IDENTITY_OK + "\n"
    "Waiting: engineer - implementing the fix.\n"
    + "\n".join(_creep8_lines) + "\n"
)
rc, out, err = run_hook(make_payload(mb3_creep_msg))
check(
    "mb3-neg. sole-stoppage turn + narrative-creep sprawl (not a genuine "
    "answer paragraph) -> still BLOCKING (anti-laundering property "
    "preserved on the newly-extended branch)",
    is_blocking(rc, out, "sole-stoppage"),
)

# mb4. Real-corpus turn_0090/turn_0096 shape: a multi-sentence identity
# line with no early line break, over STATUS_LINE_MAX_CHARS (200 chars).
# Pre-fix: unconditionally BLOCKING regardless of content. Post-fix:
# downgrades to ADVISORY when the identity line itself clears the same
# answer-shaped-prose discriminator (average words/unit + >=2 units) used
# elsewhere in this hook.
mb4_identity = (
    "unit-1 · fix-thing · abc1234 [phase: complete] The first sentence "
    "here carries real explanatory content well past the two hundred "
    "character mark on its own. A second genuine sentence follows it "
    "immediately, with no line break separating the two at all."
)
mb4_msg = mb4_identity + "\nState: done.\n"
rc, out, err = run_hook(make_payload(mb4_msg))
check(
    "mb4. multi-sentence identity line over STATUS_LINE_MAX_CHARS -> "
    "ADVISORY, not BLOCKING (real-corpus turn_0090/turn_0096 shape - "
    "identity line reads as genuine answer-shaped prose)",
    is_advisory(rc, out, "downgraded to advisory"),
)

# mb4-neg. A genuinely non-prose over-length identity line (the existing
# ds156-h stress shape: one long run of a repeated, non-word-boundary
# character with no recognizable sentence structure) must still BLOCK -
# proves the downgrade cannot be triggered by length alone.
_mb4_neg_rc, _mb4_neg_out, _mb4_neg_err = run_hook(make_payload(ds156_h_general_msg))
check(
    "mb4-neg. ds156-h's repeated-character identity line still BLOCKS "
    "(no sentence structure to clear the answer-shaped-prose "
    "discriminator)",
    is_blocking(_mb4_neg_rc, _mb4_neg_out, "identity line is"),
)

# ---------------------------------------------------------------------------
# Real-corpus regression replay (hooks/tests/fixtures/
# turn-shape-real-corpus-sample.json): a curated 10-turn subset of the
# 320-turn real conductor-transcript corpus this fix was measured
# against. The 5 "was_block" entries are the ONLY 5 turns (of 320) that
# BLOCKed at cfd764e4 (DS-159 HEAD) - all 5 must no longer BLOCK. The
# other 5 are non-BLOCKING controls (3 QUIET, 2 ADVISORY at cfd764e4),
# replayed to catch a future regression that reintroduces a BLOCKING
# false positive on real turns rather than only on hand-written fixtures.
# `pre_fix_class` documents each turn's classification at cfd764e4, before
# this fix landed - it is a historical record, not a current-behavior
# assertion. The two ADVISORY entries (turn_0016, turn_0037) carry a
# `post_fix_class: "QUIET"` field: post-DS-171, `_status_only_flag` (the
# check that produced their ADVISORY finding) is retired outright, so they
# now emit no output at all - a deliberate, intended change from ADVISORY
# to QUIET, not a regression. The loop below still only asserts "not
# BLOCKING" for every control, which both ADVISORY and QUIET satisfy.
# ---------------------------------------------------------------------------

with open(
    os.path.join(
        os.path.dirname(__file__), "fixtures", "turn-shape-real-corpus-sample.json"
    ),
    "r",
    encoding="utf-8",
) as _rc:
    _real_corpus = json.load(_rc)

_real_corpus_still_blocking = []
for _turn in _real_corpus["turns"]:
    _rc_rc, _rc_out, _rc_err = run_hook(make_payload(_turn["text"]))
    _rc_is_block = '"decision": "block"' in _rc_out
    if _rc_is_block:
        _real_corpus_still_blocking.append(_turn["file"])
    if _turn["pre_fix_class"] == "BLOCK":
        check(
            "real-corpus {}. was the pre-fix BLOCKing false positive this "
            "fix targets -> no longer BLOCKING".format(_turn["file"]),
            not _rc_is_block,
        )
    else:
        # Control turn: assert it still does not BLOCK. This does NOT
        # assert the classification is unchanged - turn_0016 and
        # turn_0037 (`pre_fix_class: "ADVISORY"`) are newly QUIET
        # post-DS-171 (see `post_fix_class` on those two fixture entries
        # and the block comment above): `_status_only_flag` was retired
        # outright, not merely fixed, so those two turns now produce no
        # output at all. That is intended, not a regression - the
        # non-BLOCKING property this loop checks is unaffected either way.
        check(
            "real-corpus {}. control turn ({}) -> still not BLOCKING".format(
                _turn["file"], _turn["pre_fix_class"]
            ),
            not _rc_is_block,
        )

check(
    "real-corpus summary: 0 of the curated 10-turn subset BLOCK "
    "post-fix (was 5 pre-fix)",
    len(_real_corpus_still_blocking) == 0,
)

# ---------------------------------------------------------------------------
# Advisory-recall fix: 3 real corpus turns, hand-classified as genuine
# status-only false positives (multi-sentence explanatory answers that
# pre-fix code flagged status-only purely on line count, with none of
# _QUOTED_FRAGMENT_RE's double-quoted fragment / _transcript_answer_bonus's
# question-shaped preceding message). Screened before inclusion in this
# PUBLIC repo (credential shapes, personal emails/names, and any sibling-
# project brand/filename all excluded or redacted); no `transcript_path`
# is supplied for any of the three, so none of them carries an Answer
# warrant (no quoted fragment, no transcript bonus) or a Decision/Stoppage/
# Completion warrant either - all three classify as zero-warrant turns.
# Post-DS-171, `_status_only_flag` (and its suppression heuristic,
# `_status_only_prose_is_explanatory`, named by an earlier version of this
# comment) is retired outright, so no hook check runs on the zero-warrant
# branch at all - QUIET below is a structural consequence of that branch
# having no check, not a heuristic classification. These assertions retain
# their value as a record that this real-corpus false-positive class is
# still QUIET post-DS-171, even though the mechanism that makes it so has
# changed. Measured against the same 320-turn real corpus cited in this
# module's docstring: 37 turns flagged status-only pre-fix, 2 remain
# flagged post-fix (both genuine single-sentence status pings), so the 35
# recalled turns - of which these three are a hand-picked, publication-safe
# sample - average well above the 8 words/unit threshold (16-44 words/unit
# measured across the full recalled set).
# ---------------------------------------------------------------------------

corpus_fp1_msg = (
    IDENTITY_OK
    + "\n"
    + "Fix in flight. [phase: ci-fix]\n"
    "\n"
    "The verification round paid for itself. Everything the engineer "
    "claimed held up under independent mutation testing - including the "
    "`closed_unmerged` mapping surviving, which is the exact spot a bad "
    "quote would have silently deleted. But it also caught what the "
    "earlier round didn't: a JS hook test pins the old Part F sentence "
    "verbatim, and it lives in `hooks/tests/`, not `bin/tests/`. The "
    "600-pass number was accurate and irrelevant to it.\n"
    "\n"
    "Worth noting the fix direction, because the tempting move is wrong: "
    "revert the prose to satisfy the old regex. That prose is a "
    "byte-identical clause shared across two files - itself a Skeptic "
    "finding that took three attempts to land. So the stale guard gets "
    "updated, and it has to still fail when the gate is removed, or it's "
    "worse than what it replaced.\n"
    "\n"
    "The verifier was also honest about its own new guard: it probed the "
    "R4 never-substitutes test with novel wording (`retry with the "
    "semantically equivalent live state name`) and got a pass. The guard "
    "is real at its pinned call sites but the docstring claims block-wide "
    "coverage it doesn't have - so the docstring gets corrected rather "
    "than trusted.\n"
)
rc, out, err = run_hook(make_payload(corpus_fp1_msg))
check(
    "corpus-fp1. real corpus false positive (multi-paragraph fix-in-flight "
    "explanation, no quoted fragment, no transcript bonus) -> QUIET",
    is_quiet(rc, out),
)

corpus_fp2_msg = (
    IDENTITY_OK
    + "\n"
    + "I found the issue. The qa-engineer agent writes screenshots and "
    "diff images to `/tmp/` and only tears down browser sessions/dev "
    "servers - it never deletes the screenshot files. The teardown "
    "section mentions a dev-server log path but not screenshot "
    "cleanup.\n"
    "\n"
    "A few questions before I route this as a fix:\n"
    "\n"
    "1. Do you want cleanup to cover **all** qa-engineer temp artifacts "
    "(screenshots, diff PNGs, dev server log) or specifically "
    "screenshots?\n"
    "2. Should cleanup happen **on every exit path** (matching the "
    "existing browser/dev-server teardown obligation) or only on PASS?\n"
    "3. Is this the only agent with temp-file leakage, or do you suspect "
    "others (e.g. `agent-browser`, orchestration tools)? I can audit "
    "other agent specs while fixing this one.\n"
)
rc, out, err = run_hook(make_payload(corpus_fp2_msg))
check(
    "corpus-fp2. real corpus false positive (diagnosis + numbered "
    "clarifying questions, no quoted fragment, no transcript bonus) -> "
    "QUIET",
    is_quiet(rc, out),
)

corpus_fp3_msg = (
    IDENTITY_OK
    + "\n"
    + "Final review running on a deliberately narrow scope - verify five "
    "changes landed, confirm nothing regressed, don't re-open five "
    "rounds of verified work.\n"
    "\n"
    "The two things I'd bet on if anything is still wrong: whether a "
    "reuse claim survived the scope-out disguised as background or "
    "rationale (a deferral that still asserts a mechanism isn't a "
    "deferral), and a per-consumer table row that has been inaccurate "
    "in three consecutive revisions in two opposite directions.\n"
    "\n"
    "I also asked it to check that a rubric line's new absence-grep "
    "isn't too narrow a pattern - an absence claim is only as strong as "
    "its search breadth, which is a lesson already in this repo's "
    "memory.\n"
    "\n"
    "The plan's fresh design still running.\n"
)
rc, out, err = run_hook(make_payload(corpus_fp3_msg))
check(
    "corpus-fp3. real corpus false positive (multi-paragraph review-scope "
    "narration, no quoted fragment, no transcript bonus) -> QUIET",
    is_quiet(rc, out),
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
