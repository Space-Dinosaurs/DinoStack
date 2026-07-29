#!/usr/bin/env python3
"""
Purpose: Executable reference implementation of the DS-108 task-state fold. This
         module is the SINGLE NORMATIVE DEFINITION of the fold's state machine.
         `docs/planning/tasks-jsonl-cross-session/plan.md` section 3.2 points at
         this file rather than restating the algorithm in prose, so the
         "two representations that disagree" defect (r1-r4) cannot recur.

Public API:
  fold(records)                  -> dict[task_id, FoldResult]
  fold_group(records, ...)       -> FoldResult for a single task_id
  classify(folded, viewer, ...)  -> row label from plan.md section 2
  holds_branch(folded, viewer)   -> the rows 9/16 splitting predicate, computed
                                    from the RAW group (never from provenance)
  may_merge(folded, viewer)      -> plan.md section 3.3 gate point 3
  FoldResult.raw                 -> the group's records in arrival order; what
                                    holds_branch() reads
  FoldResult.record()            -> the folded record as a plain dict. WARNING:
                                    for a legacy group this carries
                                    `session_id: LEGACY_SENTINEL`; never write
                                    it back to disk (see the method docstring)
  MERGE_PERMITTED / SPAWN_PERMITTED -> the row sets the section 3.3 gate reads
  LEGACY_SENTINEL                -> the folded owner of a record with no
                                    `session_id` (plan.md section 2 row 12)
  Mutation switches (test-only), SIX: DONE_GUARD, OWNER_TEST, ORDER_MODE,
  FRESHNESS_MODE, LEGACY_MODE, WHITELIST_MODE.

Upstream deps: none (stdlib only, no I/O).

Downstream consumers: test_fold_invariants.py (property tests for I1-I5 plus
                      the row-12 legacy routing); plan.md section 3.2
                      (normative pointer); the engineer implementing the spec
                      prose in content/commands/ds-implement-ticket.md.

Failure modes: a record missing `task_id` is SKIPPED by `fold` and counted in
               `FoldResult.skipped` - it never raises. A record missing
               `session_id` is LEGACY (the documented schema in
               content/references/task-state-file.md never mandated the field,
               so every pre-fix record and every spec-compliant partial append
               is one): it folds normally under the owner `LEGACY_SENTINEL`,
               which no viewer can ever match and which forces `stale=True` in
               `classify` - see plan.md section 2 row 12 and AC25. It is NOT
               dropped and NOT counted as skipped. `fold_group` accepts such a
               record; it raises `KeyError` only under the `legacy_mode="drop"`
               mutation, which reintroduces the r5 defect. This module never
               performs I/O and never mutates its inputs.

Performance: O(n log n) per group (one sort), single pass thereafter. Pure.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Tuple

# --------------------------------------------------------------------------
# Normative constants
# --------------------------------------------------------------------------

#: plan.md section 3.2 step 5. Only `done` is absorbing. NOT the sync-terminal
#: set (`{done, failed, blocked, abandoned}`, plan.md section 3.4 / R12).
FOLD_ABSORBING = frozenset({"done"})

#: plan.md section 3.4 / R12. The full writer terminal set. Named here so the
#: two sets can never be re-derived from each other.
SYNC_TERMINAL = frozenset({"done", "failed", "blocked", "abandoned"})

#: plan.md section 3.2 step 7. Fields that may cross a `session_id` generation
#: boundary. WHITELIST, not blacklist: a field added to the schema later is
#: session-scoped until someone deliberately adds it here.
CROSS_GENERATION_WHITELIST = frozenset(
    {
        "task_id",
        "ticket_id",
        "unit_slug",
        "depends_on",
        "created_at",
        "inputs",
    }
)

#: Fields governed by their own steps rather than by the whitelist test.
#:
#: `updated_at` is deliberately NOT here. It is an ordinary session-scoped field:
#: it is folded from the LATEST ARRIVAL-ORDER RECORD OF THE FOLDED OWNER, any
#: status, output-only appends included. That is the reading the rows 7/8
#: staleness test actually asks for - "is the session that holds this unit still
#: alive?" - and it is the only reading a non-owner's append cannot refresh.
#: A foreign stray `pending` (AC20 concedes W2's suppression is only
#: defence-in-depth) must never renew the incumbent's freshness, because that
#: would pin row 7 permanently and hard-block legitimate orphan recovery.
_GOVERNED = frozenset({"status", "session_id"})

#: Internal ordering key injected by `fold`; never part of a real record.
_SEQ = "_seq"

#: plan.md section 2 row 12 / AC25. The folded owner of any record that carries
#: no `session_id`. The documented schema
#: (content/references/task-state-file.md) never mandated the field - zero
#: mentions - so every pre-fix on-disk record and every spec-compliant partial
#: append is legacy. Three properties are normative and are asserted by
#: `test_fold_invariants.check_legacy`:
#:
#:   1. It FOLDS. A legacy record is never discarded, so a legacy group never
#:      folds to nothing and never routes a reader onto the no-task-state
#:      (spawn-and-merge) path. Discarding was the r5 defect.
#:   2. It NEVER self-matches a viewer. No session may read a legacy group as
#:      `own`, so rows 1-4 and `may_merge` are unreachable for it - nobody can
#:      prove they authored an unattributed record. A legacy record carrying
#:      `branch_name` is therefore claimable by NO viewer: `holds_branch`
#:      returns False for the sentinel, so the rows 9/16 split for a legacy
#:      group is decided solely by the viewer's OWN build records.
#:   3. It FORCES `stale=True` in `classify`, so row 7 is unreachable per row
#:      12 ("never row 7"; blocking on an id that cannot be shown live would
#:      deadlock every pre-fix project). This also supplies the answer for a
#:      legacy record with no `updated_at` at all, where the staleness
#:      predicate would otherwise have no defined value.
#:   4. It COLLAPSES every pre-fix writer into ONE folded identity, and that
#:      is not free: I1 (at most one merger) and I4 (only the owner
#:      transitions) provide NO protection AMONG legacy writers. Two distinct
#:      pre-fix sessions are the same `session_id` to every reader, so I1's
#:      merger set cannot exceed one by construction there (it is a set of
#:      ids, and both writers carry the same id), and a second pre-fix
#:      session's `done` is admitted under the first's ownership because
#:      `sid == owner` holds. Neither harness check can see the difference -
#:      `check_I4` reads `Transition.session_id`, the sentinel for both. The
#:      protection over this population is NOT I1/I4 but clause 2: no legacy
#:      group is mergeable AT ALL (`may_merge(res, <legacy>) is False`), so
#:      the double-merge I1 exists to prevent is unreachable by a different
#:      route. The residue is that a modern reader of a legacy group whose
#:      `done` came from a second pre-fix writer reads row 9 ("do not spawn,
#:      dependency satisfied") while the claiming pre-fix session may still be
#:      running. That is disclosed rather than fixed: an unattributed record
#:      carries no information that could distinguish the two writers.
#:
#: The value is outside the `<ISO-date>-<4hex>` namespace the conductor mints
#: (ds-implement-ticket.md:1671), so it can never collide with a real id.
LEGACY_SENTINEL = "<legacy>"

# --------------------------------------------------------------------------
# Mutation switches - DEFAULTS ARE THE NORMATIVE BEHAVIOUR.
#
# These exist so test_fold_invariants.py can reintroduce a historical defect and
# demonstrate that the corresponding property test goes RED. Production readers
# of this module must never pass a non-default value.
# --------------------------------------------------------------------------

#: I3. When True, an `in_progress` claim landing after the folded status is
#: already `done` is NOT honored. Setting False reintroduces r3-Major-1.
DONE_GUARD = True

#: I4. When True, a non-claim status transition is admitted only from the
#: session that is the folded owner at that point. Setting False reintroduces
#: r4-Major-1 (a concurrent Phase-3b `pending` regressing a live `in_progress`).
OWNER_TEST = True

#: plan.md section 3.2 step 3. "arrival" = O_APPEND file-line order only, which
#: is a real total order and is prefix-monotonic by construction. "updated_at"
#: is the r4 ordering ((updated_at ASC, line order ASC)); it is NOT
#: prefix-monotonic when a record arrives carrying an earlier timestamp, and it
#: breaks the freeze lemma. Retained only as a mutation switch.
ORDER_MODE = "arrival"

#: I5. "owner" = the folded `updated_at` is the one on the latest arrival-order
#: record of the folded OWNER (the normative reading; see `_GOVERNED`).
#: "group" is the rejected reading - the latest record in the group, whoever
#: wrote it - under which a foreign stray `pending` refreshes the incumbent's
#: freshness and permanently pins row 7. Retained only as a mutation switch.
FRESHNESS_MODE = "owner"

#: AC25 / plan.md section 2 row 12. "sentinel" = a record with no `session_id`
#: folds under `LEGACY_SENTINEL` (the normative reading). "drop" is the r5
#: defect: `fold` discarded such a record and `fold_group` raised `KeyError` on
#: it, so a legacy group folded to NOTHING and row 12's whole disposition was
#: unreachable. Retained only as a mutation switch.
LEGACY_MODE = "sentinel"

#: AC23. "spec" = `CROSS_GENERATION_WHITELIST` exactly as declared above (the
#: normative reading). "drift" adds `branch_name` to it, which is the precise
#: schema drift AC23 exists to prevent: a session-scoped build field that
#: crosses a `session_id` generation boundary, so the folded record can pair a
#: superseded generation's `branch_name` with the current owner's `done`.
#: Unlike an injected `FoldResult`, this is a plausible edit to a real
#: constant, and I2's build-field half catches it on GENERATED logs.
WHITELIST_MODE = "spec"

#: The single field admitted by the `whitelist_mode="drift"` mutation.
_WHITELIST_DRIFT = frozenset({"branch_name"})


def _whitelist(whitelist_mode: str) -> frozenset:
    if whitelist_mode == "spec":
        return CROSS_GENERATION_WHITELIST
    if whitelist_mode == "drift":
        return CROSS_GENERATION_WHITELIST | _WHITELIST_DRIFT
    raise ValueError("unknown WHITELIST_MODE: %r" % (whitelist_mode,))


# --------------------------------------------------------------------------
# Result types
# --------------------------------------------------------------------------


@dataclass
class Transition:
    """One record's disposition under the state machine, for I3/I4 auditing."""

    seq: int
    session_id: str
    status: Optional[str]
    owner_before: Optional[str]
    owner_after: Optional[str]
    status_before: Optional[str]
    status_after: Optional[str]
    #: one of: bootstrap, claim, claim_rejected_post_terminal, transition,
    #: transition_rejected_unowned, transition_rejected_absorbed, no_status
    kind: str = "no_status"


