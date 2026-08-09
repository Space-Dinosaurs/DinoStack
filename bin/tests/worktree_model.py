#!/usr/bin/env python3
"""
Purpose: Executable reference implementation of the DS-118 worktree
         classification-and-disposition model. This module is the SINGLE
         NORMATIVE DEFINITION of "what class is this worktree entry" and
         "is it safe to delete" - content/sections/11-worktree-lifecycle.md
         and content/references/worktree-lifecycle.md point at this file
         rather than restating the classification/disposition algorithm in
         prose, mirroring fold_model.py's own pattern (DS-108) for exactly
         the same reason: two representations that can disagree is the
         defect class this exists to prevent.

         Resolves DS-118 defect 1 (the two worktree classes were previously
         keyed on colliding, name-based schemes - a `feature/*`/`fix/*`/
         `chore/*` branch can and does live inside a `.claude/worktrees/`
         isolation directory once the branch is renamed post-creation,
         which the branch-name-only heuristic could not disambiguate).
         `classify_entry` below classifies by PATH AND HOST ONLY - creation
         mechanism/location, never by branch name - which is what makes the
         collision unreachable by construction. Defect 3 (worktree reuse
         across fix-pass rounds) is explicitly OUT OF SCOPE for this module
         - see DS-123.

Public API:
  parse_porcelain(text)                              -> List[WorktreeEntry]
  classify_entry(entry, *, host, repo_root, is_main)  -> WorktreeClass
  disposition_for(entry, wt_class, facts, *,
                   merge_evidence_order=MERGE_EVIDENCE_ORDER) -> Disposition
  disposition_for_orphan_branch(branch, facts, *,
                   merge_evidence_order=MERGE_EVIDENCE_ORDER,
                   base_branches=DEFAULT_BASE_BRANCHES) -> Disposition
  relative_path(path, repo_root)                      -> str
  WorktreeEntry, DispositionFacts                      -> dataclasses
  WorktreeClass, Disposition                            -> enums
  MERGE_EVIDENCE_ORDER                                   -> evidence-source
                                                            precedence tuple
  DEFAULT_BASE_BRANCHES                                  -> ("main", "master")
                                                            default guard set

  DS-153 / plan Amendment B1: `disposition_for` (LIVE WORKTREE REMOVAL,
  `git worktree remove`) and `disposition_for_orphan_branch` (BRANCH
  DELETION, `git branch -D`) now resolve `pr_state == "MERGED"`
  differently, via an explicit `strict_pr_state` parameter threaded through
  the shared `_resolve_merge_evidence` helper - never an implicit caller
  convention. `disposition_for` passes `strict_pr_state=False` (unchanged
  legacy behavior: a bare MERGED PR is ELIGIBLE) because `git worktree
  remove` does not destroy commits - the branch and its objects survive,
  so the worst case is already covered by SKIP_DIRTY/SKIP_LOCKED.
  `disposition_for_orphan_branch` passes `strict_pr_state=True` (new
  behavior: a bare MERGED PR alone is `SKIP_PR_MERGED_UNPROVEN`, a
  TERMINAL skip - only `content_subsumption == "subsumed"` can still earn
  ELIGIBLE) because `git branch -D` is a data-loss-capable operation and
  the plan's subsumption predicate is calibrated for it. See the plan
  Skeptic's Amendment B1 (`.agentic/ds-153-plan.md`, DS-153) for the full
  rationale: applying the branch-deletion bar to worktree removal strands
  every squash-merged LIVE worktree permanently.

Upstream deps: none (stdlib only, no I/O). Pure functions throughout -
               callers gather live facts (via `git`, `gh`) and pass them in.

Downstream consumers: test_worktree_model.py (pytest suite);
                      test_worktree_lifecycle_spec.sh (shell-level
                      determinism smoke spec); content/sections/
                      11-worktree-lifecycle.md and content/references/
                      worktree-lifecycle.md (both point at this file as the
                      normative classification/disposition definition rather
                      than restating the algorithm in prose);
                      content/references/worktree-lifecycle.md
                      §Session-start prune script (its worktree-agent-*
                      branch delete is gated on a merge-evidence check
                      before deleting - ancestry then PR state, mirroring
                      disposition_for_orphan_branch's evidence order,
                      though not a literal function call from this bash
                      context); §Branch prune bullets 1/2 (their existing
                      selection filters are pre-model guards, annotated as
                      equivalent to what disposition_for_orphan_branch would
                      compute - left unchanged, not a literal call site);
                      §Branch prune bullet 3 now applies the identical
                      merge-evidence gate as the session-start prune script
                      above it (ancestry, then PR state) - it targets the
                      same worktree-agent-*-with-no-live-worktree population
                      at the same session-start phase, so leaving it
                      ungated while the script above was gated produced
                      zero behavior change plus stderr noise; both are now
                      consistently gated, not a literal call site;
                      content/commands/ds-cleanup-worktrees.md Steps 2/3/4
                      (classify_entry is the normative classification Step 2
                      describes; disposition_for is the normative gate Steps
                      3/4 describe, in disposition_for's own locked -> dirty
                      -> merge-evidence order - Step 4's dirty check, absent
                      before this ticket, was added to close that gap).
                      None of these prose consumers literally import or
                      shell out to this module at conductor runtime - as
                      with fold_model.py (DS-108), the model is the
                      normative definition the prose is checked against and
                      kept in sync with; where prose and this module
                      disagree, this module wins.

Failure modes: `parse_porcelain` raises ValueError on a block missing the
               `worktree` key unconditionally, and (for a non-bare block
               only - see the bare-repository exemption in its docstring)
               on a block missing `HEAD`, or missing/duplicating both of
               `branch`/`detached`. `classify_entry` and `disposition_for`
               never raise on well-formed input - both are total functions
               over their enums. `DispositionFacts` has NO field defaults
               (a bare dataclass): omitting a required field raises
               TypeError at construction. This is the fail-closed
               guarantee this ticket's outcome rubric line 4 names - no
               code path can construct a partially-populated facts object
               and have it silently authorize Disposition.ELIGIBLE; every
               field must be an explicit string (never `Optional[bool]`),
               and every field's own "not_checked" value routes to a SKIP_*
               disposition rather than defaulting to ELIGIBLE.

Performance: O(n) single-pass parse per invocation; O(1) per-entry
             classification and disposition. No I/O.
"""

