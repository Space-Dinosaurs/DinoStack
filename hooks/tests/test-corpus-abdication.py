#!/usr/bin/env python3
# Run with: python3 hooks/tests/test-corpus-abdication.py
"""
Purpose: Permanent regression corpus for hooks/enforce-no-abdication.py. This
         file exists because three rounds of architect+Skeptic review each
         proposed a change to widen the hook's detection, and each was
         measured unsafe by hand-built one-off probe sets that were then
         thrown away. This corpus makes those measured failure classes
         durable and executable so the next author who attempts any of the
         four rejected changes below cannot ship on a guess - they must run
         this file and it must still pass.

         The four rejected attempts, pinned by this corpus:
           1. Widening _PERMISSION_PHRASES (the closed 9-phrase list) to
              catch more "obvious question" shapes: measured 11/17 then 7/8
              FALSE BLOCKS on genuine hard-stop questions (Group 3 below).
           2. Narrowing the design-fork negative gate to require
              co-occurrence rather than a bare-word match: composes with (1)
              to strip hard-stop protection entirely (Group 5 below).
           3. A flat whole-block "(recommended)" substring shape, no
              per-item split, routed through _ABDICATION_REASON: rejected
              on Skeptic findings against the plan proposing it - never
              built, never reached a measurable shape. Hard-gate/surface-
              and-proceed suppression and code-fence/blockquote exclusion
              must be present from first authoring, not bolted on after
              review. A revival needed to add a compliant ALLOW row and a
              genuine co-equal-ballot BLOCK row to this corpus, and to
              route through a dedicated reason constant that does not
              carry an unconditional "proceed now" directive. A per-item,
              fence-masking design with a dedicated non-"proceed now"
              reason (_is_prose_ballot / _BALLOT_REASON) shipped in
              a950bdd4 (PR #519) - per its PR body, 0 Critical findings
              across three Skeptic rounds, and it passes this corpus.
              Groups 3/5/7 remain the floor for the OTHER rejected
              attempts; Group 8 below now carries the compliant ALLOW row
              and the genuine co-equal-ballot BLOCK row this revival
              required, closing that gap. Two limitations remain, both
              deliberate and known: the negative-gate exemption
              (self-documented at _is_prose_ballot's own docstring) and
              the absent ">"-blockquote heading handling.
           4. Widening the destructive negative gate with
              `drop/alter table|column|index|database|schema`: measured
              13/13 FALSE SUPPRESSIONS - it stops catching real abdication on
              turns that only incidentally mention those words (Group 1
              below).

         This is a standalone stdlib-only script (no pytest), auto-discovered
         by .github/workflows/bin-tests.yml's hooks-python-tests job via the
         `hooks/tests/test-*.py` glob - no CI wiring change is needed. It
         exercises the REAL hook file via subprocess, exactly like
         test-enforce-no-abdication.py and test-enforce-stall-detection.py -
         it never imports or reimplements the hook's regex/classifier logic.

         Zero behavioral change to the hook is made or implied by this file.
         It is pure pinning: every row's expectation matches CURRENT hook
         behavior, including two rows (Group 2) that pin a known imperfection
         on purpose, and possibly some rows (Group 4) that pin a known
         residual limitation - see their comments for what was actually
         measured, not assumed.

Public API: python3 hooks/tests/test-corpus-abdication.py
            Exits 0 when every CORPUS row's actual result matches its
            expect_block value AND at least one row actually blocked (the
            vacuous-pass guard - see main()). Exits 1 otherwise, printing a
            PASS/FAIL line per row plus a summary.

Upstream deps: Python 3 stdlib only (json, os, subprocess, sys, tempfile).
               Invokes hooks/enforce-no-abdication.py as a subprocess - never
               imports it.

Downstream consumers: .github/workflows/bin-tests.yml (hooks-python-tests
                      job, glob-discovered). No other consumers.

Failure modes: a row whose actual result does not match its expect_block
               value is reported as FAIL with the row id, category, rc,
               stdout, and stderr. If zero rows in the whole run actually
               blocked, main() fails loudly with a distinct message stating
               the harness is not exercising the hook at all - this is the
               mechanical defense against a suite that "passes" because
               nothing ran (e.g. a missing .agentic/config.json in every
               row's temp dir, which makes the hook fail-open on every
               invocation and every ALLOW-expectation row pass vacuously).

Performance: subprocess-per-row; a couple dozen rows complete in well under
             CI's 5-minute job timeout.

IMPORTANT for future editors of hooks/enforce-no-abdication.py: any NEW
classifier added to that hook should route its injected directive through
the two-exit pattern (proceed now OR explicitly wait for authorization)
shared by _STALL_REASON and _ABDICATION_REASON - never an unconditional
"proceed now" directive. A false positive on an unconditional directive
forces an irreversible action with no escape on that turn, whereas the
two-exit wording gives the conductor a compliant way out even when the
classifier guesses wrong.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile

HOOK_PATH = os.path.join(
    os.path.dirname(__file__), "..", "enforce-no-abdication.py"
)

# ---------------------------------------------------------------------------
# Helpers (mirrors test-enforce-no-abdication.py / test-enforce-stall-detection.py)
# ---------------------------------------------------------------------------


def run_hook(payload: str, env: dict | None = None, timeout: int = 10) -> tuple[int, str, str]:
    """Invoke the real hook file as a subprocess. Never imports the hook."""
    merged_env = os.environ.copy()
    merged_env.pop("AE_ABDICATION_GUARD_DISABLE", None)
    if env:
        merged_env.update(env)
    result = subprocess.run(
        [sys.executable, HOOK_PATH],
        input=payload,
        capture_output=True,
        text=True,
        env=merged_env,
        timeout=timeout,
    )
    return result.returncode, result.stdout, result.stderr


def is_block(returncode: int, stdout: str) -> bool:
    """BLOCK: exit 0, {"decision":"block","reason":<non-empty str>} on stdout.

    MUST return a real bool - explicitly cast with bool(...). An untyped
    boolean-expression chain that happens to evaluate to a non-bool truthy
    value is a known bug shape in exactly this kind of helper; casting
    explicitly closes it off rather than relying on every operand already
    being bool-typed.
    """
    if returncode != 0:
        return False
    stripped = stdout.strip()
    if not stripped:
        return False
    try:
        obj = json.loads(stripped)
    except Exception:
        return False
    return bool(
        obj.get("decision") == "block"
        and isinstance(obj.get("reason"), str)
        and len(obj["reason"]) > 0
    )


def _make_payload(cwd: str, message: str) -> str:
    return json.dumps(
        {
            "hook_event_name": "Stop",
            "session_id": "corpus-abdication-test",
            "cwd": cwd,
            "stop_hook_active": False,
            "permission_mode": "default",
            "last_assistant_message": message,
        }
    )


def _write_config(cwd: str) -> None:
    """Write .agentic/config.json with abdication_guard_enabled: true.

    MANDATORY CORRECTION 2: without this file, the hook exits 0 (allow)
    early for EVERY row (see enforce-no-abdication.py main(), the config
    check around line 858-867), and every ALLOW-expectation row would pass
    vacuously regardless of the message text.
    """
    agentic_dir = os.path.join(cwd, ".agentic")
    os.makedirs(agentic_dir, exist_ok=True)
    with open(os.path.join(agentic_dir, "config.json"), "w") as f:
        json.dump({"abdication_guard_enabled": True}, f)


# ---------------------------------------------------------------------------
# Corpus
# ---------------------------------------------------------------------------
# Each row: (id, category, text, expect_block). expect_block is the
# CURRENTLY MEASURED behavior of the unmodified hook - not an aspiration.

CORPUS: list[tuple[str, str, str, bool]] = []

# --- Group 1: BLOCK-side pins -----------------------------------------------
# Non-destructive turns whose text incidentally matches drop|alter near
# table|column|index|database|schema. All 13 were constructed and measured to
# BLOCK correctly on the current hook. They exist so that any future
# destructive-gate widening (rejected attempt #4 above) must prove it does
# not suppress them - the 13/13 false-suppression measurement is what killed
# that attempt, and these are the exact 13 rows.
_GROUP1_BLOCK_PINS = [
    "Should I drop the index on the search page redesign?",
    "Do you want me to drop the column header styling?",
    "Should I go ahead and alter the schema doc wording?",
    "Want me to drop that table border?",
    "Want me to drop the shadow on the column layout?",
    "Should I drop the index.ts re-export?",
    "Should I drop the database section from the README?",
    "The old pivot table markup is still there. Should I drop the table wrapper div?",
    "Want me to drop the index signature from the types file?",
    "Should I alter the schema comment to match?",
    "Want me to drop the column gap to 8px?",
    "Should I drop the table-driven test in favor of parametrize?",
    "Should I drop the index into the log message?",
]
for _i, _text in enumerate(_GROUP1_BLOCK_PINS):
    CORPUS.append((
        f"g1-{_i:02d}",
        "block_pin_coincidental_destructive_lexical",
        _text,
        True,
    ))

# --- Group 2: known imperfection, pinned as current behavior ---------------
# These ARE genuinely destructive questions that arguably SHOULD reach the
# operator as a hard-stop rather than being force-completed by this guard -
# but the cure (rejected attempt #4) was measured worse than the disease
# (13/13 false suppressions on Group 1's shape), so current behavior is
# pinned deliberately. The block message itself instructs the model to
# re-surface genuinely destructive questions (see _ABDICATION_REASON's "(1) a
# genuinely irreversible/destructive action not pre-authorized" carve-out),
# so this is self-correcting in practice, not a silent trap. DO NOT "fix"
# this by widening the destructive gate - see rejected attempt #4 above.
CORPUS.append((
    "g2-00",
    "known_gap_pinned_destructive_question",
    "Should I go ahead and drop the orders table now?",
    True,
))
CORPUS.append((
    "g2-01",
    "known_gap_pinned_destructive_question",
    "Should I go ahead and alter the users schema now?",
    True,
))

# --- Group 3: hard-stop-adjacent ALLOW rows ---------------------------------
# These must never block. Each was measured to FALSELY BLOCK under the
# rejected phrase-widening attempt (#1 above, 11/17 then 7/8 false blocks) -
# they are the permanent precondition any future widening of
# _PERMISSION_PHRASES must clear. Under the CURRENT (unwidened) hook they
# simply do not match any of the 9 closed phrases, so they ALLOW today for a
# more basic reason too - but that is exactly the property future widening
# must not destroy.
_GROUP3_HARD_STOP_ADJACENT_ALLOW = [
    "I need the staging DB password before I can run this. Which credential store do you prefer I read it from?",
    "This will rewrite published history on the release branch. Which tag do you prefer I reset to?",
    "There are two prod regions and this is not reversible per-region. Which region do you prefer I start with?",
    "The vendor contract renewal is a business call. How would you like to handle the pricing tier?",
    "Before I send the release notes out to the mailing list - is that what you had in mind?",
    "I cannot tell which of the two customer accounts is live. Do you want the sandbox account used?",
]
for _i, _text in enumerate(_GROUP3_HARD_STOP_ADJACENT_ALLOW):
    CORPUS.append((
        f"g3-{_i:02d}",
        "hard_stop_adjacent_allow",
        _text,
        False,
    ))

# --- Group 4: quotation ALLOW rows ------------------------------------------
# A permission-seeking phrase appearing only inside quoted/fenced/relayed
# content must not block. MEASURED (not assumed) against the current hook:
# the tail-scan design has NO deliberate quote/fence awareness at all, so
# three of these four rows BLOCK - a permission question embedded in quoted
# text is indistinguishable from the model asking it directly. This is a
# known residual limitation, pinned honestly rather than forcing an
# expectation the code does not meet.
#
# The fourth row (relayed_subagent_quotation) measured False (ALLOW), but not
# because the hook understood the quoting: the sentence-split regex
# (_SENTENCE_SPLIT_RE) only splits on a terminator immediately followed by
# whitespace, and here the "?" is immediately followed by a closing quote
# mark (`?" I already ran...`) with no whitespace in between - so the
# splitter never isolates "Want me to run the tests?" as its own sentence,
# the whole string is treated as one sentence ending in "passed.", and
# _is_abdication's endswith("?") check never fires. This is an accidental
# side effect of the sentence splitter, not intentional quote-awareness - if
# a future change to the punctuation-adjacency handling makes this flip to
# True, that is expected and this row's expectation (and comment) should be
# updated to match, not treated as a regression.
_GROUP4_QUOTATION = [
    (
        "fenced_code_block",
        "Here is the relayed engineer output verbatim:\n\n"
        "```\nStatus: DONE\nShould I proceed with the migration?\n```\n\n"
        "I'm not asking that myself - just relaying the sub-agent's report for context.",
        True,  # measured: the hook does not recognize fencing at all
    ),
    (
        "blockquote",
        "The user's original message included this:\n\n"
        "> Should I go ahead and merge this?\n\n"
        "I already merged it after confirming out of band.",
        True,  # measured: the hook does not recognize blockquotes at all
    ),
    (
        "relayed_subagent_quotation",
        'The engineer returned: "Want me to run the tests?" '
        "I already ran them myself and they passed.",
        # measured False - see the Group 4 comment above for why (sentence
        # splitter punctuation-adjacency artifact, not quote-awareness).
        False,
    ),
    (
        "quoted_todo_comment",
        "Found a stale comment in the file: // TODO: should I proceed with removing this helper?\n"
        "Left it as-is since it's out of scope for this ticket.",
        True,  # measured: the hook does not recognize comment quoting at all
    ),
]
for _i, (_label, _text, _expect_block) in enumerate(_GROUP4_QUOTATION):
    CORPUS.append((
        f"g4-{_i:02d}-{_label}",
        "quotation_known_residual_limitation",
        _text,
        _expect_block,
    ))

# --- Group 5: design-fork composition ALLOW rows ----------------------------
# These allow today only because the design-fork tokens
# (which direction/approach/option/of these, load-bearing, design
# decision/fork/choice) remain bare-word matches in the negative gate. They
# pin that: narrowing this gate to require co-occurrence (rejected attempt
# #2 above) composes with a widened _PERMISSION_PHRASES (rejected attempt #1)
# to strip hard-stop protection from exactly these shapes.
_GROUP5_DESIGN_FORK_ALLOW = [
    "There is a design fork on the retry semantics for the payments webhook. Which approach do you prefer?",
    "The cache key format is a design decision. How would you like the tenant id encoded?",
    "That constant is load-bearing for the billing rollup. Do you want the fallback hard-coded or read from config?",
    "Which option do you prefer for the token TTL - 15 min or 24 h?",
    "This is a design choice about the migration ordering. Is that what you had in mind?",
]
for _i, _text in enumerate(_GROUP5_DESIGN_FORK_ALLOW):
    CORPUS.append((
        f"g5-{_i:02d}",
        "design_fork_composition_allow",
        _text,
        False,
    ))

# --- Group 6: true-positive pins --------------------------------------------
# Must keep blocking - uses the existing 9 phrases with no negative-gate
# token present. If these ever flip to False, something suppressed the
# classic classifier far more broadly than intended.
CORPUS.append((
    "g6-00",
    "true_positive_block",
    "Want me to run the tests?",
    True,
))
CORPUS.append((
    "g6-01",
    "true_positive_block",
    "I've finished the analysis. Should I go ahead and ship it?",
    True,
))

# --- Group 7: ordinary-completion ALLOW controls ----------------------------
# No interrogative and no permission phrase at all - baseline controls that
# must never block regardless of anything above.
CORPUS.append((
    "g7-00",
    "ordinary_completion_allow",
    "Fixed the bug in config.ts and added a regression test. All quality gates pass.",
    False,
))
CORPUS.append((
    "g7-01",
    "ordinary_completion_allow",
    "Filed the two follow-up tickets as DS-201 and DS-202. Learnings captured to memory.",
    False,
))

# --- Group 8: prose-ballot classifier (_is_prose_ballot / _BALLOT_REASON) --
# Closes the gap rejected attempt #3 left open (see the Purpose docstring
# above): this classifier shipped in a950bdd4 (PR #519) and, until these
# rows, nothing in this corpus exercised its "## Operator decisions" +
# unmarked-item path at all. All three values below are MEASURED against
# the real hook, not assumed - see the header comment on each row.
#
# g8-00: a genuine co-equal ballot - 2 items, neither carries a
# "(Recommended)" or "Recommendation:" marker. Measured to BLOCK.
CORPUS.append((
    "g8-00",
    "prose_ballot_block",
    "Fixed the login bug and added a regression test.\n\n"
    "## Operator decisions\n\n"
    "- Proceed with approach A for the retry policy - unclear which is preferred.\n"
    "- Proceed with approach B for the cache eviction window - unclear which is preferred.",
    True,
))
# g8-01: a compliant block - 2 items, each carries a recommendation marker
# (one "(Recommended)" suffix, one "Recommendation:" lead-in). Measured to
# ALLOW - a compliant author is never punished by this check.
CORPUS.append((
    "g8-01",
    "prose_ballot_compliant_allow",
    "Fixed the login bug and added a regression test.\n\n"
    "## Operator decisions\n\n"
    "- Proceed with approach A for the retry policy (Recommended) - matches the existing pattern in src/foo.ts.\n"
    "- Proceed with approach B for the cache eviction window. Recommendation: use a 5 minute TTL to match the session cache.",
    False,
))
# g8-02: a single decision item with a marker. Pins that a lone recommended
# decision never trips the ballot check (the rule bans co-equal ballots,
# not surfacing one genuine decision - see _is_prose_ballot's docstring).
# Measured to ALLOW.
CORPUS.append((
    "g8-02",
    "prose_ballot_single_item_allow",
    "Fixed the login bug and added a regression test.\n\n"
    "## Operator decisions\n\n"
    "- Proceed with approach A for the retry policy (Recommended) - matches the existing pattern in src/foo.ts.",
    False,
))


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _run_row(row: tuple[str, str, str, bool]) -> tuple[bool, int, str, str]:
    """Run a single corpus row in its own isolated temp dir.

    MANDATORY CORRECTION 1: isolation is via the payload's `cwd` field, NOT
    the subprocess working directory. _counter_path() in
    enforce-no-abdication.py resolves os.path.join(cwd, ".agentic",
    COUNTER_FILENAME) where `cwd` comes from the stdin JSON payload (read in
    main()), not from the process's actual working directory. Setting only
    the subprocess cwd (or not isolating at all) lets CONSECUTIVE_BLOCK_CAP
    state accumulate across rows and silently suppress later blocks.
    """
    row_id, _category, text, expect_block = row
    with tempfile.TemporaryDirectory() as tmp_dir:
        _write_config(tmp_dir)
        payload = _make_payload(tmp_dir, text)
        rc, stdout, stderr = run_hook(payload)
        actual_block = is_block(rc, stdout)
        ok = actual_block == expect_block
        return ok, rc, stdout, stderr


def main() -> int:
    failed = 0
    any_row_blocked = False
    results = []

    for row in CORPUS:
        row_id, category, text, expect_block = row
        ok, rc, stdout, stderr = _run_row(row)
        actual_block = is_block(rc, stdout)
        if actual_block:
            any_row_blocked = True
        status = "PASS" if ok else "FAIL"
        if not ok:
            failed += 1
        results.append((row_id, category, status, expect_block, actual_block))
        print(f"  [{status}] {row_id:12s} {category:42s} expect_block={expect_block!s:5s} actual={actual_block!s:5s}")
        if not ok:
            print(f"         text:   {text!r}")
            print(f"         rc:     {rc}")
            print(f"         stdout: {stdout!r}")
            print(f"         stderr: {stderr!r}")

    print()
    print(f"Ran {len(CORPUS)} corpus rows.")

    # MANDATORY CORRECTION 3: the harness must assert at least one row BLOCKs
    # before trusting any ALLOW row. If zero rows blocked across the entire
    # run, the harness is not exercising the hook at all (e.g. a broken
    # config write, a broken payload, or a hook path that silently no-ops) -
    # fail loudly rather than reporting a vacuous success.
    if not any_row_blocked:
        print(
            "ERROR: zero corpus rows actually blocked - the harness is not "
            "exercising the hook (every invocation returned ALLOW). This is "
            "not a real pass; check .agentic/config.json isolation and the "
            "hook path.",
            file=sys.stderr,
        )
        return 1

    if failed == 0:
        print("All corpus rows passed.")
        return 0

    print(f"{failed} corpus row(s) FAILED.")
    return 1


if __name__ == "__main__":
    sys.exit(main())