@dataclass
class FoldResult:
    """The folded record plus the audit trail the invariants are checked against."""

    task_id: str
    session_id: Optional[str] = None  # the folded owner
    status: Optional[str] = None
    fields: Dict[str, Any] = field(default_factory=dict)
    #: field name -> session_id that contributed the surviving value
    provenance: Dict[str, str] = field(default_factory=dict)
    trace: List[Transition] = field(default_factory=list)
    #: session_id that appended the honored `done`, or None
    done_by: Optional[str] = None
    skipped: int = 0
    #: the group's raw records in arrival order. `holds-a-branch` is a property
    #: of the RAW LOG, not of the folded record: the whitelist deliberately
    #: excludes a superseded generation's `branch_name` from `fields`, which is
    #: exactly the population rows 9/16 must be split on.
    raw: List[Dict[str, Any]] = field(default_factory=list)

    def record(self) -> Dict[str, Any]:
        """The folded record as a plain dict (what a reader consumes).

        NEVER WRITE THIS BACK TO DISK. For a legacy group it carries
        `session_id: LEGACY_SENTINEL` - a value that exists only as a folded
        identity and is not part of the on-disk schema. Inert today because
        nothing persists a folded record (plan.md:142 "Never a rewrite", and
        log compaction is a deferred default at plan.md section 8, "Default:
        none"). If compaction is ever adopted, a compactor that appends
        `record()` would inject `<legacy>` into the file as a real
        `session_id`, at which point pre-fix writers would become
        indistinguishable from a *written* identity rather than from an absent
        one - strip or re-derive `session_id` first.
        """
        out = dict(self.fields)
        out["task_id"] = self.task_id
        out["session_id"] = self.session_id
        if self.status is not None:
            out["status"] = self.status
        return out

    @property
    def updated_at(self) -> Any:
        """The folded `updated_at` - see `_GOVERNED`. None when absent."""
        return self.fields.get("updated_at")