from __future__ import annotations

import os.path
from dataclasses import dataclass
from enum import Enum
from typing import Callable, Dict, List, Optional, Tuple

# --------------------------------------------------------------------------
# Data model
# --------------------------------------------------------------------------


@dataclass
class WorktreeEntry:
    path: str
    head: Optional[str]  # None for a bare-repo entry (no HEAD line is emitted)
    branch: Optional[str]  # None when detached OR bare
    is_detached: bool  # False for a bare entry (neither "detached" applies)
    is_bare: bool = False  # True only for the `bare` keyword shape below
    locked: bool = False
    locked_reason: Optional[str] = None
    prunable: bool = False
    prunable_reason: Optional[str] = None


def parse_porcelain(text: str) -> List[WorktreeEntry]:
    """Pure parser for `git worktree list --porcelain` output. No I/O - operates on
    caller-supplied text only, exactly as fold_model.py's fold() operates on
    caller-supplied records rather than reading .jsonl itself.

    Format: entries are separated by a blank line. Each entry is a sequence of
    space-separated `<key> <value>` lines (values may contain spaces, e.g. a
    `locked` or `prunable` reason - the value is everything after the first
    space on that line, not split further).

    Recognized keys:
        worktree <absolute-path>          - always present, always first in its entry
        HEAD <40-char-sha>                 - present UNLESS the entry is bare
        branch refs/heads/<name>           - present when NOT detached and NOT bare
        detached                           - present (bare keyword, no value) when the
                                              worktree has no branch checked out AND is
                                              not itself a bare-repository entry
        bare                                - present (bare keyword, no value) ONLY for
                                              a bare repository's own worktree listing
                                              entry (`git worktree list --porcelain` on
                                              a `--bare` clone emits exactly `worktree
                                              <path>` then `bare` - no HEAD, no branch,
                                              no detached line at all). Verified against
                                              a scratch --bare clone (round-5 finding).
        locked [<reason>]                  - optional, independent of the above
        prunable [<reason>]                - optional, independent of the above

    Validation: a block missing `worktree` is malformed (ValueError) unconditionally.
    For a NON-bare block (no `bare` key present), `HEAD` must be present and exactly
    one of `branch`/`detached` must be present - both ValueError otherwise. For a
    BARE block (`bare` key present), `HEAD`, `branch`, and `detached` are all
    EXEMPTED from those requirements - their presence or absence is not validated
    at all for a bare entry, since git itself emits none of them for this shape.
    is_bare = (the `bare` line was present). head = None when bare (no HEAD line
    to parse). branch = None when bare (no branch line to parse).

    Algorithm: split `text` on blank lines into blocks; for each non-empty block,
    split into lines; parse `worktree` unconditionally (a block missing it is
    malformed input - raise ValueError naming the block, never silently skip,
    matching fold_model's own "never raises on a merely-unusual record, but a
    structurally malformed one is not silently absorbed" posture in spirit);
    `branch`/`detached` are mutually exclusive for a non-bare block - exactly
    one must be present, else ValueError; `locked`/`prunable` are optional,
    presence-tested independently. entry.branch is set to the value after
    `refs/heads/` when the `branch` line is present, else None. is_detached =
    (the `detached` line was present, non-bare only).

    Returns entries in the SAME ORDER as the input text - this is load-bearing:
    the caller relies on entries[0] being the main worktree (git always emits it
    first), which is how `is_main` is derived (see Implementation steps, Slice 1,
    step 6, "is_main derivation").
    """
    entries: List[WorktreeEntry] = []
    block: List[str] = []

    def flush() -> None:
        if block:
            entries.append(_parse_block(list(block)))

    for line in text.split("\n"):
        if line.strip() == "":
            flush()
            block.clear()
        else:
            block.append(line)
    flush()

    return entries


