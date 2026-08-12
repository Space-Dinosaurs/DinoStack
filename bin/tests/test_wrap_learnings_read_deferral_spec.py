#!/usr/bin/env python3
"""
Spec test for the "defer `.agentic/learnings.md` read" perf change to
`/ds-wrap` (extracted from the abandoned PR #629, which bundled this change
with an unrelated and reverted Part E concurrency change).

The invariant: `.agentic/learnings.md` is a growing, unbounded knowledge log
(~295 KB / ~73K tokens observed live). Step 0 previously read its full
content unconditionally, before Step 0.5 ever determined the session's
route - paying that cost even on the light path and the ordinary
zero-substance path, neither of which ever consumes it. This change moves
the full read to immediately before the draft-Worker spawn, conditioned on
"a draft Worker is being spawned" (the already-determined route), covering
both the standard path's Step 1 and the zero-substance path's staging-drain
exception (Step 0.5) - not on a re-derivation of Step 0.5's routing
criteria, which `content/commands/ds-wrap.md` Step 0-pre states are defined
"here and only here".

Why `reach_model.py` is NOT the vehicle for this pin: that model's own
docstring scopes it to the Step 0.5 routing decision only, not to
within-Step-0/Step-1 read ordering. This is pinned here instead as a
literal prose-content spec test against `content/commands/ds-wrap.md`, the
same pattern `test_skeptic_spawn_global_context_spec.py` uses for the
Global-context inputs block.

Four assertions pinned:

1. Step 0 no longer performs the full `.agentic/learnings.md` read (its
   unconditional-reads sentence, and its own dedicated bullet, no longer
   claim a full read there).
2. The Step 0-pre short-circuit's skipped-reads list no longer names
   `learnings.md` among what it skips (it never read it in the first
   place after this change, so it cannot be a thing the short-circuit
   "skips").
3. The full read is mandated at the draft-Worker spawn site (Step 1), and
   the zero-substance path's staging-drain exception (Step 0.5) is stated
   to reuse that same site's read.
4. The new read's condition is expressed in terms of the already-determined
   route ("a draft Worker is being spawned"), not a restatement of Step
   0.5's light-path/zero-substance criteria.

Each assertion below is labeled [PIN] (asserts prose is present/absent, not
a computed regression from a prior bug) or [REGRESSION] (guards against a
specific reverted defect). Mutation-tested against a mutated copy of this
branch's own `content/commands/ds-wrap.md`; pre-fix baseline is
`origin/main` (where the full pre-change text still reads `.agentic/learnings.md`
unconditionally in Step 0).

Run with: python3 -m pytest bin/tests/test_wrap_learnings_read_deferral_spec.py -q
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WRAP_MD = REPO_ROOT / "content" / "commands" / "ds-wrap.md"


def _read() -> str:
    assert WRAP_MD.is_file(), f"expected file not found: {WRAP_MD}"
    return WRAP_MD.read_text(encoding="utf-8")


def test_step0_no_longer_reads_learnings_md_unconditionally() -> None:
    """[PIN] Step 0's own unconditional-reads sentence must no longer list
    `.agentic/learnings.md` alongside `.agentic/compression-state.json`,
    and the dedicated Step 0 bullet must explicitly say the read does NOT
    happen there."""
    text = _read()
    assert (
        "reads `.agentic/compression-state.json` in full, and runs a "
        "`gh pr list` network call" in text
    ), (
        "Step 0's unconditional-reads sentence no longer isolates "
        "compression-state.json - learnings.md may have been re-added to "
        "the unconditional list"
    )
    assert (
        "reads `.agentic/compression-state.json` and `.agentic/learnings.md` "
        "in full" not in text
    ), (
        "REGRESSION: Step 0's unconditional-reads sentence again claims a "
        "full unconditional learnings.md read - the deferral was reverted"
    )
    assert "**Do NOT read `.agentic/learnings.md` here**" in text, (
        "Step 0's dedicated learnings.md bullet no longer states that the "
        "read is deferred away from Step 0"
    )


def test_step0_pre_short_circuit_no_longer_names_learnings_in_skip_list() -> None:
    """[PIN] Step 0-pre's short-circuit describes what it skips by skipping
    the remainder of Step 0. Since Step 0 no longer performs the
    learnings.md read at all, the short-circuit's list of what it skips
    must not still name it - a stale cross-reference implies the read was
    still happening in Step 0 (and being skipped), which is false post-fix."""
    text = _read()
    assert (
        "skipping the remainder of Step 0 (the AGENTS.md/compression-state.json "
        "reads) and the `gh pr list` call entirely" in text
    ), (
        "the Step 0-pre short-circuit's skip-list no longer matches the "
        "expected post-fix wording"
    )
    assert (
        "AGENTS.md/compression-state.json/learnings.md reads" not in text
    ), (
        "REGRESSION: the Step 0-pre short-circuit's skip-list again names "
        "learnings.md - stale cross-reference reintroduced (this is the "
        "exact fourth stale-reference defect fixed by upstream commit "
        "9a945208 on the original branch)"
    )


def test_learnings_md_read_is_gated_behind_the_draft_worker_spawn() -> None:
    """[PIN] Every route that reaches a draft-Worker spawn - the standard
    path's Step 1, and the zero-substance path's staging-drain exception
    (Step 0.5) using "this same template" - performs the deferred
    `.agentic/learnings.md` read at that spawn, and ONLY at that spawn. If a
    future edit adds a third draft-Worker spawn site without carrying this
    same read-gate forward, or drops the staging-drain exception's use of
    "this same template", the read could silently go missing on that path -
    not caught by `reach_model.py`, whose docstring scopes it to the
    routing decision only, not to within-Part-B step ordering.

    [REGRESSION, positional] An earlier version of this test used only
    unanchored `in text` membership checks. A reviewer mutation-proved the
    gap: deleting the read paragraph from its Step 1 position and
    re-appending it verbatim at EOF (after Part G, where the read would
    happen long after the spawn and be useless) left all four membership
    assertions green. The positional assertion below fails that exact
    mutation by requiring the read note to appear AFTER the "**Step 1 —
    Spawn a draft Worker**" heading (it describes the read that happens
    "here", at Step 1) but BEFORE the full "**Step 2 — When the draft
    Worker returns, spawn a fresh Skeptic**" heading (so it is pinned into
    Step 1's own block, not merely somewhere earlier in the document, and
    cannot have drifted past the spawn site to EOF). The full Step 2
    heading is used rather than the bare "**Step 2" prefix because a
    prefix is not self-delimiting: `str.index` returns the first match,
    so a future "**Step 2..." bold appearing anywhere earlier in the
    document - including inside the Worker prompt template this window
    spans - would silently narrow the window rather than fail loudly.

    [REGRESSION, positional] A second reviewer mutation proved the window
    above is wider than its own docstring claims: relocating the read
    paragraph to sit immediately before the Step 2 heading (i.e. after the
    entire Worker prompt template, including the "**Existing learnings:**"
    field the read exists to populate) still passed `step1_pos <
    read_note_pos < step2_pos`, because that position is still "somewhere
    inside Step 1's block". The read only serves its purpose if it
    precedes the template field it populates, so the assertion below
    additionally pins the read note BEFORE the "**Existing learnings:**"
    field."""
    text = _read()
    assert (
        "This is the sole point where its full content is read" in text
    ), "Step 1 no longer claims to be the sole read site for learnings.md"
    assert (
        "deferred this far specifically because only a draft-Worker spawn "
        "consumes it" in text
    ), "Step 1 no longer ties the deferred read to the draft-Worker spawn"
    assert (
        "The zero-substance path's staging-drain exception (Step 0.5) also "
        "spawns a draft Worker from this same template and must perform "
        "this same read first when it does" in text
    ), (
        "the zero-substance staging-drain exception no longer states that "
        "it reuses the Step 1 draft-Worker template and its learnings.md "
        "read - a second draft-Worker spawn site could silently drop the "
        "read"
    )
    assert (
        "still spawn the draft Worker and Skeptic, but scoped to Output 2 "
        "only" in text
    ), (
        "the zero-substance path's staging-drain exception no longer "
        "spawns a draft Worker at all - the learnings-read gate above "
        "would then be dead code on that path"
    )

    do_not_read_marker = "**Do NOT read `.agentic/learnings.md` here**"
    step1_heading = "**Step 1 — Spawn a draft Worker**"
    step2_heading = "**Step 2 — When the draft Worker returns, spawn a fresh Skeptic**"
    read_note = "This is the sole point where its full content is read"
    existing_learnings_field = "**Existing learnings:**"
    assert do_not_read_marker in text, (
        "Step 0's 'Do NOT read learnings.md here' bullet is missing - "
        "cannot anchor the positional window"
    )
    assert step1_heading in text, (
        "the 'Step 1 — Spawn a draft Worker' heading is missing - cannot "
        "anchor the positional window"
    )
    assert step2_heading in text, (
        "the 'Step 2 — When the draft Worker returns, spawn a fresh "
        "Skeptic' heading is missing - cannot anchor the positional window"
    )
    assert existing_learnings_field in text, (
        "the '**Existing learnings:**' Worker-prompt-template field is "
        "missing - cannot anchor the positional window"
    )
    do_not_read_pos = text.index(do_not_read_marker)
    step1_pos = text.index(step1_heading)
    step2_pos = text.index(step2_heading)
    read_note_pos = text.index(read_note)
    existing_learnings_pos = text.index(existing_learnings_field)
    assert do_not_read_pos < step1_pos, (
        "Step 0's 'Do NOT read ... here' bullet no longer precedes the "
        "'Step 1 — Spawn a draft Worker' heading - document structure has "
        "changed in a way this test's anchors no longer reflect"
    )
    assert step1_pos < read_note_pos < step2_pos, (
        "REGRESSION: the deferred learnings.md read note is not positioned "
        "strictly between the 'Step 1 — Spawn a draft Worker' heading and "
        "the 'Step 2' heading - it may have drifted past Step 1's own "
        "block (e.g. relocated to EOF, after Part G), which would make "
        "the read happen too late to serve the draft-Worker spawn it "
        "claims to gate"
    )
    assert read_note_pos < existing_learnings_pos, (
        "REGRESSION: the deferred learnings.md read note no longer "
        "precedes the '**Existing learnings:**' Worker-prompt-template "
        "field it exists to populate - it may have drifted to somewhere "
        "later in Step 1's block (e.g. immediately before Step 2, after "
        "the entire prompt template), which would make the read happen "
        "too late to serve the field it is supposed to fill"
    )


def test_new_read_condition_does_not_restate_step_0_5_criteria() -> None:
    """[PIN] The new read site must express its condition as "a draft
    Worker is being spawned" (the already-determined route), never as a
    restatement of Step 0.5's light-path/zero-substance trigger criteria -
    `content/commands/ds-wrap.md` Step 0-pre states those criteria are
    defined "here and only here"; a restatement elsewhere is a drift
    defect even when currently accurate."""
    text = _read()
    assert (
        "conditioned on the route already determined by Step 0.5, not on "
        "a re-evaluation of Step 0.5's criteria" in text
    ), (
        "Step 0's learnings.md bullet no longer states that the deferred "
        "read is conditioned on the already-determined route rather than "
        "a re-evaluation of Step 0.5's criteria"
    )
    # Regression guard: the new read site must not restate Step 0.5's own
    # trigger predicates (e.g. re-deriving "no file-mutating tool calls").
    assert (
        "No file-mutating tool calls and no git commits this session" not in
        text[text.index("**Step 1 — Spawn a draft Worker**"):]
        if "**Step 1 — Spawn a draft Worker**" in text
        else True
    ), (
        "REGRESSION: the Step 1 read-deferral note appears to restate "
        "Step 0.5's light-path/zero-substance trigger criteria instead of "
        "conditioning on the already-determined route"
    )
