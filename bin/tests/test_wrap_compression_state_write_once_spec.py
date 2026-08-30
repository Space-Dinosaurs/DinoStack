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

Each assertion below is labeled [PIN] (asserts prose is present, not a
computed regression from a prior bug). Mutation-tested against a mutated
copy of this branch's own `content/commands/ds-wrap.md` (see the mutation
named in each docstring); pre-fix baseline is `origin/main`, where step
4(e) contains none of this language at all.

Run with: python3 -m pytest bin/tests/test_wrap_compression_state_write_once_spec.py -q
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WRAP_MD = REPO_ROOT / "content" / "commands" / "ds-wrap.md"


def _read() -> str:
    assert WRAP_MD.is_file(), f"expected file not found: {WRAP_MD}"
    return WRAP_MD.read_text(encoding="utf-8")


def test_step_4e_is_pinned_as_the_sole_write_point() -> None:
    """[PIN] Step 4(e) must state it is the sole point in Part E, on
    either path, permitted to create or advance
    `last_compressed_size_bytes`.

    Mutation that reddens this: delete the sentence "This sub-step is the
    sole point in Part E - on either path, sync or async - permitted to
    create or advance `last_compressed_size_bytes`..." from step 4(e),
    leaving only the plain "Update `[cwd]/.agentic/compression-state.json`
    with `last_compressed_size_bytes` set to..." instruction (i.e. revert
    to the pre-DS-221-round-2 text). Confirmed to redden by testing
    against the unmodified origin/main copy of this file, which contains
    no such sentence at all.
    """
    text = _read()
    assert (
        "is the sole point in Part E - on either path, sync or async - "
        "permitted to create or advance `last_compressed_size_bytes`"
        in text
    ), (
        "step 4(e) no longer states it is the sole point in Part E "
        "(on either path) permitted to create or advance "
        "last_compressed_size_bytes - the write-once invariant's scope "
        "clause has been deleted or reworded away"
    )


def test_step_4e_enumerates_every_way_the_chain_can_stop_short() -> None:
    """[PIN] Step 4(e) must enumerate the specific ways the chain can
    stop short of reaching the write (re-route exhaustion, the ignore
    guard, a lock-acquisition failure, a staleness-guard discard, or the
    session ending mid-chain) and require the target's entry be left
    untouched in every one of them.

    Mutation that reddens this: narrow the enumeration to only one named
    stop-short path (e.g. keep "re-route exhaustion" but delete "a
    lock-acquisition failure" and "a staleness-guard discard"), which
    would leave those async-path-specific failure modes structurally
    unprotected. Confirmed to redden by testing against origin/main,
    which has no such enumeration.
    """
    text = _read()
    assert (
        "Every other way this chain can stop short of here - re-route "
        "exhaustion, the ignore guard, a lock-acquisition failure, a "
        "staleness-guard discard, or the session ending mid-chain"
        in text
    ), (
        "step 4(e) no longer enumerates re-route exhaustion / ignore "
        "guard / lock-acquisition failure / staleness-guard discard / "
        "session-ending-mid-chain as the stop-short paths that must "
        "leave the compression-state.json entry untouched"
    )


def test_step_4e_forbids_creating_or_touching_the_entry_on_any_stop_short_path() -> None:
    """[PIN] Step 4(e) must require that every stop-short path leave the
    target's `compression-state.json` entry byte-for-byte as found -
    covering both the "entry does not yet exist" case (never create one)
    and the "entry already exists" case (never touch it).

    Mutation that reddens this: weaken "never create a new entry, never
    touch an existing one" to only one half (e.g. drop "never create a
    new entry", which would leave a first-ever-compression target
    unprotected against a partial write on a stop-short path, since that
    target has no pre-existing entry to compare against). Confirmed to
    redden by testing against origin/main, which has neither clause.
    """
    text = _read()
    assert (
        "must leave the target's `compression-state.json` entry, "
        "whether it already exists or does not, byte-for-byte as it "
        "found it: never create a new entry, never touch an existing one"
        in text
    ), (
        "step 4(e) no longer requires every stop-short path to leave "
        "the target's compression-state.json entry byte-for-byte as "
        "found (both the never-create-new and never-touch-existing "
        "halves) - a partial write on a stop-short path could "
        "reintroduce a false negative-baseline-move signal"
    )