_BRANCH_REF_PREFIX = "refs/heads/"


def _parse_block(lines: List[str]) -> WorktreeEntry:
    path: Optional[str] = None
    head: Optional[str] = None
    branch: Optional[str] = None
    is_detached = False
    is_bare = False
    locked = False
    locked_reason: Optional[str] = None
    prunable = False
    prunable_reason: Optional[str] = None

    for line in lines:
        if " " in line:
            key, value = line.split(" ", 1)
        else:
            key, value = line, ""

        if key == "worktree":
            path = value
        elif key == "HEAD":
            head = value
        elif key == "branch":
            branch = value[len(_BRANCH_REF_PREFIX):] if value.startswith(_BRANCH_REF_PREFIX) else value
        elif key == "detached":
            is_detached = True
        elif key == "bare":
            is_bare = True
        elif key == "locked":
            locked = True
            locked_reason = value or None
        elif key == "prunable":
            prunable = True
            prunable_reason = value or None
        # unrecognized keys are ignored (forward-compat with a future git
        # porcelain field this parser has not been taught yet).

    if path is None:
        raise ValueError("malformed worktree porcelain block: missing 'worktree' key: %r" % (lines,))

    if not is_bare:
        if head is None:
            raise ValueError("malformed non-bare worktree block: missing 'HEAD': %r" % (lines,))
        if branch is not None and is_detached:
            raise ValueError(
                "malformed worktree block: both 'branch' and 'detached' present: %r" % (lines,)
            )
        if branch is None and not is_detached:
            raise ValueError(
                "malformed worktree block: neither 'branch' nor 'detached' present: %r" % (lines,)
            )

    return WorktreeEntry(
        path=path,
        head=None if is_bare else head,
        branch=None if is_bare else branch,
        is_detached=False if is_bare else is_detached,
        is_bare=is_bare,
        locked=locked,
        locked_reason=locked_reason,
        prunable=prunable,
        prunable_reason=prunable_reason,
    )


def relative_path(path: str, repo_root: str) -> str:
    """Pure path relativization - no filesystem access, no symlink resolution.

    Returns a normalized relative path (no leading slash) when `path` is
    under `repo_root`; returns `"."` when `path` IS `repo_root`; returns the
    normalized `path` unchanged when it is NOT under `repo_root` at all - the
    caller (`classify_entry`) uses that unchanged-absolute-path return to
    detect a foreign/out-of-repo path, distinct from a merely-unrecognized
    in-repo one.
    """
    norm_root = os.path.normpath(repo_root)
    norm_path = os.path.normpath(path)
    if norm_path == norm_root:
        return "."
    prefix = norm_root.rstrip("/") + "/"
    if norm_path.startswith(prefix):
        return norm_path[len(prefix):]
    return norm_path


