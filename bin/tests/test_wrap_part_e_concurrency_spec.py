#!/usr/bin/env python3
"""
Spec test for the PR #629 Skeptic pass on `/ds-wrap` Part E's concurrent
compression pipeline (Majors 1 and 2 on the "defer learnings.md read and
parallelize Part E compression" change).

Why `reach_model.py` is NOT the vehicle for these pins: that model's own
docstring (bin/tests/reach_model.py:25-44) states it "deliberately does NOT
model the four lock-held mid-run escalations" at Part E and Step 3, since
those are mid-run Skeptic re-route/format-reinvocation limits occurring
INSIDE the draft-worker loop downstream of the routing decision the model
covers. The invariants pinned here (write-serialization, per-target Worker
brief labeling, and the Part E escalation/lock-release semantics) are all
inside that excluded scope, so they are pinned here instead as a literal
prose-content spec test against `content/commands/ds-wrap.md` - the same
pattern `test_skeptic_spawn_global_context_spec.py` uses for the
Global-context inputs block.

Three invariants pinned, one per Skeptic finding:

1. **Write-serialization clause** (Concurrency scope paragraph): Step 4 (the
   on-disk write sequence) is serialized within a target AND across targets,
   and is main-agent-only - never delegated to a subagent.

2. **Per-target-path requirement on the Worker brief** (Major 2): the
   compression Worker brief template must carry an explicit target-path
   field (not just "substituting ... file content"), so a Worker's return
   can be associated with its target unambiguously when N Workers are
   spawned in one message and return in arbitrary order.

3. **Escalation/lock-release semantics** (Major 1): a format- or
   re-route-limit escalation on one target, while sibling targets still have
   pipelines in flight, must not release the wrap lock (and therefore must
   not return control to the user) until every in-flight sibling target has
   resolved to either a completed step-4 write or a logged skip. Guards
   against a regression back to the ambiguous "does not pause or affect any
   other target's pipeline" wording this PR replaced.

Round-3 fix (this revision) closes a relocated defect in the round-2 fix
above: the Escalation quiescing procedure's own outcome enumeration was not
total, and its own headline contradicted its own qualifier. Two more
invariants pinned:

4. **Quiesced-skip is a third, explicit outcome** (Round-3 Major, Gap A):
   step 2's per-sibling outcome enumeration must be total - a sibling that
   is neither signed off nor has exhausted its own re-route/format budget,
   but for which step 1 bars the next round that would advance it, must
   resolve to a defined third outcome ("quiesced skip") treated identically
   to an escalated target for steps 3-5. Without this, that sibling has no
   reachable terminal state and step 5's termination predicate is
   unsatisfiable for it.

5. **Headline/qualifier agreement on first-Skeptic spawns** (Round-3 Major,
   Gap B): step 1's "stop spawning" headline must scope to re-route/format-
   re-invocation rounds only (matching its own qualifier), and must
   explicitly permit a sibling's first Skeptic spawn for a Worker that
   already returned before the escalation was detected - otherwise the
   headline and qualifier disagree about whether that spawn is allowed.

6. **Skeptic sign-off carries the same `Target:` prefix as the Worker
   brief** (Round-3 Minor 1): the Part E Skeptic brief's sign-off format
   must require a `Target: <path>` prefix line, mirroring the Worker
   brief's existing `Target:` echo-back requirement - otherwise sign-off
   attribution across N out-of-order Skeptic returns rests on free-form
   text while draft attribution is structurally pinned.

**Baseline note (Round-3 Minor 2 fix):** each assertion below is verified
against TWO baselines - `d8c6e677` (the pre-round-2-fix PR content, i.e.
the state Majors 1/2 were filed against) and `origin/main` (the state
before this PR branch existed at all, i.e. no concurrency feature, no
learnings.md deferral). All Round-2 assertions (tests 1-4 in this file)
fail against BOTH baselines - the earlier commit message's blanket claim
"all five assertions verified to fail against the pre-fix d8c6e677 file
content" was correct for four of the five, but test 5
(`test_learnings_md_read_is_gated_behind_the_draft_worker_spawn`) pins a
pre-existing invariant that `d8c6e677` ALREADY satisfies (it introduced the
deferral) - test 5 PASSES against `d8c6e677` and FAILS only against
`origin/main`. Executed independently for this fix: `python3 -c` running
each assertion set against both baseline file contents confirmed exactly
this split (4 fail/fail, 1 pass-on-d8c6e677/fail-on-origin-main). See that
test's own docstring, which already correctly called this a "pre-existing
engineer invariant (unpinned before this PR)" - only the commit message's
summary line overstated it as a fifth failing-pre-fix assertion.

Run with: python3 -m pytest bin/tests/test_wrap_part_e_concurrency_spec.py -q
"""

