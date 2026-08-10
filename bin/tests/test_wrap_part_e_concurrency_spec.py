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

Round-3 fix closed a relocated defect in the round-2 fix above: the
Escalation quiescing procedure's own outcome enumeration was not total, and
its own headline contradicted its own qualifier. Three more invariants
were pinned then (items 4-6 below). Items 4 and 5 were themselves
superseded by the round-4 structural rewrite described further below -
they are retained here only as history of what was fixed and why; do not
read them as the file's live guarantee. Items 7-9 are the live invariants
for the write/skip split and the two carve-outs it governs.

4. **Quiesced-skip is a third, explicit outcome** (Round-3 Major, Gap A,
   SUPERSEDED by item 7): at the time of this fix, step 2's per-sibling
   outcome enumeration was made total by naming a third outcome
   ("quiesced skip") for a sibling that is neither signed off nor has
   exhausted its own re-route/format budget, but for which step 1 bars
   the next round that would advance it. Round 4 replaced this
   enumeration entirely with a structural default rule, because
   enumerating named cases is exactly the shape that produced three
   successive relocated gaps (rounds 1, 2, and this round itself, which
   found a fourth case the round-2 enumeration had not named). Do not
   treat enumeration-totality as this file's live invariant -
   it is not, and reintroducing that framing is the defect item 7 exists
   to prevent.

5. **Headline/qualifier agreement on first-Skeptic spawns** (Round-3
   Major, Gap B, SUPERSEDED by item 8): at the time of this fix, step 1's
   "stop spawning" headline was scoped to re-route/format-re-invocation
   rounds only (matching its own qualifier), permitting a sibling's FIRST
   Skeptic spawn for a Worker that already returned before escalation was
   detected. Round 4 generalized this carve-out beyond "first spawn
   only" - item 8 is the live invariant.

6. **Skeptic sign-off carries the same `Target:` prefix as the Worker
   brief** (Round-3 Minor 1): the Part E Skeptic brief's sign-off format
   must require a `Target: <path>` prefix line, mirroring the Worker
   brief's existing `Target:` echo-back requirement - otherwise sign-off
   attribution across N out-of-order Skeptic returns rests on free-form
   text while draft attribution is structurally pinned.

Round-4 fix (this revision) replaces step 2's outcome enumeration with a
single affirmative condition and a structural default for everything
else, closing the class of bug that produced rounds 1-3 (a resolution
matching no named outcome) by construction rather than by finding and
naming one more case. Three more invariants are pinned:

7. **The write/skip split is structural, not enumerated** (Round-4
   Major): a sibling target proceeds to its own step-4 write if and only
   if it reaches a validated sign-off before quiescing finishes for it;
   every other resolution - named or not - is a quiesced skip by
   negation, with no exception. This is the invariant the file now
   guards: an exhaustive-enumeration framing (a list of named outcomes
   each individually proven total) is the exact defect class rounds 1-3
   kept relocating into rather than closing, and this file's own
   regression assertion below forbids the literal phrase "this
   enumeration is total" from resurfacing as a claim about step 2.