# --------------------------------------------------------------------------
# Classification
# --------------------------------------------------------------------------


class WorktreeClass(Enum):
    MAIN = "MAIN"
    ISOLATION = "ISOLATION"
    CONDUCTOR_CREATED = "CONDUCTOR_CREATED"
    UNMANAGED = "UNMANAGED"


#: The two conductor-owned worktree admin subdirectories this repo's own
#: methodology declares (content/sections/11-worktree-lifecycle.md /
#: content/rules/conventions.md §Git Workflow). Checked against the
#: `repo_root`-relative path, never against `entry.branch` - this is
#: defect 1's fix: a `feature/*`/`fix/*`/`chore/*`-named branch living
#: inside `.claude/worktrees/` (the live, observed collision) still
#: classifies ISOLATION by its location, never CONDUCTOR_CREATED by its
#: name.
_ISOLATION_DIR_PREFIX = ".claude/worktrees/"
_CONDUCTOR_CREATED_DIR_PREFIX = ".agentic/worktrees/"


def classify_entry(
    entry: WorktreeEntry,
    *,
    host: str,
    repo_root: str,
    is_main: bool,
) -> WorktreeClass:
    """Path-and-host-only classification. Never reads `entry.branch` - see
    the module docstring for why (DS-118 defect 1).

    `is_main` is supplied by the caller, not derived here - the caller
    already knows it positionally (git always emits the main worktree
    first; see `parse_porcelain`'s own "SAME ORDER" guarantee).

    `host` is the containment boundary: the caller's own repository root as
    git itself reports it (e.g. `git rev-parse --show-toplevel`, NOT
    necessarily byte-identical to the `repo_root` a particular call site
    wants relative paths computed against, though in the common case they
    are the same value). An entry whose `path` is not a descendant of
    `host` belongs to a DIFFERENT repository entirely - it is foreign, not
    merely unrecognized, and is always UNMANAGED regardless of any
    name-pattern coincidence (the cross-repo non-collision guarantee: a
    worktree from a different clone that happens to sit under a
    `.agentic/worktrees/`-shaped path of ITS OWN repo must never be
    classified as belonging to `repo_root`'s CONDUCTOR_CREATED set).
    `repo_root` is then used only to compute the path relativization that
    the directory-prefix checks below key on.
    """
    if is_main:
        return WorktreeClass.MAIN

    if entry.is_bare:
        # A bare repository's own worktree-list entry is never one of the
        # two managed worktree classes this model governs.
        return WorktreeClass.UNMANAGED

    norm_host = os.path.normpath(host)
    norm_path = os.path.normpath(entry.path)
    under_host = norm_path == norm_host or norm_path.startswith(norm_host.rstrip("/") + "/")
    if not under_host:
        return WorktreeClass.UNMANAGED

    rel = relative_path(entry.path, repo_root)
    if rel.startswith(_ISOLATION_DIR_PREFIX):
        return WorktreeClass.ISOLATION
    if rel.startswith(_CONDUCTOR_CREATED_DIR_PREFIX):
        return WorktreeClass.CONDUCTOR_CREATED
    return WorktreeClass.UNMANAGED


# --------------------------------------------------------------------------
# Disposition
# --------------------------------------------------------------------------


class Disposition(Enum):
    ELIGIBLE = "ELIGIBLE"
    SKIP_MAIN = "SKIP_MAIN"
    SKIP_UNMANAGED = "SKIP_UNMANAGED"
    SKIP_LOCKED = "SKIP_LOCKED"
    SKIP_DIRTY = "SKIP_DIRTY"
    SKIP_NOT_PUSHED = "SKIP_NOT_PUSHED"
    SKIP_LS_REMOTE_ERROR = "SKIP_LS_REMOTE_ERROR"
    SKIP_PR_OPEN = "SKIP_PR_OPEN"
    SKIP_PR_MERGED_UNPROVEN = "SKIP_PR_MERGED_UNPROVEN"
    SKIP_AMBIGUOUS_NO_PR = "SKIP_AMBIGUOUS_NO_PR"
    SKIP_UNREFERENCED_COMMIT = "SKIP_UNREFERENCED_COMMIT"
    SKIP_BASE_BRANCH = "SKIP_BASE_BRANCH"


