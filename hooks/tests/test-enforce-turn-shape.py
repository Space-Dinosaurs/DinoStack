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