8. **Step 1's already-in-flight-Skeptic carve-out covers any round, not
   just the first** (Round-4 Minor 1): a Worker call spawned before
   escalation was detected, whose Skeptic review would close out a later
   re-route round (not just a target's first Worker->Skeptic pipeline),
   is explicitly permitted to complete - only the decision to start the
   NEXT round after that Skeptic returns is barred.

9. **A pipeline that never returns resolves via the structural default,
   with no new timeout mechanism** (Round-4 Minor 2): a hung Worker or
   Skeptic call is, definitionally, not an affirmative sign-off, so it
   already resolves to quiesced skip once the main agent concludes the
   call will not return - stated explicitly rather than left to match no
   named outcome.

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


def _quiescing_block() -> str:
    """Isolate the Escalation quiescing procedure (through the non-response
    note) so a scoped check like "no conductor-judgment escape hatch" is
    not tripped by unrelated uses of similar wording elsewhere in the file
    (e.g. Step 0-pre's own, unrelated "the conductor judges" bullet)."""
    text = _read()
    start = text.index("**Escalation quiescing (NORMATIVE).**")
    end = text.index("**Step 5 — Worktree cleanup.**")
    assert start < end, "could not isolate the Escalation quiescing block"
    return text[start:end]


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
        "write or a logged quiesced skip does `/ds-wrap` release the lock"
        in text
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


def test_escalation_quiescing_step2_default_is_structural_not_enumerated() -> None:
    """Round-4 fix (this revision): step 2's write/skip split is now a
    single affirmative condition with a default negation, not an
    enumeration - the shape that produced three successive relocated gaps
    (round 1: lock released too early; round 2: a budget-remaining sibling
    matched no outcome; round 3: a format-validation-failure-with-budget
    sibling matched no outcome). The prior "this enumeration is total"
    claim is deleted (it was false by round 3), and the write path is
    pinned as the sole affirmative condition with everything else
    defaulting to quiesced skip - so a fourth relocated gap is structurally
    impossible rather than merely unfound."""
    text = _read()
    assert (
        "**The write/skip split is a single affirmative condition, not an "
        "enumeration.**" in text
    ), "step 2 no longer states the structural (not enumerated) rule"
    assert (
        "A sibling target proceeds to its own step-4 write if and only if "
        "it reaches a validated sign-off" in text
    ), "step 2 no longer pins sign-off as the sole affirmative write condition"
    assert (
        "Every other resolution for that target is a quiesced skip, with "
        "no exception" in text
    ), (
        "step 2 no longer states that every non-affirmative resolution "
        "defaults to quiesced skip - a fourth uncovered case could again "
        "match no outcome"
    )
    # The falsified totality claim from round 3 must not resurface.
    assert "this enumeration is total" not in text, (
        "the round-3 'this enumeration is total' claim has resurfaced - "
        "it was false (round 3's own Major proved a case it did not "
        "cover) and is superseded by the structural default-to-skip rule"
    )
    # Illustrative cases must be explicitly labeled non-exhaustive.
    assert (
        "illustrate common quiesced-skip paths; they are examples, not an "
        "exhaustive list" in text
    ), (
        "the retained example cases no longer disclaim exhaustiveness - a "
        "future editor could again read them as the total case list"
    )
    # Step 4's do-not-write list must still count quiesced-skip targets.
    assert "For every quiesced-skip target per step 2" in text, (
        "step 4's 'do NOT write anything for it' list no longer counts "
        "quiesced-skip targets - they would fall through with no defined "
        "write/skip disposition"
    )
    # Step 5's termination predicate must state satisfiability-by-construction
    # and must NOT reintroduce a conductor-judgment escape hatch.
    assert (
        "This predicate is satisfiable by construction, not by "
        "enumeration" in text
    ), "step 5 no longer states the by-construction satisfiability rationale"
    # NOTE: the prose deliberately avoids the literal phrase "conductor
    # judgment" - that exact bigram is a semantic-variant pattern pinned by
    # test_learnings_agent_capture_model_spec.py (a wholly unrelated gate,
    # about learnings-agent capture discretion) and would false-trip it.
    quiescing_block = _quiescing_block()
    assert "no manual determination needed to classify it" in quiescing_block, (
        "step 5 no longer states that its predicate requires no manual "
        "determination to classify a target"
    )
    assert (
        "Classification is mechanical: a target that is not an affirmative "
        "sign-off is a quiesced skip by definition, never a judgment call"
        in quiescing_block
    ), (
        "step 5 no longer states that classification is mechanical, not a "
        "judgment call"
    )
    # Forbid the escape-hatch VERB form ("the conductor judges ..."),
    # granting a live discretionary call to classify a target.
    assert "the conductor judges" not in quiescing_block, (
        "a conductor-judgment escape hatch (an active 'the conductor "
        "judges ...' clause) has appeared inside the Escalation quiescing "
        "block - the structural rule must resolve every target without a "
        "discretionary determination, per the explicit prohibition on "
        "reintroducing one"
    )


def test_escalation_quiescing_step1_permits_any_already_in_flight_skeptic_spawn() -> None:
    """Round-4 Minor 1 fix: step 1's carve-out permitted only a sibling's
    FIRST Skeptic spawn, leaving ambiguous whether the Skeptic spawn that
    closes out an already-in-flight RE-ROUTE round (Worker spawned
    pre-escalation, returns its revised draft post-escalation) is
    permitted or forbidden. The carve-out must now cover both cases
    explicitly - any Skeptic spawn reviewing a Worker call already in
    flight before escalation was detected, at any round number - while
    still barring the decision to start the round AFTER that Skeptic
    returns."""
    text = _read()
    assert (
        "This is true regardless of which round it is - the FIRST "
        "Worker->Skeptic pipeline for that target, or a later re-route "
        "round's Worker->Skeptic pipeline" in text
    ), (
        "step 1 no longer explicitly extends its already-in-flight-Skeptic "
        "carve-out to a re-route round's Skeptic spawn - a Worker spawned "
        "pre-escalation whose Skeptic spawn would close a re-route round "
        "is left ambiguous again"
    )
    assert (
        "Only the decision to start the NEXT round after that Skeptic "
        "returns is barred by this step" in text
    ), (
        "step 1 no longer states which decision remains barred once an "
        "already-in-flight Skeptic spawn (of any round) is permitted to "
        "run"
    )


def test_escalation_quiescing_non_response_case_resolves_via_default_rule() -> None:
    """Round-4 Minor 2 fix: a sibling Worker or Skeptic call that never
    returns previously matched no outcome in step 2's enumeration (step 2
    said only "let every pipeline resolve", with no bound), and quiescing
    newly makes that block lock release for every sibling target where a
    sequential run would not have. The fix does not invent a new timeout
    mechanism - it states explicitly that the structural default rule
    already covers this case (non-response is not an affirmative sign-off,
    so it is a quiesced skip), giving it a bounded terminal state without
    a fourth special case."""
    text = _read()
    assert (
        "**A sibling Worker or Skeptic call that never returns.**" in text
    ), "the non-response case is no longer named as a resolved gap"
    assert (
        "This file does not define a new timeout mechanism for this case, "
        "and it does not need one" in text
    ), "the non-response case no longer disclaims inventing a new mechanism"
    assert (
        "it also holds the lock for every sibling target, so a sibling "
        "that would otherwise have released independently now waits on "
        "it too" in text
    ), (
        "the non-response note no longer states quiescing's actual effect "
        "on sibling targets - the reason this pre-existing gap newly "
        "matters here"
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


def test_module_docstring_pins_round4_structural_rule_not_enumeration() -> None:
    """PR #629 round-5 Major 1 regression guard: this module's own
    docstring must describe the round-4 structural default rule (items
    7-9) as the file's live invariant, and must not describe
    enumeration-totality as still binding - that framing is the exact
    defect class rounds 1-3 kept relocating into, and the docstring is
    the only place in this file explaining WHY the shape is what it is.
    A maintainer following a stale docstring that still called
    quiesced-skip enumeration "must be total" (the pre-fix wording) could
    reintroduce the round-3 defect. This test reads this module's own
    __doc__, not content/commands/ds-wrap.md - it guards THIS file's
    header against going stale relative to the assertions below it, the
    exact failure Major 1 found."""
    docstring = __doc__ or ""
    assert "must be total" not in docstring, (
        "the module docstring still frames the enumeration as needing to "
        "be total - that framing is the round-3 defect class; the live "
        "invariant is the round-4 structural default rule (item 7)"
    )
    assert "Round-4 fix" in docstring, (
        "the module docstring has no round-4 entry - it stops at round-3 "
        "and omits the three invariants round-4 actually pins"
    )
    assert (
        "structural default rule" in docstring
        or "structural, not enumerated" in docstring
    ), (
        "the module docstring does not describe the round-4 structural "
        "invariant that replaced the round-3 enumeration"
    )
    assert "SUPERSEDED by item 7" in docstring and "SUPERSEDED by item 8" in docstring, (
        "the module docstring no longer marks the round-3 items it "
        "superseded as superseded - a reader could mistake items 4/5 for "
        "still-live invariants"
    )


def test_step6_quiesced_skip_report_is_a_derived_reason_not_a_string_menu() -> None:
    """PR #629 round-6 Major fix (relocation of round-5 Major 2): round-5
    gave quiescing four named report strings, one per reachable category
    - but a target that exhausts its FORMAT re-invocation budget (no
    re-routes spent at all) still matched only the "after 3 re-routes"
    string, which is false for it. That is the round-5 fix's own defect
    class recurring one category later: a hand-maintained list of N
    report strings will keep needing an N+1th to stay total.

    Round 6 replaces the list with a single template,
    `Compression skipped for [path] - [reason].`, where `[reason]` is
    derived from the target's own terminal state rather than selected
    from an enumerated menu. This is a PIN, not a runtime regression test
    (there is no executable Step 6 to run against a prior binary state) -
    it asserts the template and every reason value are present in the
    prose, verified by mutation against d5b1c94f (this fix's own parent
    commit) below."""
    text = _read()
    assert "`Compression skipped for [path] - [reason].`" in text, (
        "Step 6 no longer states the single derived-reason report "
        "template - it may have reverted to a hand-maintained string "
        "per category"
    )
    assert (
        "derived from that target's own terminal state, never chosen "
        "from a fixed menu of category strings" in text
    ), (
        "Step 6 no longer states that [reason] is derived rather than "
        "picked from a menu - the property that prevents a category from "
        "matching zero or two strings has been dropped"
    )
    assert '"after 3 re-routes"' in text, (
        "Step 6 has no reason value for the own-re-route-budget-exhausted "
        "quiesced skip"
    )
    assert '"after 3 sign-off-format re-invocations"' in text, (
        "Step 6 has no distinct reason value for the own-format-"
        "re-invocation-budget-exhausted quiesced skip - reusing the "
        "re-routes reason for this category is false for a target that "
        "spent zero re-routes, which is the exact defect this round fixes"
    )
    assert (
        "unresolved findings, round budget remaining when quiescing began"
        in text
    ), (
        "Step 6 has no truthful reason value for the unresolved-findings "
        "quiesced skip"
    )
    assert (
        "sign-off format validation failed, round budget remaining when "
        "quiescing began" in text
    ), (
        "Step 6 has no truthful reason value for the format-validation-"
        "failure quiesced skip"
    )
    assert "the Worker or Skeptic call did not return" in text, (
        "Step 6 has no reason value for the non-response quiesced skip"
    )
    assert "round budget unspent when quiescing began" not in text, (
        "the false 'unspent' qualifier has resurfaced - a target that "
        "consumed 1 or 2 of its 3 re-routes before quiescing began has "
        "budget REMAINING, not unspent"
    )


def test_escalation_quiescing_step2_catchall_is_pinned() -> None:
    """Minor (preference, taken): the Skeptic verified by mutation that
    step 2's catch-all "or any resolution not named here" is unpinned -
    replacing it with "and nothing else" left all existing tests green.
    Pin the catch-all itself so a future editor cannot narrow the
    structural default's scope back toward an enumerated list without
    tripping a test, matching the pin already on the governing sentence
    above it."""
    text = _read()
    assert "or any resolution not named here" in text, (
        "step 2's open-ended catch-all for quiesced-skip resolutions has "
        "been narrowed or removed - the structural default must cover "
        "every non-affirmative resolution, not only the ones named "
        "explicitly, and this phrase was the only place that said so"
    )