@dataclass
class DispositionFacts:
    """Every field is a required, no-default string - see the module
    docstring's Failure modes paragraph. Never `Optional[bool]`: a caller
    that cannot determine a fact must pass the string `"not_checked"`
    explicitly, which every gate below treats as inconclusive-and-fails-
    closed, never as a silent green light.
    """

    dirty_status: str  # "clean" | "dirty" | "not_checked"
    head_reachable: str  # "reachable" | "unreachable" | "not_checked"
    ls_remote_status: str  # "pushed" | "not_pushed" | "error" | "not_checked"
    merge_evidence: str  # "merged" | "unmerged" | "not_checked"
    content_subsumption: str  # "subsumed" | "not_subsumed" | "not_checked" (DS-153 B1)
    pr_state: str  # "OPEN" | "MERGED" | "CLOSED" | "NONE" | "not_checked"


def _check_merge_evidence(facts: DispositionFacts) -> Optional[Disposition]:
    if facts.merge_evidence == "merged":
        return Disposition.ELIGIBLE
    return None  # "unmerged" / "not_checked": inconclusive, try the next source


def _check_content_subsumption(facts: DispositionFacts) -> Optional[Disposition]:
    """DS-153 B1: proves the LOCAL TIP's content is on the base branch via
    the plan's four-layer subsumption predicate (computed entirely by the
    caller - `bin/ds-branch-prune` - and passed in as a fact, exactly like
    every other field on this dataclass). `"not_checked"` and
    `"not_subsumed"` are both inconclusive here, never a green light.
    """
    if facts.content_subsumption == "subsumed":
        return Disposition.ELIGIBLE
    return None


def _check_pr_state_lenient(facts: DispositionFacts) -> Optional[Disposition]:
    """Legacy/unchanged semantics, used ONLY by `disposition_for` (live
    worktree REMOVAL). `git worktree remove` does not destroy commits - the
    branch and its objects survive - so a bare MERGED PR is still treated
    as sufficient evidence. See DS-153 Amendment B1.
    """
    if facts.pr_state == "OPEN":
        return Disposition.SKIP_PR_OPEN
    if facts.pr_state == "MERGED":
        return Disposition.ELIGIBLE
    return None  # "CLOSED" / "NONE" / "not_checked": inconclusive


def _check_pr_state_strict(facts: DispositionFacts) -> Optional[Disposition]:
    """DS-153 B1: used ONLY by `disposition_for_orphan_branch` (BRANCH
    DELETION, `git branch -D`). Reaching this check means `merge_evidence`
    and `content_subsumption` were both already inconclusive, so a bare
    MERGED PR is now affirmatively INSUFFICIENT - it proves a PR merged,
    not that this local tip's content is on the base branch. Returns the
    TERMINAL `SKIP_PR_MERGED_UNPROVEN`, not an inconclusive `None`: this is
    intentionally NOT a fall-through to `ls_remote_status`, since "pushed"
    says nothing that would rescue a MERGED-but-unproven PR.
    """
    if facts.pr_state == "OPEN":
        return Disposition.SKIP_PR_OPEN
    if facts.pr_state == "MERGED":
        return Disposition.SKIP_PR_MERGED_UNPROVEN
    return None  # "CLOSED" / "NONE" / "not_checked": inconclusive


def _check_ls_remote(facts: DispositionFacts) -> Optional[Disposition]:
    if facts.ls_remote_status == "error":
        return Disposition.SKIP_LS_REMOTE_ERROR
    if facts.ls_remote_status == "not_pushed":
        return Disposition.SKIP_NOT_PUSHED
    return None  # "pushed" alone is not proof of merge; inconclusive


#: plan §API / interface design. The evidence-source precedence used by both
#: `disposition_for` and `disposition_for_orphan_branch` when no single
#: source is definitive on its own. ORDER IS LOAD-BEARING (this is the
#: mutation-switch QA scenario 6 exercises): `merge_evidence` first because
#: it is the strongest, most direct signal (proof the branch's content
#: landed on the base branch); `content_subsumption` second (DS-153 B1) -
#: the plan's four-layer subsumption predicate, itself a stronger-than-PR
#: proof that a squashed/rebased branch's delta is on the base branch, so it
#: is checked before a mere PR-merged signal; `pr_state` third because
#: `OPEN` is a hard safety override that must win over an unrelated
#: push-status signal, and (for the lenient/worktree-removal caller only)
#: `MERGED` is corroborating evidence when ancestry-based `merge_evidence`
#: could not be computed (e.g. after a history rewrite); `ls_remote_status`
#: last because "pushed" alone says nothing about merge status - it only
#: ever produces a SKIP_* here, never an ELIGIBLE.
MERGE_EVIDENCE_ORDER: Tuple[str, ...] = (
    "merge_evidence",
    "content_subsumption",
    "pr_state",
    "ls_remote_status",
)