from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
WRAP_MD = REPO_ROOT / "content" / "commands" / "ds-wrap.md"


def _read() -> str:
    assert WRAP_MD.is_file(), f"expected file not found: {WRAP_MD}"
    return WRAP_MD.read_text(encoding="utf-8")


def test_step4_write_serialization_is_stated_once_and_referenced() -> None:
    """The 'main-agent-only and serialized ... within a target and across
    targets' invariant must be defined in the Concurrency scope paragraph,
    and the step-4 write-sequence paragraph must cite it rather than
    re-derive it (Minor: duplicated binding prose is a drift hazard here)."""
    text = _read()
    assert "**Concurrency scope.**" in text, (
        "the Concurrency scope paragraph (Part E) is missing entirely"
    )
    assert (
        "is the one part of this procedure that stays serialized and "
        "main-agent-only, per target and across targets alike" in text
    ), "Concurrency scope no longer states the write-serialization invariant"
    assert (
        "Serialization is exactly as stated in \"Concurrency scope\" above"
        in text
    ), (
        "the step-4 write paragraph no longer cites Concurrency scope for "
        "its serialization claim - it may have reverted to restating it "
        "(duplicated binding prose drift)"
    )


def test_worker_brief_carries_explicit_target_path_field() -> None:
    """The compression Worker brief template (Part E step 1) must contain an
    explicit target-path field the Worker echoes back, not just file
    content - otherwise N parallel Worker returns carry no target identity
    and the main agent cannot safely associate a draft with its file."""
    text = _read()
    assert "substituting that target's absolute path AND that target's own file content" in text, (
        "Part E step 1 no longer instructs substituting the target's "
        "absolute path into the Worker brief"
    )
    assert "> Target: [paste target's absolute path]" in text, (
        "the compression Worker brief template no longer has an explicit "
        "target-path field - a Worker's return cannot be safely associated "
        "with its target (MEMORY.md vs .agentic/memory.md overwrite risk)"
    )
    assert (
        "preceded by a single line `Target: <the absolute path given below>`"
        in text
    ), (
        "the Worker brief no longer instructs the Worker to echo its "
        "target path back in its return"
    )


def test_escalation_quiescing_procedure_is_defined() -> None:
    """A step-3 escalation on one target, while siblings are still in
    flight, must be defined explicitly: sibling pipelines already in flight
    run to their own conclusion, every target that reaches sign-off gets its
    step-4 write completed, every escalated target is skipped (not
    partially written), and the lock is released only after all targets have
    resolved - never at the moment the first escalation is detected."""
    text = _read()
    assert "**Escalation quiescing (NORMATIVE).**" in text, (
        "the Escalation quiescing procedure (Major 1 fix) is missing "
        "entirely from Part E"
    )
    assert (
        "does NOT mean `/ds-wrap` releases the lock and returns control "
        "at that instant" in text
    ), "Escalation quiescing no longer states the core non-instant-release rule"
    assert (
        "Only once every target has resolved to either a completed step-4 "
        "write or a logged skip does `/ds-wrap` release the lock" in text
    ), "Escalation quiescing no longer gates lock release on full resolution"
    # Regression guard: the ambiguous pre-fix wording must not resurface.
    assert "does not pause or affect any other target's pipeline" not in text, (
        "the ambiguous pre-fix escalation wording has resurfaced - Major 1 "
        "regression (both the quiescing procedure AND the old permissive "
        "claim would be present, which is self-contradictory)"
    )


def test_lock_release_clause_cross_references_escalation_quiescing() -> None:
    """The 'Lock release is mandatory on every exit path' list's Part E
    bullet must point at the Escalation quiescing procedure so a reader
    lands on the concurrent-pipeline definition of 'before /ds-wrap returns
    control', rather than the single-target-loop reading that was valid
    pre-parallelization but is now ambiguous/wrong."""
    text = _read()
    assert "Escalation quiescing procedure (Part E) has resolved every in-flight target" in text, (
        "the mandatory lock-release list no longer cross-references the "
        "Escalation quiescing procedure for the Part E bullet"
    )


def test_learnings_md_read_is_gated_behind_the_draft_worker_spawn() -> None:
    """Pre-existing engineer invariant (unpinned before this PR): every
    route that reaches a draft-Worker spawn - the standard path's Step 1,
    and the zero-substance path's staging-drain exception (Step 0.5) using
    "this same template" - performs the deferred `.agentic/learnings.md`
    read at that spawn, and ONLY at that spawn. If a future edit adds a
    third draft-Worker spawn site without carrying this same read-gate
    forward, or drops the staging-drain exception's use of "this same
    template", the read could silently go missing on that path (the exact
    failure mode DS-90's Step 0 deferral was designed to avoid regressing
    into) - not caught by `reach_model.py`, whose docstring scopes it to
    the routing decision only, not to within-Part-B step ordering."""
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