# --------------------------------------------------------------------------
# The fold
# --------------------------------------------------------------------------


def _sid_of(r: Dict[str, Any], legacy_mode: str) -> str:
    """The record's effective session_id. See `LEGACY_SENTINEL`."""
    if legacy_mode == "drop":
        return r["session_id"]  # r5 behaviour: raises on a legacy record
    return r.get("session_id", LEGACY_SENTINEL)


def _order(group: List[Dict[str, Any]], order_mode: str) -> List[Dict[str, Any]]:
    if order_mode == "arrival":
        return sorted(group, key=lambda r: r[_SEQ])
    if order_mode == "updated_at":
        return sorted(group, key=lambda r: (r.get("updated_at", 0), r[_SEQ]))
    raise ValueError("unknown ORDER_MODE: %r" % (order_mode,))


def fold_group(
    records: Iterable[Dict[str, Any]],
    *,
    task_id: Optional[str] = None,
    done_guard: bool = None,
    owner_test: bool = None,
    order_mode: str = None,
    freshness_mode: str = None,
    legacy_mode: str = None,
    whitelist_mode: str = None,
) -> FoldResult:
    """Fold one `task_id` group. See plan.md section 3.2.

    The machine carries the state `(owner, status, fields)` and applies each
    record as a transition whose admissibility depends on the state BEFORE it:

      * `status: in_progress` is a CLAIM. It sets `owner := record.session_id`,
        UNLESS the folded status is already `done`, in which case the claim is
        not honored (I3) and the record is a row-16 signal.
      * any other `status` value is a TRANSITION, admitted only if
        `record.session_id == owner` at that point (I4), and further ignored if
        the folded status is already `done` (step 5, `done` is absorbing).
      * a record with NO `status` field is neither a claim nor a transition.
    """
    done_guard = DONE_GUARD if done_guard is None else done_guard
    owner_test = OWNER_TEST if owner_test is None else owner_test
    order_mode = ORDER_MODE if order_mode is None else order_mode
    freshness_mode = FRESHNESS_MODE if freshness_mode is None else freshness_mode
    legacy_mode = LEGACY_MODE if legacy_mode is None else legacy_mode
    whitelist_mode = WHITELIST_MODE if whitelist_mode is None else whitelist_mode
    whitelist = _whitelist(whitelist_mode)
    if freshness_mode not in ("owner", "group"):
        raise ValueError("unknown FRESHNESS_MODE: %r" % (freshness_mode,))
    if legacy_mode not in ("sentinel", "drop"):
        raise ValueError("unknown LEGACY_MODE: %r" % (legacy_mode,))

    group = [dict(r) for r in records]
    for i, r in enumerate(group):
        r.setdefault(_SEQ, i)
    if task_id is None:
        task_id = group[0]["task_id"] if group else ""

    ordered = _order(group, order_mode)

    owner: Optional[str] = None
    status: Optional[str] = None
    done_by: Optional[str] = None
    trace: List[Transition] = []

    for r in ordered:
        sid = _sid_of(r, legacy_mode)
        owner_before, status_before = owner, status
        kind = "no_status"

        if owner is None:
            # Step 6 fallback: absent any `in_progress` claim, the folded
            # session_id is that of the EARLIEST record. Any later claim
            # overrides this provisional bootstrap.
            owner = sid
            kind = "bootstrap"

        s = r.get("status")
        if s == "in_progress":
            if status in FOLD_ABSORBING and done_guard:
                kind = "claim_rejected_post_terminal"  # I3
            else:
                owner = sid
                status = "in_progress"
                kind = "claim"
        elif s is not None:
            if owner_test and sid != owner:
                kind = "transition_rejected_unowned"  # I4
            elif status in FOLD_ABSORBING:
                kind = "transition_rejected_absorbed"  # step 5
            else:
                status = s
                kind = "transition"
                if s == "done":
                    done_by = sid

        trace.append(
            Transition(
                seq=r[_SEQ],
                session_id=sid,
                status=s,
                owner_before=owner_before,
                owner_after=owner,
                status_before=status_before,
                status_after=status,
                kind=kind,
            )
        )

    # ---- Pass 2: fields. Step 4 (field-level LWW) bounded by step 7. ----
    fields: Dict[str, Any] = {}
    provenance: Dict[str, str] = {}
    for r in ordered:
        sid = _sid_of(r, legacy_mode)
        for k, v in r.items():
            if k == _SEQ or k in _GOVERNED:
                continue
            root = k.split(".", 1)[0]
            if k == "updated_at" and freshness_mode == "group":
                fields[k] = v
                provenance[k] = sid
            elif root in whitelist:
                fields[k] = v
                provenance[k] = sid
            elif sid == owner:
                fields[k] = v
                provenance[k] = sid
            # else: session-scoped field from a superseded generation. Dropped.

    return FoldResult(
        task_id=task_id,
        session_id=owner,
        status=status,
        fields=fields,
        provenance=provenance,
        trace=trace,
        done_by=done_by,
        raw=ordered,
    )