_EVIDENCE_CHECKS_LENIENT: Dict[str, Callable[[DispositionFacts], Optional[Disposition]]] = {
    "merge_evidence": _check_merge_evidence,
    "content_subsumption": _check_content_subsumption,
    "pr_state": _check_pr_state_lenient,
    "ls_remote_status": _check_ls_remote,
}

_EVIDENCE_CHECKS_STRICT: Dict[str, Callable[[DispositionFacts], Optional[Disposition]]] = {
    "merge_evidence": _check_merge_evidence,
    "content_subsumption": _check_content_subsumption,
    "pr_state": _check_pr_state_strict,
    "ls_remote_status": _check_ls_remote,
}


def _resolve_merge_evidence(
    facts: DispositionFacts,
    merge_evidence_order: Tuple[str, ...],
    *,
    strict_pr_state: bool,
) -> Disposition:
    """DS-153 B1: `strict_pr_state` is an explicit, required-by-keyword
    parameter - not an implicit caller convention - selecting which
    `pr_state` check function participates in evidence resolution.
    `strict_pr_state=False` (used by `disposition_for`, live worktree
    removal) keeps the legacy MERGED-is-sufficient behavior.
    `strict_pr_state=True` (used by `disposition_for_orphan_branch`, branch
    deletion) makes a bare MERGED PR terminally insufficient absent
    `content_subsumption == "subsumed"`. Both variants share every other
    evidence source unchanged.
    """
    checks = _EVIDENCE_CHECKS_STRICT if strict_pr_state else _EVIDENCE_CHECKS_LENIENT
    for source in merge_evidence_order:
        verdict = checks[source](facts)
        if verdict is not None:
            return verdict
    # Every source was inconclusive: fail closed rather than default ELIGIBLE.
    return Disposition.SKIP_AMBIGUOUS_NO_PR


def disposition_for(
    entry: WorktreeEntry,
    wt_class: WorktreeClass,
    facts: DispositionFacts,
    *,
    merge_evidence_order: Tuple[str, ...] = MERGE_EVIDENCE_ORDER,
) -> Disposition:
    """The locked/dirty/branch-vs-detached/merge-evidence-independent-of-push
    disposition gate for a LIVE worktree entry (has a `WorktreeClass`).

    Gate order: class (MAIN/UNMANAGED never proceed) -> locked -> dirty
    (fails closed on anything but exactly "clean") -> detached-vs-branched
    (a detached HEAD has no branch to check merge evidence against; it is
    ELIGIBLE only when `facts.head_reachable == "reachable"` - i.e. the
    commit is still referenced elsewhere and removing this worktree cannot
    orphan it - and SKIP_UNREFERENCED_COMMIT otherwise, "otherwise"
    including `"not_checked"`) -> merge-evidence resolution via
    `merge_evidence_order`, independent of push status (a locally-verified-
    merged branch does not need its push status checked at all; push status
    is consulted only once merge evidence and PR state are both
    inconclusive).
    """
    if wt_class is WorktreeClass.MAIN:
        return Disposition.SKIP_MAIN
    if wt_class is WorktreeClass.UNMANAGED:
        return Disposition.SKIP_UNMANAGED
    if entry.locked:
        return Disposition.SKIP_LOCKED
    if facts.dirty_status != "clean":
        return Disposition.SKIP_DIRTY

    if entry.branch is None:
        # Detached HEAD (or otherwise branchless) - no branch to run merge
        # evidence against; the only question is whether the commit is
        # referenced elsewhere.
        if facts.head_reachable == "reachable":
            return Disposition.ELIGIBLE
        return Disposition.SKIP_UNREFERENCED_COMMIT

    # DS-153 B1: strict_pr_state=False - this is the WORKTREE-REMOVAL path
    # (`git worktree remove`, which does not destroy commits), so a bare
    # MERGED PR remains sufficient evidence, unchanged from pre-DS-153
    # behavior. See _resolve_merge_evidence's docstring and Amendment B1.
    return _resolve_merge_evidence(facts, merge_evidence_order, strict_pr_state=False)