def test_escalation_quiescing_step2_enumeration_is_total() -> None:
    """Round-3 Major, Gap A: step 2 of Escalation quiescing must enumerate
    THREE outcomes for an in-flight sibling, not two. A sibling whose
    current round returned Critical/Major findings, that has neither
    signed off nor exhausted its own re-route/format budget, and for which
    step 1 bars the next round, needs an explicit third outcome
    ("quiesced skip") - otherwise that sibling has no reachable terminal
    state and step 5's "resolved to either a completed step-4 write or a
    logged skip" predicate is unsatisfiable for it."""
    text = _read()
    assert (
        "Let every already-in-flight sibling pipeline resolve to exactly "
        "one of these three outcomes" in text
    ), "step 2 no longer states a total three-outcome enumeration"
    assert "**Quiesced skip:**" in text, (
        "the third (quiesced-skip) outcome is missing from step 2's "
        "enumeration - a sibling with unresolved findings and a "
        "step-1-barred next round has no defined terminal state"
    )
    assert (
        "treated identically to an escalated target for the purposes of "
        "steps 3-5 below" in text
    ), (
        "the quiesced-skip outcome no longer states it is treated "
        "identically to an escalated target for steps 3-5"
    )
    # Step 4's do-not-write list must also count quiesced-skip targets,
    # not just the first escalation and separately-budget-exhausted siblings.
    assert (
        "any sibling that resolved to a quiesced skip during step 2" in text
    ), (
        "step 4's 'do NOT write anything for it' list no longer counts "
        "quiesced-skip targets - they would fall through with no defined "
        "write/skip disposition"
    )


def test_escalation_quiescing_step1_headline_permits_first_skeptic_spawn() -> None:
    """Round-3 Major, Gap B: step 1's headline ("stop spawning NEW ...
    rounds") must scope explicitly to re-route/format-re-invocation rounds,
    matching its own qualifier, and must explicitly state that a sibling's
    FIRST Skeptic spawn (for a Worker that already returned before the
    escalation was detected) is permitted - completing an already-in-flight
    initial pipeline, not starting a new round. Without this, the headline
    ("Stop spawning NEW Worker/Skeptic rounds") and the qualifier ("do not
    start a fresh re-route or format re-invocation") disagreed about
    whether that spawn was allowed."""
    text = _read()
    assert (
        "Stop spawning NEW re-route or format-re-invocation rounds for "
        "every OTHER target" in text
    ), (
        "step 1's headline no longer scopes to re-route/format-"
        "re-invocation rounds - it may have reverted to the broader "
        "'Stop spawning NEW Worker/Skeptic rounds' wording that "
        "contradicts its own qualifier"
    )
    assert (
        "does NOT forbid a sibling target's FIRST Skeptic spawn for a "
        "Worker that already returned before the escalation was detected"
        in text
    ), (
        "step 1 no longer explicitly permits a sibling's first Skeptic "
        "spawn for an already-returned Worker - that target's terminal "
        "state (per step 2's enumeration) would be unreachable"
    )


def test_part_e_skeptic_signoff_carries_target_prefix() -> None:
    """Round-3 Minor 1: the Part E Skeptic brief's sign-off format must
    require a `Target: <path>` prefix line, mirroring the Worker brief's
    existing `Target:` echo-back requirement (test
    test_worker_brief_carries_explicit_target_path_field above) - otherwise
    sign-off attribution across N out-of-order Skeptic returns rests on
    free-form text ("Reviewed: ...") while draft attribution is
    structurally pinned."""
    text = _read()
    assert (
        "Begin your sign-off with a single line `Target: <the absolute "
        "path given as Global-context input field 5>`" in text
    ), (
        "the Part E Skeptic brief no longer instructs the Skeptic to "
        "prefix its sign-off with a Target: line"
    )
    assert (
        'Sign-off format: "Target: ... Reviewed: ... Findings: ... '
        "Active search: ... Manifest check: ... Test-CI-wiring check: "
        '... No unresolved Critical or Major findings. Sign-off '
        'granted."' in text
    ), (
        "the Part E Skeptic sign-off format string no longer leads with "
        "Target: ..."
    )
    assert "plus the `Target: <path>` prefix line required above" in text, (
        "step 3's sign-off-format validation no longer requires the "
        "Target: prefix line as a mandatory element"
    )