def fold(
    lines: Iterable[Dict[str, Any]],
    **kwargs: Any,
) -> Dict[str, FoldResult]:
    """Fold a whole log. `lines` is the append order (O_APPEND arrival order).

    Records without a `task_id` are skipped and counted, per step 1. A record
    without a `session_id` is LEGACY, not unparseable: it is folded under
    `LEGACY_SENTINEL` and is never skipped (row 12 / AC25). Under the
    `legacy_mode="drop"` mutation it is skipped instead, which is the r5 defect.
    """
    legacy_mode = kwargs.get("legacy_mode") or LEGACY_MODE
    groups: Dict[str, List[Dict[str, Any]]] = {}
    skipped = 0
    for i, raw in enumerate(lines):
        if not isinstance(raw, dict) or "task_id" not in raw:
            skipped += 1
            continue
        if legacy_mode == "drop" and "session_id" not in raw:
            skipped += 1
            continue
        r = dict(raw)
        r[_SEQ] = i
        groups.setdefault(r["task_id"], []).append(r)

    out: Dict[str, FoldResult] = {}
    for tid, group in groups.items():
        res = fold_group(group, task_id=tid, **kwargs)
        res.skipped = skipped
        out[tid] = res
    return out


# --------------------------------------------------------------------------
# Row classification (plan.md section 2 B x C matrix)
# --------------------------------------------------------------------------