#: Default `base_branches` for `disposition_for_orphan_branch` - matches the
#: exclusion set the live §Branch prune bullet 2 filter already applies
#: (`grep -vE '^[*+]|(^| )(main|master)$'`). Callers with a differently-named
#: base branch (e.g. `develop`) MUST pass their own `base_branches` tuple
#: explicitly - this function never infers it from the environment.
DEFAULT_BASE_BRANCHES: Tuple[str, ...] = ("main", "master")


def disposition_for_orphan_branch(
    branch: str,
    facts: DispositionFacts,
    *,
    merge_evidence_order: Tuple[str, ...] = MERGE_EVIDENCE_ORDER,
    base_branches: Tuple[str, ...] = DEFAULT_BASE_BRANCHES,
) -> Disposition:
    """Disposition for a BRANCH with no live worktree at all - no
    `WorktreeEntry`, no `WorktreeClass` involved (used by branch-prune
    bullets 1/2 and the session-start-prune dangling-branch sweep - see
    content/references/worktree-lifecycle.md §Branch prune / §Session-start
    prune script). By construction this function has no code path that can
    produce `SKIP_MAIN`, `SKIP_UNMANAGED`, `SKIP_LOCKED`, `SKIP_DIRTY`, or
    `SKIP_UNREFERENCED_COMMIT` - none of those concepts (a live checkout,
    a lock, a dirty tree, a detached HEAD) apply to a branch with no
    worktree. Absent a `base_branches` match (below) it reduces to the same
    merge-evidence resolution `disposition_for` falls through to for a
    branched, clean, unlocked entry.

    `base_branches` is an explicit, caller-supplied guard, never inferred:
    when `branch` is a member (case-sensitive exact match), this function
    returns `SKIP_BASE_BRANCH` unconditionally, before any evidence source is
    consulted - a base/integration branch is never eligible for deletion
    regardless of what `facts` claims about its merge status. This closes
    the gap where `disposition_for_orphan_branch("main", merge_evidence=
    "merged", ...)` previously resolved `ELIGIBLE`: `merge_evidence="merged"`
    is trivially and permanently true for a base branch against itself,
    which made the merge-evidence-first ordering actively dangerous for this
    one input class. Every one of this ticket's 11 call sites already
    excludes `main`/`master` via its own pre-model selection filter (see
    content/references/worktree-lifecycle.md §Branch prune bullet 2's
    `grep -vE`), so this guard is a defense-in-depth floor for any FUTURE
    caller that forgets to - not a behavior change for the callers that
    exist today.

    DS-153 Amendment B1: this function ALWAYS resolves evidence with
    `strict_pr_state=True` - a bare `pr_state == "MERGED"` is TERMINAL
    (`SKIP_PR_MERGED_UNPROVEN`), not `ELIGIBLE`. Reaching the `pr_state`
    check means both `merge_evidence` (ancestry) and `content_subsumption`
    (the plan's four-layer subsumption predicate) were already
    inconclusive, so "a PR merged" is affirmatively insufficient proof that
    THIS local tip's content is on the base branch - the exact forbidden
    predicate the plan was written to eliminate for a `git branch -D` call
    site. This is a deliberate divergence from `disposition_for` (live
    worktree removal), which stays lenient because `git worktree remove`
    does not destroy commits. See `_resolve_merge_evidence`'s docstring for
    the shared mechanism and `.agentic/ds-153-plan.md` Amendment B1 for the
    full rationale (a worktree-removal-strength bar applied to a
    data-loss-capable branch deletion is unsafe in one direction; applied
    the other way around, it strands every squash-merged live worktree).
    """
    if branch in base_branches:
        return Disposition.SKIP_BASE_BRANCH
    del branch  # beyond the guard above, identifies the branch to the
    # caller/audit trail only - the remaining logic depends solely on `facts`.
    return _resolve_merge_evidence(facts, merge_evidence_order, strict_pr_state=True)
