#!/usr/bin/env python3
"""
Spec tests for the `transitions: manual` kill switch prose (DS-244 rework):
the Tracker Writeback Helper's kill-switch gate, Phase 11's kernel copy of
that gate, the corrected comment/assignee-still-fire semantics, the
`transitions_mode` parameter's presence at every writeback call site, and
the `skipped_transitions_manual` status spelling. Prior to this file, no
test under bin/tests/ or hooks/tests/ mentioned any of these three tokens -
deleting the gate paragraph, dropping `transitions_mode` from a call site,
or misspelling the status all stayed green.

Tracker-free: every assertion here reads static repo files only.

Covers:
  - (a) the kill-switch gate paragraph exists in content/references/
    tracker-writeback.md and sits BEFORE step 1 (the pre-read).
  - (b) the corrected Major-1 semantics: the gate suppresses the STATE
    TRANSITION only - comment and assignee update still proceed - in both
    the reference doc and Phase 11's own kernel Behavior block.
  - (c) Phase 11's kernel Behavior block carries its OWN kill-switch bullet
    (Major 2), positioned ahead of both the Linear and Jira forward-only-
    guard bullets.
  - (d) `transitions_mode` is passed at every writeback call site that
    spawns the Helper: the invocation contract itself, Phase 11's Inputs
    list, ds-ticket-status-sync.md's Preflight/single-ticket/`--all` sites,
    and ds-wrap.md Part F's Gate/Reconcile.
  - (e) `skipped_transitions_manual` is spelled correctly (not e.g.
    `skipped_manual_transitions` or `skipped_transition_manual`) in the
    return-status enum wherever it is declared.
  - (f) round-2 rework additions (previously untested): the `--pending-merge`
    no-record disposition for `skipped_transitions_manual` in
    ds-ticket-status-sync.md, the `transitions_manual` breadcrumb field in
    the pending-merge sweep's Output section, and the
    `ds-tracker set transitions manual` mention in ds-init-project.md's
    closing summary.
  - (g)-(l) round-3 rework: the four-state overlay model and the `no_tracker`
    `transitions` carve-out in the kernel Setup prose, the bounded
    once-per-session fire-and-forget line the kernel now SPECIFIES for
    `skipped_transitions_manual` (and the reference's agreeing copy), the
    per-call-site comment/assignee reality replacing the falsified global
    claim, Phase 11's per-tracker Linear/Jira manual behavior, the
    single-ticket spawn paragraph reachable from both mode branches, and the
    corrected `bin/ds-tracker` and README statements.
  - (m) round-4 rework: the Resume check's own resolve-and-print obligation
    for `TRACKER_TRANSITIONS_MODE` (every resume entry point jumps past
    Setup, so the kill switch previously fell back to `auto` on that path),
    and the containment claim corrected in both files to cover fresh and
    resumed runs rather than naming Setup alone.

Run with: python3 -m pytest bin/tests/test_tracker_transitions_kill_switch_spec.py -q
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent

HELPER_PATH = REPO_ROOT / "content" / "references" / "tracker-writeback.md"
CANONICAL_PATH = REPO_ROOT / "content" / "commands" / "ds-implement-ticket.md"
STATUS_SYNC_PATH = REPO_ROOT / "content" / "commands" / "ds-ticket-status-sync.md"
WRAP_PATH = REPO_ROOT / "content" / "commands" / "ds-wrap.md"
INIT_PROJECT_PATH = REPO_ROOT / "content" / "commands" / "ds-init-project.md"

STATUS_TOKEN = "skipped_transitions_manual"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# (a) kill-switch gate exists ahead of step 1
# ---------------------------------------------------------------------------

def test_helper_kill_switch_paragraph_exists():
    text = _text(HELPER_PATH)
    assert "**Kill switch (checked FIRST" in text


def test_helper_kill_switch_precedes_pre_read_step_1():
    text = _text(HELPER_PATH)
    kill_switch_idx = text.index("**Kill switch (checked FIRST")
    step1_idx = text.index("1. **Pre-read current state:**")
    assert kill_switch_idx < step1_idx, "kill switch must be checked before step 1's pre-read"


# ---------------------------------------------------------------------------
# (b) corrected Major-1 semantics: transition-only suppression
# ---------------------------------------------------------------------------

def test_helper_kill_switch_suppresses_transition_only():
    text = _text(HELPER_PATH)
    gate_start = text.index("**Kill switch (checked FIRST")
    gate_end = text.index("When `auto` (the default), proceed to step 1.") + len(
        "When `auto` (the default), proceed to step 1."
    )
    gate = text[gate_start:gate_end]
    assert "STATE TRANSITION ONLY" in gate
    assert "comment and the assignee update are NOT part of this gate" in gate
    # Regression guard: the old over-reaching wording must be gone.
    assert "no other side effect" not in gate
    # The kill switch's core claim - a full inversion of this flag was the one
    # mutation the pre-existing slice check could not see.
    assert 'report `status: "skipped_transitions_manual"` with `transitioned: false`' in gate
    # Scoped to the report clause: the paragraph legitimately cites
    # `transitioned: true` elsewhere, as the awaiting callers' comment gate.
    assert 'with `transitioned: true`' not in gate


def test_phase11_returns_line_documents_partial_side_effects():
    text = _text(CANONICAL_PATH)
    assert (
        '`status: "skipped_transitions_manual"` means only the transition was suppressed; '
        "`transitioned` is `false` but `comment_posted`/`assigned` still reflect reality"
    ) in text


# ---------------------------------------------------------------------------
# (c) Phase 11 kernel Behavior block carries its own kill-switch bullet,
#     positioned ahead of both tracker-specific forward-only-guard bullets
# ---------------------------------------------------------------------------

def test_phase11_behavior_block_has_kill_switch_bullet():
    text = _text(CANONICAL_PATH)
    behavior_idx = text.index("> **Behavior:**")
    linear_idx = text.index("> - **Linear:** Apply forward-only guard")
    jira_idx = text.index("> - **Jira:** Apply forward-only guard")
    kill_switch_idx = text.index(
        "> - **Kill switch (checked FIRST, ahead of forward-only guard).**"
    )
    assert behavior_idx < kill_switch_idx < linear_idx < jira_idx, (
        "Phase 11's kill-switch bullet must sit in the Behavior block, ahead of "
        "both the Linear and Jira forward-only-guard bullets"
    )


def test_phase11_kill_switch_bullet_does_not_suppress_comment_or_assignee():
    text = _text(CANONICAL_PATH)
    idx = text.index(
        "> - **Kill switch (checked FIRST, ahead of forward-only guard).**"
    )
    bullet = text[idx : idx + 1100]
    assert "suppresses the STATE TRANSITION only" in bullet
    assert "at this site both still fire" in bullet
    # Phase 11 is the ONLY site carrying a comment body and an assignee; the
    # round-3 finding was a global "comment/assignee still fire" claim read off
    # this bullet and pasted onto sites that carry neither.
    assert "ONLY writeback call site that carries a comment body and an assignee" in bullet
    # Major 4: no single cross-tracker claim - Linear cannot both skip every
    # round trip and still update the assignee.
    assert "assignee update and comment stay UNAFFECTED" not in bullet
    assert "each tracker bullet below states its own behavior" in bullet


# ---------------------------------------------------------------------------
# (g) round-3 rework: Major 1 - the four-state overlay model in the kernel
# ---------------------------------------------------------------------------

def test_kernel_setup_documents_four_state_overlay_model():
    text = _text(CANONICAL_PATH)
    assert "**Four-state diagnostic.**" in text
    assert "**Three-state diagnostic.**" not in text, (
        "the kernel's fallback prose still asserts the superseded three-state "
        "model, which silently discards `transitions` on the `no_tracker` path"
    )
    idx = text.index("**Four-state diagnostic.**")
    bullet = text[idx : idx + 900]
    for token in ("`ok`", "`absent`", "`no_tracker`", "`unusable`"):
        assert token in bullet, token


def test_kernel_setup_documents_no_tracker_transitions_carve_out():
    text = _text(CANONICAL_PATH)
    idx = text.index("**`no_tracker` carve-out (binding - never discard `transitions`).**")
    bullet = text[idx : idx + 1200]
    assert "`transitions:` IS honored and sets `TRACKER_TRANSITIONS_MODE`" in bullet
    assert "tracker-specific overlay field is ignored" in bullet
    assert "`unusable` is the only status that discards `transitions`" in bullet


def test_kernel_required_field_rule_demotes_to_no_tracker_not_unusable():
    text = _text(CANONICAL_PATH)
    idx = text.index("- **Required-field rule.**")
    bullet = text[idx : idx + 700]
    assert "demoted to `no_tracker` when it still carries a valid `transitions:` value" in bullet
    assert "demoted to `unusable` rather than producing" not in bullet


def test_kernel_setup_summary_prints_transitions_mode():
    text = _text(CANONICAL_PATH)
    assert "TRACKER_TRANSITIONS_MODE:   [auto | manual]" in text


# ---------------------------------------------------------------------------
# (h) round-3 rework: Major 2 - bounded fire-and-forget output, kernel first
# ---------------------------------------------------------------------------

# Retired output: asserted ABSENT everywhere (see the no-session-state test).
MANUAL_LINE = (
    "tracker-writeback: <ticket_id> -> '<target_state>' SKIPPED: transitions "
    "manual - further transition-skip lines suppressed this session. Run "
    "ds-tracker set transitions auto to re-enable."
)


def test_kernel_specifies_fire_and_forget_output_for_transitions_manual():
    """The kernel governs and must SPECIFY what fire-and-forget sites emit for
    skipped_transitions_manual, not merely exclude it from another convention.
    The specified output is now NOTHING, with the Setup print carrying the
    indication - see the no-session-state test below for why."""
    text = _text(CANONICAL_PATH)
    assert "emit NO stderr line for this status" in text
    assert MANUAL_LINE not in text, (
        "the suppress-after-first line is retired; it required a session-scoped "
        "flag with no named state location"
    )
    # The round-2 wording supplied no replacement output at all.
    assert (
        "The bullet above's `SKIPPED:` convention is scoped to the "
        "fire-and-forget call sites' `skipped_unconfigured_state` outcome "
        "only, not to this status."
    ) not in text


def test_reference_fire_and_forget_output_agrees_with_kernel():
    ref = _text(HELPER_PATH)
    assert "emit NO stderr line for this status" in ref
    assert MANUAL_LINE not in ref
    # The reference must no longer claim one line per fire for this status.
    assert "the new status emits ONE bounded stderr line per fire" not in ref


# ---------------------------------------------------------------------------
# (i) round-3 rework: Major 3 - per-call-site text, not one global claim
# ---------------------------------------------------------------------------

def test_reference_states_per_call_site_comment_reality():
    ref = _text(HELPER_PATH)
    assert "per-call-site, not global" in ref
    assert "W1-W7 pass neither a comment nor an assignee" in ref
    assert "Each gates that comment on `transitioned: true`" in ref
    # The falsified global claim must be gone.
    assert "still proceed exactly as they would under `auto`" not in ref


def test_reference_comment_posting_caller_enumeration_is_the_true_set():
    """Major regression: the reference claimed THREE awaiting callers post a
    comment, naming `/ds-ticket-status-sync` single-ticket among them. Only
    TWO define a comment step at all - `--all` Tier 1's step 7 and `/ds-wrap`
    Part F - which is verified structurally below against the call sites
    themselves, not taken on trust from the prose."""
    ref = _text(HELPER_PATH)
    assert "Exactly TWO of the four awaiting callers define a comment step" in ref
    assert "`--all` Tier 1 (the tracker-wide sweep's step 7) and `/ds-wrap` Part F" in ref
    # The false count and the false member must both be gone.
    assert "three awaiting callers" not in ref.lower()
    assert "single-ticket and `--all` Tier 1, plus" not in ref

    # Structural check: ds-ticket-status-sync defines exactly ONE comment-post
    # step, and it lives in the tracker-wide sweep (--all Tier 1), after the
    # single-ticket resolution algorithm section has ended.
    sync = _text(STATUS_SYNC_PATH)
    post_steps = [
        line for line in sync.splitlines()
        if line.startswith("7. **Evidence comment")
    ]
    assert len(post_steps) == 1, post_steps
    comment_idx = sync.index("7. **Evidence comment")
    sweep_idx = sync.index("## Tracker-wide sweep (`--all` mode, Tier 1")
    single_idx = sync.index("## Resolution algorithm (single ticket)")
    assert single_idx < sweep_idx < comment_idx, (single_idx, sweep_idx, comment_idx)
    # Single-ticket mode says so itself.
    assert "steps 1-6 define neither" in sync
    # /ds-wrap Part F is the other one.
    assert "Gate the comment on the Writeback Helper's return payload" in _text(WRAP_PATH)


def test_fire_and_forget_sites_emit_no_per_skip_line_and_name_no_session_state():
    """Minor regression: the old rule bounded the fire-and-forget stderr line
    to "exactly ONE line per conductor session" while naming no state location
    and no session boundary, unlike every other cross-invocation flag in this
    repo. Replaced with a bound needing no persisted state: no line at all,
    with the one per-run print as the guaranteed indication.

    The zero-state bound is kept rather than traded for a bounded per-site
    line, and its guarantee is stated to cover BOTH run shapes: a fresh run
    prints from Setup, a resumed run from the Resume check (which never
    reaches Setup). The earlier wording named Setup alone, which was false on
    the resume path."""
    for path in (CANONICAL_PATH, HELPER_PATH):
        text = _text(path)
        assert "emit NO stderr line for this status" in text, path
        assert "not one per fire, and not one per run" in text, path
        # The unimplementable bound and its line must both be gone.
        assert "ONE line per conductor session" not in text, path
        assert "ONE stderr line per conductor session" not in text, path
        assert "further transition-skip lines suppressed this session" not in text, path
        # The guarantee must not rest on Setup alone.
        assert "every such run prints `TRACKER_TRANSITIONS_MODE`" in text, path
        assert "never reaches Setup" in text, path

    # The operator is never left with zero indication: the print carries
    # the consequence when the mode is manual.
    kernel = _text(CANONICAL_PATH)
    assert (
        "TRACKER_TRANSITIONS_MODE:   manual - no automatic tracker state "
        "transition will fire this run."
    ) in kernel


def test_resume_path_resolves_and_prints_transitions_mode():
    """Major regression: every resume entry point sits downstream of W1-W7 and
    Phase 11, and the resume path jumps straight past Setup - so a resumed
    session left TRACKER_TRANSITIONS_MODE unresolved and the Helper's
    transitions_mode defaulted to `auto`, firing the transitions a
    `transitions: manual` operator had explicitly disabled. The Resume check
    must now resolve and print it before jumping to any entry point."""
    kernel = _text(CANONICAL_PATH)

    marker = (
        "**After resuming - resolve and print `TRACKER_TRANSITIONS_MODE` "
        "before jumping to any entry point.**"
    )
    assert marker in kernel

    block = kernel[kernel.index(marker) : kernel.index(marker) + 1400]
    # It must say WHY (the auto fallback fires suppressed transitions) ...
    assert "falls back to its `auto` default" in block
    # ... HOW to resolve it (Setup's own rule, not a second algorithm) ...
    assert "ds-tracker resolve --json" in block
    assert "`no_tracker` carve-out" in block
    # ... and that it prints the same line Setup prints.
    assert "print the same `TRACKER_TRANSITIONS_MODE:` line Setup prints" in block

    # The obligation has to sit in the Resume check, ahead of Setup.
    assert kernel.index(marker) < kernel.index("## Setup: Read project config")


def test_pending_merge_print_and_record_decisions_do_not_contradict():
    """Minor regression: step (f) inherited single-ticket step 6's manual-branch
    print while step (g) said "no print this sweep" - a flat contradiction.
    Resolved by splitting on invocation path (automatic session-start silent,
    direct operator invocation prints) and decoupling the print decision from
    the record decision."""
    sync = _text(STATUS_SYNC_PATH)
    assert "only on a direct operator invocation" in sync
    assert "the print and the state record are independent decisions" in sync
    # The bare contradiction must be gone.
    assert "no `attempts` touched, no print this sweep" not in sync
    assert "no entry in `.agentic/pending-merge-state.jsonl` and no `attempts` touched" in sync

    # Round-4 minor: (j)'s "one line per transition attempt" left it open
    # whether a manual skip counts as an attempt, so a direct invocation could
    # print (f)'s line AND (j)'s. (j) is now scoped to exclude it.
    j_start = sync.index("**j. Output.**")
    j_block = sync[j_start : sync.index("\n\n", j_start)]
    assert "is NOT a transition attempt and gets no line from this step" in j_block
    assert "would double-print it" in j_block


def test_single_ticket_manual_branch_claims_no_comment_or_assignee():
    text = _text(STATUS_SYNC_PATH)
    assert (
        "[ticket-status-sync] <TICKET_ID>: transition to '<expected>' skipped "
        "(transitions_mode=manual). Run `ds-tracker set transitions auto` to re-enable."
    ) in text
    assert "**Do not claim a comment or an assignee update here:**" in text
    # The round-3 falsehood: single-ticket steps 1-6 define no comment step.
    assert "posting comment/assignee update only" not in text
    assert "the comment and assignee update still fire" not in text


def test_all_sweep_and_wrap_substitute_diagnostics_do_not_claim_a_comment():
    for path in (STATUS_SYNC_PATH, WRAP_PATH):
        text = _text(path)
        assert "no comment posted" in text, path
        assert "transitions_mode=manual (comment/assignee still" not in text, path


# ---------------------------------------------------------------------------
# (j) round-3 rework: Major 4 - Linear and Jira each state their own behavior
# ---------------------------------------------------------------------------

def test_phase11_linear_bullet_specifies_assignee_only_save_issue():
    text = _text(CANONICAL_PATH)
    idx = text.index("> - **Linear:** Apply forward-only guard")
    bullet = text[idx : text.index("> - **Jira:** Apply forward-only guard")]
    assert "**Under `transitions_mode: manual`:**" in bullet
    assert "make ONE assignee-only `save_issue` call passing `assigneeId` and no `state`" in bullet
    assert "make no `save_issue` call at all" in bullet


def test_phase11_jira_bullet_states_its_own_manual_behavior():
    text = _text(CANONICAL_PATH)
    idx = text.index("> - **Jira:** Apply forward-only guard")
    bullet = text[idx : idx + 2600]
    assert "**Under `transitions_mode: manual`:**" in bullet
    assert "no round trip at all on the transition path" in bullet
    assert "fire exactly as they would under `auto`" in bullet


def test_reference_closing_phase11_note_scopes_assignee_per_tracker():
    ref = _text(HELPER_PATH)
    assert "The assignee update is unaffected in effect on both, but not in call shape" in ref
    assert "the comment and assignee update are unaffected; this plan does not change" not in ref


# ---------------------------------------------------------------------------
# (k) round-3 rework: Minor 4 - the spawn reference must resolve
# ---------------------------------------------------------------------------

def test_single_ticket_spawn_paragraph_is_reachable_from_both_branches():
    text = _text(STATUS_SYNC_PATH)
    assert "**Spawn (reached from BOTH branches above).**" in text
    manual_idx = text.index("**`TRACKER_TRANSITIONS_MODE == manual` - no prompt at all.**")
    auto_idx = text.index("**`TRACKER_TRANSITIONS_MODE == auto` (the default) - confirm first.**")
    spawn_idx = text.index("**Spawn (reached from BOTH branches above).**")
    assert manual_idx < auto_idx < spawn_idx, (
        "the spawn instruction must sit outside - and after - both mutually "
        "exclusive mode branches, or the manual branch's forward reference "
        "resolves into a branch it can never enter"
    )
    assert "proceed straight to the spawn below" not in text


# ---------------------------------------------------------------------------
# (l) round-3 rework: Minor 3/5 - ds-tracker docstring and README
# ---------------------------------------------------------------------------

def test_ds_tracker_docstring_unusable_definition_is_accurate():
    text = (REPO_ROOT / "bin" / "ds-tracker").read_text(encoding="utf-8")
    assert "which is reserved for an overlay with no usable field at all" not in text, (
        "false: the credential-shaped-key guard returns `unusable` for an "
        "overlay carrying a valid `transitions` value"
    )
    assert "carrying a credential-shaped key, a guard that rejects the whole file even" in text


def test_readme_states_the_transitions_carve_out():
    text = (REPO_ROOT / "README.md").read_text(encoding="utf-8")
    idx = text.index("An absent, malformed, incomplete, or credential-bearing overlay never blocks")
    para = text[idx : idx + 800]
    assert "still contributes its `transitions:` kill switch" in para


# ---------------------------------------------------------------------------
# (d) transitions_mode present at every writeback call site
# ---------------------------------------------------------------------------

def test_helper_invocation_contract_has_transitions_mode():
    text = _text(HELPER_PATH)
    assert "`transitions_mode`: `$TRACKER_TRANSITIONS_MODE`" in text


def test_phase11_inputs_list_has_transitions_mode():
    text = _text(CANONICAL_PATH)
    assert '`transitions_mode`: `$TRACKER_TRANSITIONS_MODE` from Setup' in text


def test_ticket_status_sync_preflight_resolves_transitions_mode():
    text = _text(STATUS_SYNC_PATH)
    assert "Additionally resolve `TRACKER_TRANSITIONS_MODE`" in text
    assert "pass it as `transitions_mode` to every Tracker Writeback Helper invocation" in text


def test_ticket_status_sync_single_and_all_sites_pass_transitions_mode():
    text = _text(STATUS_SYNC_PATH)
    occurrences = [i for i in range(len(text)) if text.startswith("`transitions_mode` (`$TRACKER_TRANSITIONS_MODE`", i)]
    assert len(occurrences) >= 2, (
        "expected transitions_mode to be passed at both the single-ticket and "
        "--all tracker-writeback spawn sites"
    )


def test_wrap_part_f_resolves_and_passes_transitions_mode():
    text = _text(WRAP_PATH)
    assert "Also resolve `TRACKER_TRANSITIONS_MODE`" in text
    assert "pass it as `transitions_mode` below" in text
    assert "`transitions_mode` (`$TRACKER_TRANSITIONS_MODE` resolved in the Gate above)" in text


# ---------------------------------------------------------------------------
# (e) status spelling
# ---------------------------------------------------------------------------

# Precise enum-token extractors - deliberately narrower than a line-scoped
# substring check, because both the reference doc's and the kernel's "Full
# return-status set" bullet repeat the status token a second time later in
# the SAME line (in an explanatory sentence), which would let a line-scoped
# substring check pass vacuously even when the enum literal itself is
# misspelled. These regexes pin only the enum literal itself.
_ENUM_RE = re.compile(
    r"`ok \| partial \| failed \| skipped_unconfigured_state \| ([a-z_]+)`"
)
_RETURNS_ENUM_RE = re.compile(
    r'status: "ok" \| "partial" \| "failed" \| "skipped_unconfigured_state" \| "([a-z_]+)"'
)


def test_status_token_spelled_correctly_in_helper_doc():
    text = _text(HELPER_PATH)
    m = _ENUM_RE.search(text)
    assert m is not None, "return-status enum literal not found in tracker-writeback.md"
    assert m.group(1) == STATUS_TOKEN


def test_status_token_spelled_correctly_in_kernel_caller_enumeration():
    text = _text(CANONICAL_PATH)
    m = _ENUM_RE.search(text)
    assert m is not None, "return-status enum literal not found in the kernel Caller enumeration"
    assert m.group(1) == STATUS_TOKEN


def test_status_token_spelled_correctly_in_phase11_returns():
    text = _text(CANONICAL_PATH)
    m = _RETURNS_ENUM_RE.search(text)
    assert m is not None, "Phase 11 Returns status enum literal not found"
    assert m.group(1) == STATUS_TOKEN


# ---------------------------------------------------------------------------
# (f) round-2 rework additions
# ---------------------------------------------------------------------------

def test_pending_merge_no_record_disposition_documented():
    text = _text(STATUS_SYNC_PATH)
    assert "**`skipped_transitions_manual` writes NO record.**" in text
    assert (
        "Treat it exactly like the `OPEN` outcome in (c): no entry in "
        "`.agentic/pending-merge-state.jsonl` and no `attempts` touched."
    ) in text


def test_pending_merge_transitions_manual_breadcrumb_field_present():
    text = _text(STATUS_SYNC_PATH)
    breadcrumb = (
        "[phase: ticket-status-sync | mode=pending-merge | candidates=<N> | "
        "confirmed_merged=<N> | blocked_by_open_pr=<N> | transitions=<N> | "
        "skipped=<N> | transitions_manual=<N>]"
    )
    occurrences = text.count(breadcrumb)
    assert occurrences >= 2, (
        "expected the transitions_manual breadcrumb to appear in both the "
        "pending-merge sweep's own Output subsection (j) and the command's "
        f"top-level ## Output section; found {occurrences}"
    )


def test_init_project_closing_summary_mentions_transitions_kill_switch():
    text = _text(INIT_PROJECT_PATH)
    assert (
        "To stop /ds-implement-ticket and related commands from automatically "
        "transitioning this tracker's tickets, run `ds-tracker set transitions manual` "
        "at any time. Run `ds-tracker set transitions auto` to re-enable."
    ) in text


if __name__ == "__main__":
    test_helper_kill_switch_paragraph_exists()
    test_helper_kill_switch_precedes_pre_read_step_1()
    test_helper_kill_switch_suppresses_transition_only()
    test_phase11_returns_line_documents_partial_side_effects()
    test_phase11_behavior_block_has_kill_switch_bullet()
    test_phase11_kill_switch_bullet_does_not_suppress_comment_or_assignee()
    test_helper_invocation_contract_has_transitions_mode()
    test_phase11_inputs_list_has_transitions_mode()
    test_ticket_status_sync_preflight_resolves_transitions_mode()
    test_ticket_status_sync_single_and_all_sites_pass_transitions_mode()
    test_wrap_part_f_resolves_and_passes_transitions_mode()
    test_status_token_spelled_correctly_in_helper_doc()
    test_status_token_spelled_correctly_in_kernel_caller_enumeration()
    test_status_token_spelled_correctly_in_phase11_returns()
    test_pending_merge_no_record_disposition_documented()
    test_pending_merge_transitions_manual_breadcrumb_field_present()
    test_init_project_closing_summary_mentions_transitions_kill_switch()
    test_kernel_setup_documents_four_state_overlay_model()
    test_kernel_setup_documents_no_tracker_transitions_carve_out()
    test_kernel_required_field_rule_demotes_to_no_tracker_not_unusable()
    test_kernel_setup_summary_prints_transitions_mode()
    test_kernel_specifies_fire_and_forget_output_for_transitions_manual()
    test_reference_fire_and_forget_output_agrees_with_kernel()
    test_reference_states_per_call_site_comment_reality()
    test_single_ticket_manual_branch_claims_no_comment_or_assignee()
    test_all_sweep_and_wrap_substitute_diagnostics_do_not_claim_a_comment()
    test_phase11_linear_bullet_specifies_assignee_only_save_issue()
    test_phase11_jira_bullet_states_its_own_manual_behavior()
    test_reference_closing_phase11_note_scopes_assignee_per_tracker()
    test_single_ticket_spawn_paragraph_is_reachable_from_both_branches()
    test_ds_tracker_docstring_unusable_definition_is_accurate()
    test_readme_states_the_transitions_carve_out()
    print("PASS test_tracker_transitions_kill_switch_spec")