#: Live schema at content/commands/ds-implement-ticket.md:1497 (`branch_name`)
#: and :1501 (`outputs.skeptic_status`, dotted - NOT bare `skeptic_status`).
_BUILD_FIELDS = ("branch_name", "commit_sha", "outputs.skeptic_status")


def holds_branch(res: FoldResult, viewer: str) -> bool:
    """True when `viewer` appended a build record (branch/commit) for this task.

    Scans the RAW group, not `res.provenance`. `provenance` is populated only
    from records whose `session_id` equals the folded owner, so reading it here
    is structurally incapable of returning True for a non-owner - which is
    exactly the population the rows 9/16 split is about (r5-Major-2). A
    superseded generation's `branch_name` is dropped from the folded record by
    the whitelist and survives only on disk; that is where the predicate looks.

    LEGACY (`LEGACY_SENTINEL`, row 12): a record with no `session_id` that
    carries `branch_name` is claimable by NO viewer - nobody can prove they
    authored an unattributed record - so this returns False for the sentinel
    viewer. Consequence, stated rather than implied: the rows 9/16 split for a
    legacy group is decided solely by the viewer's own attributed build
    records, and a legacy group whose only build record is unattributed routes
    every viewer to row 9.
    """
    if viewer == LEGACY_SENTINEL:
        return False
    return any(
        r.get("session_id", LEGACY_SENTINEL) == viewer
        and any(k in _BUILD_FIELDS for k in r)
        for r in res.raw
    )


