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
