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

[REGRESSION, round 3 -> round 4 -> round 5] Three consecutive review
rounds found the same class of gap in this test file's OWN verification
apparatus, not in the fix it protects:

- Round 3 (`62225f4c`) pinned all three clauses below with unanchored
  whole-file `in text` membership checks. A reviewer mutation-proved the
  gap: deleting the entire invariant block from step 4(e) and
  re-appending it verbatim at EOF (under an archived-note comment) left
  all three assertions green, while step 4(e) itself had reverted to its
  pre-DS-221 text.

- Round 4 (`2474767b`) replaced the whole-file check with a positional
  window bound by two string anchors: the start anchor was step 4(e)'s
  OWN "- (d) Overwrite `FILE.md`" bullet marker (one bullet too early)
  and the end anchor was the "Async-path amendment" heading. A reviewer
  mutation-proved the gap: relocating the entire invariant block from the
  (e) bullet into the END of the (d) bullet left all three assertions
  green (the block's index still fell inside the (d)-(e) window), while
  step 4(e) itself reverted to byte-identical pre-DS-221 text and the
  "sole point" self-reference now sat on the (d) bullet, which writes
  `FILE.md` and never touches `compression-state.json` at all - a
  structurally false self-reference the window could not detect, because
  the window was never actually step 4(e)'s own block.

- Round 5 (this file) replaces window arithmetic with EXTRACTION: locate
  step 4(e)'s own bullet by its unique "- (e)" marker, then bound its end
  at the next sibling bullet marker or block-ending bold heading -
  whichever comes first - via `_extract_step_4e_bullet()`. There is no
  hand-picked neighbouring-bullet start anchor and no end-anchor string
  to get subtly wrong: the extraction fails loudly (via a `pytest.fail`
  in `_extract_step_4e_bullet`) if the marker is missing, if more than
  one candidate marker exists, or if no boundary can be found after it -
  it never silently widens the region. All three content assertions
  below are now evaluated strictly `in` the extracted bullet substring,
  not the whole document and not a hand-bounded window.

Each assertion below is labeled [PIN] (asserts prose is present, not a
computed regression from a prior bug) unless marked [REGRESSION].
Mutation-tested against a mutated copy of this branch's own
`content/commands/ds-wrap.md` (see the mutation named in each docstring);
pre-fix baseline is `origin/main`, where step 4(e) contains none of this
language at all.

Run with: python3 -m pytest bin/tests/test_wrap_compression_state_write_once_spec.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WRAP_MD = REPO_ROOT / "content" / "commands" / "ds-wrap.md"

# Matches step 4(e)'s own bullet marker at the start of a line, e.g.
# "   - (e) **Write `last_compressed_size_bytes` only here...".
STEP_4E_MARKER_RE = re.compile(r"^[ \t]*-\s*\(e\)(?=\s)", re.MULTILINE)

# A boundary that ends step 4(e)'s own block: either the next sibling
# list-item marker ("- (a)".."- (z)") or a bold heading starting a line
# (e.g. "**Async-path amendment..."), whichever comes first after the
# (e) marker. Anchored on line-start ("^[ \t]*") so an inline "**" or
# "- (x)" appearing mid-sentence inside the bullet's own prose (there is
# none today, but nothing guarantees that forever) can never be mistaken
# for a sibling boundary. Uses a `(?=\s)` lookahead rather than `\b`
# after the closing paren - `)` followed by whitespace is two non-word
# characters, so `\b` never matches there and silently produces zero
# matches (found during this test's own development).
NEXT_BOUNDARY_RE = re.compile(r"^[ \t]*(?:-\s*\([a-z]\)(?=\s)|\*\*)", re.MULTILINE)


def _read() -> str:
    assert WRAP_MD.is_file(), f"expected file not found: {WRAP_MD}"
    return WRAP_MD.read_text(encoding="utf-8")


def _extract_step_4e_bullet(text: str) -> str:
    """Extract step 4(e)'s own bullet text, and nothing else, from
    `content/commands/ds-wrap.md`.

    Fails loudly (never silently widens the region) when:
    - the "- (e)" marker is missing entirely,
    - more than one candidate "- (e)" marker exists (ambiguous - cannot
      uniquely locate the bullet), or
    - no boundary (next sibling bullet or bold heading) can be found
      after the marker, so the end of the bullet cannot be resolved.
    """
    markers = list(STEP_4E_MARKER_RE.finditer(text))
    if len(markers) != 1:
        pytest.fail(
            f"expected exactly one step 4(e) bullet marker ('- (e)') in "
            f"{WRAP_MD}, found {len(markers)} - cannot uniquely locate "
            "the bullet to extract"
        )
    marker = markers[0]
    start = marker.start()
    boundary = NEXT_BOUNDARY_RE.search(text, marker.end())
    if boundary is None:
        pytest.fail(
            "could not find a boundary (next sibling bullet marker or "
            "bold heading) after step 4(e)'s own marker - cannot resolve "
            "where the bullet ends without risking silently including "
            "unrelated trailing document content"
        )
    end = boundary.start()
    assert start < end, (
        "resolved end boundary does not follow the step 4(e) start "
        "marker - document structure has changed in a way this "
        "extraction no longer reflects"
    )
    bullet = text[start:end]
    assert bullet.strip(), "extracted step 4(e) bullet region is empty"
    return bullet


def test_extraction_finds_exactly_one_bullet_smaller_than_the_document() -> None:
    """Sanity check on the extraction itself, independent of its content:
    exactly one step 4(e) bullet must be found, and the extracted region
    must be a strict, non-trivial substring of the whole document (i.e.
    the extraction actually narrowed something down, rather than falling
    back to the full file)."""
    text = _read()
    markers = list(STEP_4E_MARKER_RE.finditer(text))
    assert len(markers) == 1, (
        f"expected exactly one step 4(e) bullet marker, found "
        f"{len(markers)}"
    )
    bullet = _extract_step_4e_bullet(text)
    assert 0 < len(bullet) < len(text), (
        "extracted step 4(e) bullet must be a non-empty, strict subset "
        "of the whole document"
    )


def test_step_4e_is_pinned_as_the_sole_write_point() -> None:
    """[PIN] Step 4(e) must state it is the sole point in Part E, on
    either path, permitted to create or advance
    `last_compressed_size_bytes`, and that statement must live inside
    step 4(e)'s own extracted bullet.

    Mutation that reddens this: delete the sentence "This sub-step is the
    sole point in Part E - on either path, sync or async - permitted to
    create or advance `last_compressed_size_bytes`..." from step 4(e),
    leaving only the plain "Update `[cwd]/.agentic/compression-state.json`
    with `last_compressed_size_bytes` set to..." instruction (i.e. revert
    to the pre-DS-221-round-2 text). Confirmed to redden against the
    unmodified `origin/main` copy of this file, which contains no such
    sentence at all.

    [REGRESSION] Also reddens against both prior rounds' defeating
    mutations: relocating this sentence (with the rest of the invariant
    block) to EOF (round 3's mutation), or to the END of the (d) bullet
    (round 4's mutation), removes it from the extracted (e)-only
    substring entirely - there is no window that could still contain it
    by accident.
    """
    bullet = _extract_step_4e_bullet(_read())
    needle = (
        "is the sole point in Part E - on either path, sync or async - "
        "permitted to create or advance `last_compressed_size_bytes`"
    )
    assert needle in bullet, (
        "step 4(e) no longer states it is the sole point in Part E "
        "(on either path) permitted to create or advance "
        "last_compressed_size_bytes - the write-once invariant's scope "
        "clause has been deleted, reworded away, or relocated outside "
        "step 4(e)'s own bullet"
    )


def test_step_4e_enumerates_every_way_the_chain_can_stop_short() -> None:
    """[PIN] Step 4(e) must enumerate the specific ways the chain can
    stop short of reaching the write (re-route exhaustion, the ignore
    guard, a lock-acquisition failure, a staleness-guard discard, or the
    session ending mid-chain) and require the target's entry be left
    untouched in every one of them, and that enumeration must live inside
    step 4(e)'s own extracted bullet.

    Mutation that reddens this: narrow the enumeration to only one named
    stop-short path (e.g. keep "re-route exhaustion" but delete "a
    lock-acquisition failure" and "a staleness-guard discard"), which
    would leave those async-path-specific failure modes structurally
    unprotected. Confirmed to redden against `origin/main`, which has no
    such enumeration.

    [REGRESSION] Also reddens against both prior rounds' defeating
    mutations (relocate-to-EOF, relocate-into-(d)): the enumeration is
    then absent from the extracted (e)-only substring.
    """
    bullet = _extract_step_4e_bullet(_read())
    needle = (
        "Every other way this chain can stop short of here - re-route "
        "exhaustion, the ignore guard, a lock-acquisition failure, a "
        "staleness-guard discard, or the session ending mid-chain"
    )
    assert needle in bullet, (
        "step 4(e) no longer enumerates re-route exhaustion / ignore "
        "guard / lock-acquisition failure / staleness-guard discard / "
        "session-ending-mid-chain as the stop-short paths that must "
        "leave the compression-state.json entry untouched, or that "
        "enumeration has been relocated outside step 4(e)'s own bullet"
    )


def test_step_4e_forbids_creating_or_touching_the_entry_on_any_stop_short_path() -> None:
    """[PIN] Step 4(e) must require that every stop-short path leave the
    target's `compression-state.json` entry byte-for-byte as found -
    covering both the "entry does not yet exist" case (never create one)
    and the "entry already exists" case (never touch it) - and that
    requirement must live inside step 4(e)'s own extracted bullet.

    Mutation that reddens this: weaken "never create a new entry, never
    touch an existing one" to only one half (e.g. drop "never create a
    new entry", which would leave a first-ever-compression target
    unprotected against a partial write on a stop-short path, since that
    target has no pre-existing entry to compare against). Confirmed to
    redden against `origin/main`, which has neither clause.

    [REGRESSION] Also reddens against both prior rounds' defeating
    mutations (relocate-to-EOF, relocate-into-(d)): the requirement is
    then absent from the extracted (e)-only substring.
    """
    bullet = _extract_step_4e_bullet(_read())
    needle = (
        "must leave the target's `compression-state.json` entry, "
        "whether it already exists or does not, byte-for-byte as it "
        "found it: never create a new entry, never touch an existing one"
    )
    assert needle in bullet, (
        "step 4(e) no longer requires every stop-short path to leave "
        "the target's compression-state.json entry byte-for-byte as "
        "found (both the never-create-new and never-touch-existing "
        "halves), or that requirement has been relocated outside step "
        "4(e)'s own bullet - a partial write on a stop-short path could "
        "reintroduce a false negative-baseline-move signal"
    )
