#!/usr/bin/env python3
"""
Spec test for DS-221's write-once invariant on
`compression-state.json`'s `last_compressed_size_bytes` field, added to
`content/commands/ds-wrap.md` Part E step 4(e) (round 2, commit
`aac6189c`).

Why this is pinned as prose rather than exercised as behavior: Part E step
4 is conductor prose, not a tested code path - there is no harness here
that drives a real `/ds-wrap` Part E run end to end (the sync path needs a
live `/ds-wrap` session; the async path needs a live
`/ds-implement-ticket` Phase 11b conductor). Pinned here instead as a
literal prose-content spec test against `content/commands/ds-wrap.md`,
the same pattern `test_wrap_learnings_read_deferral_spec.py` uses for the
analogous single-invariant prose change to this same file.

The invariant under test: step 4(e) is the SOLE point in Part E - on
either path, sync or async - permitted to create or advance
`last_compressed_size_bytes` for a target. DS-221's underlying defect (a
false negative-signal every re-tripped run) recurred five times in
production because nothing in the prose held this contract; a future
edit or reflow could delete the sentence with every existing gate green,
since no code path exercises Part E prose today.

[REGRESSION, positional] Round 3 (commit `62225f4c`) pinned all three
clauses below with unanchored whole-file `in text` membership checks. A
reviewer mutation-proved the gap: deleting the entire invariant block from
step 4(e) and re-appending it verbatim at EOF (under an archived-note
comment) left all three assertions green, while step 4(e) itself had
reverted to its pre-DS-221 text. This is the exact relocate-to-EOF defect
class `test_wrap_learnings_read_deferral_spec.py`'s own docstring records
being found and fixed twice against this same file (see that file's
`test_learnings_md_read_is_gated_behind_the_draft_worker_spawn`) - round 3
reintroduced it in a sibling file instead of inheriting the fixed shape.
The three assertions below are now bound positionally: each pinned
string's index must fall strictly between the index of step 4(e)'s own
"- (d) Overwrite `FILE.md`" bullet and the index of the "**Async-path
amendment (deliberate, ...)" heading that follows step 4(e) - the window
that is step 4(e)'s own block. The end-of-window anchor uses the FULL bold
heading text, not a bare "**Async-path amendment" prefix: a prefix is not
self-delimiting (`str.index` returns the first match, and the bare phrase
"Async-path amendment" also appears, unbolded, in two earlier cross-
references above step 4 - see `test_end_anchor_is_not_a_bare_prefix`
below), so a future edit adding an earlier bolded occurrence of that
prefix would silently narrow or invalidate the window rather than fail
loudly.

Each assertion below is labeled [PIN] (asserts prose is present, not a
computed regression from a prior bug) unless marked [REGRESSION].
Mutation-tested against a mutated copy of this branch's own
`content/commands/ds-wrap.md` (see the mutation named in each docstring);
pre-fix baseline is `origin/main`, where step 4(e) contains none of this
language at all.

Run with: python3 -m pytest bin/tests/test_wrap_compression_state_write_once_spec.py -q
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WRAP_MD = REPO_ROOT / "content" / "commands" / "ds-wrap.md"

STEP_4E_START = "- (d) Overwrite `FILE.md`"
STEP_4E_END = (
    "**Async-path amendment (deliberate, not a silent exception - the "
    "conductor is the writer on BOTH paths, no separate third agent for "
    "the write).**"
)


def _read() -> str:
    assert WRAP_MD.is_file(), f"expected file not found: {WRAP_MD}"
    return WRAP_MD.read_text(encoding="utf-8")


def _step_4e_window(text: str) -> tuple[int, int]:
    assert STEP_4E_START in text, (
        "step 4(e)'s own start anchor ('- (d) Overwrite `FILE.md`') is "
        "missing - cannot bound the positional window"
    )
    assert STEP_4E_END in text, (
        "the full 'Async-path amendment (deliberate, ...)' heading that "
        "follows step 4(e) is missing - cannot bound the positional "
        "window"
    )
    start = text.index(STEP_4E_START)
    end = text.index(STEP_4E_END)
    assert start < end, (
        "step 4(e)'s start anchor no longer precedes the Async-path "
        "amendment heading - document structure has changed in a way "
        "this test's anchors no longer reflect"
    )
    return start, end


def test_end_anchor_is_not_a_bare_prefix() -> None:
    """Sanity check on the test's own anchors: the bare phrase "Async-path
    amendment" (unbolded) appears elsewhere in the document (two forward
    cross-references above step 4), so the full bolded heading text is
    used as the end-of-window anchor rather than that bare prefix. This
    guards the test file itself against silently regressing to the
    prefix form the docstring above warns against."""
    text = _read()
    assert text.count("Async-path amendment") >= 2, (
        "expected the bare phrase 'Async-path amendment' to appear more "
        "than once in the document (forward cross-references plus the "
        "heading itself) - if this no longer holds, the prefix-vs-full-"
        "heading distinction this test relies on may no longer apply"
    )
    assert STEP_4E_END in text


def test_step_4e_is_pinned_as_the_sole_write_point() -> None:
    """[PIN, positional] Step 4(e) must state it is the sole point in
    Part E, on either path, permitted to create or advance
    `last_compressed_size_bytes`, and that statement must sit inside step
    4(e)'s own block (between the "(d) Overwrite `FILE.md`" bullet and
    the "Async-path amendment" heading that follows it).

    Mutation that reddens this: delete the sentence "This sub-step is the
    sole point in Part E - on either path, sync or async - permitted to
    create or advance `last_compressed_size_bytes`..." from step 4(e),
    leaving only the plain "Update `[cwd]/.agentic/compression-state.json`
    with `last_compressed_size_bytes` set to..." instruction (i.e. revert
    to the pre-DS-221-round-2 text). Confirmed to redden by testing
    against the unmodified origin/main copy of this file, which contains
    no such sentence at all.

    [REGRESSION, positional] Also reddens against the round-3 mutation:
    deleting this sentence (with the rest of the invariant block) from
    step 4(e) and re-appending it verbatim at EOF places its index after
    `STEP_4E_END`, outside the window, so the positional bound below
    catches it even though the unanchored substring check alone would
    not.
    """
    text = _read()
    start, end = _step_4e_window(text)
    needle = (
        "is the sole point in Part E - on either path, sync or async - "
        "permitted to create or advance `last_compressed_size_bytes`"
    )
    assert needle in text, (
        "step 4(e) no longer states it is the sole point in Part E "
        "(on either path) permitted to create or advance "
        "last_compressed_size_bytes - the write-once invariant's scope "
        "clause has been deleted or reworded away"
    )
    pos = text.index(needle)
    assert start < pos < end, (
        "REGRESSION: the sole-write-point sentence exists in the "
        "document but is no longer positioned inside step 4(e)'s own "
        "block - it may have drifted out of step 4(e) (e.g. relocated "
        "to EOF), which would make the pin decorative rather than "
        "enforcing the invariant where it is actually read"
    )


def test_step_4e_enumerates_every_way_the_chain_can_stop_short() -> None:
    """[PIN, positional] Step 4(e) must enumerate the specific ways the
    chain can stop short of reaching the write (re-route exhaustion, the
    ignore guard, a lock-acquisition failure, a staleness-guard discard,
    or the session ending mid-chain) and require the target's entry be
    left untouched in every one of them, and that enumeration must sit
    inside step 4(e)'s own block.

    Mutation that reddens this: narrow the enumeration to only one named
    stop-short path (e.g. keep "re-route exhaustion" but delete "a
    lock-acquisition failure" and "a staleness-guard discard"), which
    would leave those async-path-specific failure modes structurally
    unprotected. Confirmed to redden by testing against origin/main,
    which has no such enumeration.

    [REGRESSION, positional] Also reddens against the round-3 mutation
    (delete-from-step-4e, re-append verbatim at EOF): the enumeration's
    index then falls after `STEP_4E_END`, outside the window.
    """
    text = _read()
    start, end = _step_4e_window(text)
    needle = (
        "Every other way this chain can stop short of here - re-route "
        "exhaustion, the ignore guard, a lock-acquisition failure, a "
        "staleness-guard discard, or the session ending mid-chain"
    )
    assert needle in text, (
        "step 4(e) no longer enumerates re-route exhaustion / ignore "
        "guard / lock-acquisition failure / staleness-guard discard / "
        "session-ending-mid-chain as the stop-short paths that must "
        "leave the compression-state.json entry untouched"
    )
    pos = text.index(needle)
    assert start < pos < end, (
        "REGRESSION: the stop-short enumeration exists in the document "
        "but is no longer positioned inside step 4(e)'s own block - it "
        "may have drifted out of step 4(e) (e.g. relocated to EOF), "
        "which would make the pin decorative rather than enforcing the "
        "invariant where it is actually read"
    )


def test_step_4e_forbids_creating_or_touching_the_entry_on_any_stop_short_path() -> None:
    """[PIN, positional] Step 4(e) must require that every stop-short
    path leave the target's `compression-state.json` entry byte-for-byte
    as found - covering both the "entry does not yet exist" case (never
    create one) and the "entry already exists" case (never touch it) -
    and that requirement must sit inside step 4(e)'s own block.

    Mutation that reddens this: weaken "never create a new entry, never
    touch an existing one" to only one half (e.g. drop "never create a
    new entry", which would leave a first-ever-compression target
    unprotected against a partial write on a stop-short path, since that
    target has no pre-existing entry to compare against). Confirmed to
    redden by testing against origin/main, which has neither clause.

    [REGRESSION, positional] Also reddens against the round-3 mutation
    (delete-from-step-4e, re-append verbatim at EOF): the requirement's
    index then falls after `STEP_4E_END`, outside the window.
    """
    text = _read()
    start, end = _step_4e_window(text)
    needle = (
        "must leave the target's `compression-state.json` entry, "
        "whether it already exists or does not, byte-for-byte as it "
        "found it: never create a new entry, never touch an existing one"
    )
    assert needle in text, (
        "step 4(e) no longer requires every stop-short path to leave "
        "the target's compression-state.json entry byte-for-byte as "
        "found (both the never-create-new and never-touch-existing "
        "halves) - a partial write on a stop-short path could "
        "reintroduce a false negative-baseline-move signal"
    )
    pos = text.index(needle)
    assert start < pos < end, (
        "REGRESSION: the never-create/never-touch requirement exists in "
        "the document but is no longer positioned inside step 4(e)'s "
        "own block - it may have drifted out of step 4(e) (e.g. "
        "relocated to EOF), which would make the pin decorative rather "
        "than enforcing the invariant where it is actually read"
    )