def classify(
    res: FoldResult,
    viewer: str,
    *,
    branch: Optional[bool] = None,
    stale: bool = False,
    dispossessed: Optional[bool] = None,
) -> str:
    """Return the plan.md section 2 row for `viewer`'s read of the folded record.

    `branch` = the viewer holds an outstanding branch for the task. DEFAULT
               `None` means "derive it from the log via `holds_branch`" - the
               grid is computed, never supplied. An explicit bool is honored
               only so a caller with out-of-band knowledge can override.
    `stale`  = the folded `updated_at` (the owner's latest append, see
               `_GOVERNED`) is older than the 10-minute threshold.
    """
    if branch is None:
        branch = holds_branch(res, viewer)
    legacy = res.session_id == LEGACY_SENTINEL
    #: Row 12 / AC25. A legacy owner never self-matches, so rows 1-4 are
    #: unreachable for it, and it is forced stale so row 7 is too. `stale` is
    #: overridden rather than merely defaulted: an absent `session_id` cannot
    #: be shown live at all, and a legacy record need not even carry
    #: `updated_at` for the 10-minute test to consume.
    if legacy:
        stale = True
    own = res.session_id == viewer and not legacy
    st = res.status
    if dispossessed is None:
        dispossessed = (
            viewer != LEGACY_SENTINEL
            and not own
            and any(t.session_id == viewer and t.kind == "claim" for t in res.trace)
        )

    if dispossessed:
        if st in FOLD_ABSORBING:
            return "row16"
        return "row15" if res.trace and res.trace[-1].session_id == viewer else "row14"
    if own:
        if st == "pending":
            return "row1"
        if st == "in_progress":
            return "row2"
        if st == "done":
            return "row3"
        return "row4"
    # foreign. Reachable for a legacy owner (row 12), which arrives here
    # forced foreign + stale: `pending` -> row 6, `in_progress` -> row 8 and
    # NEVER row 7, `done` -> row 9/16 by the viewer's own build records,
    # everything else -> row 10. That is row 12's disposition exactly.
    if st == "pending":
        return "row6"
    if st == "in_progress":
        return "row8" if stale else "row7"
    if st == "done":
        return "row16" if branch else "row9"
    return "row10"


#: Rows that permit a merge. Exactly one (plan.md section 2 row 3).
MERGE_PERMITTED = frozenset({"row3"})

#: Rows that permit a spawn (plan.md section 2). Rows 14/15/16 forbid it.
SPAWN_PERMITTED = frozenset({"row1", "row4", "row6", "row8", "row10"})


def may_merge(res: FoldResult, viewer: str) -> bool:
    """plan.md section 3.3 gate point 3, fold-before-merge.

    Merge only if `owner == self AND status == done`.

    A legacy owner (`LEGACY_SENTINEL`, row 12) never self-matches, so no viewer
    may ever merge a legacy-owned group - including a viewer that is itself
    unattributed. Two pre-fix sessions are mutually indistinguishable, so
    permitting the match would let both merge and break I1.
    """
    return (
        res.session_id == viewer
        and res.session_id != LEGACY_SENTINEL
        and res.status == "done"
    )
