#!/usr/bin/env python3
"""
Purpose: Executable reference implementation of the DS-90 staging-drain
         algorithm - the single normative definition of which staged/fresh
         learning entries get PRESENTED to the adjudicator on a given
         `/ds-wrap` run, given a bounded per-run cap and a reserve carve-out
         that protects fresh entries from starvation behind an
         ever-growing staged backlog. It models ONLY the algorithm: whether
         Part B step 0 (the drain step) is REACHED AT ALL on a given run is
         `reach_model.py`'s contract, not this file's. A reader must not
         conclude from a green drain suite that the drain runs - only that
         IF it runs, these five properties (D1-D5) hold.

Public API:
  Outcome                 -> enum, exactly 9 members (1 appended, 2
                             superseded-in-place, 3 skipped-duplicate, 4
                             skipped-already-a-structured-learning, 5
                             consolidated, 6 deferred-to-memory-pending, 7
                             rejected-on-the-merits, 8 dropped-by-cap, 9
                             never-adjudicated)
  PRESENTED_OUTCOMES       -> frozenset, outcomes 1-7 (this run's judged set)
  UNPRESENTED_OUTCOMES     -> frozenset, outcomes 8-9 (still in the backlog)
  DrainResult              -> dataclass: .order, .outcomes, .presented_sids,
                              .reject_disposition (echoed input, consulted
                              by retained())
  drain(staged, fresh, dispositions, *, cap=CAP, reserve=RESERVE,
        order_mode=None, reject_disposition=None, reserve_rule=None)
                           -> DrainResult (dispositions values, when given,
                              MUST be drawn from PRESENTED_OUTCOMES - an
                              UNPRESENTED-category value is rejected
                              fail-closed, not honoured)
  presented(result)        -> arrival-ordered list of DRAINED entries
                              (presented to the adjudicator this run)
  retained(result)         -> arrival-ordered list of RETAINED entries (not
                              presented this run, PLUS - under the
                              REJECT_DISPOSITION="retained" mutation - any
                              REJECTED_ON_THE_MERITS entry, which is the
                              defect this mutation models: a rejected entry
                              that never actually leaves the pool)
  CAP, RESERVE             -> the normative per-run cap (3) and fresh
                              reserve (1)
  Mutation switches (test-only), THREE: REJECT_DISPOSITION, ORDER_MODE,
  RESERVE_RULE.

Upstream deps: none (stdlib only: dataclasses, enum).

Downstream consumers: test_drain_invariants.py (D1-D5 property tests, tier 1
                      exhaustive + tier 2 seeded-random multi-run
                      simulation); PR 2's edit to content/commands/ds-wrap.md,
                      which implements the drain step this file specifies.

Failure modes: `drain()` raises `ValueError` on a missing or duplicate `sid`
               across the combined staged+fresh set, on an entry whose
               disposition is not a member of PRESENTED_OUTCOMES (an
               adjudicator cannot emit an UNPRESENTED-category verdict -
               those two labels are drain()'s own, applied only to entries
               it did not present), or on an entry whose disposition
               requires quote verification but whose `quote` field is
               missing/empty - FAIL-CLOSED ATOMICITY (D4): on any of these
               errors, drain() raises BEFORE computing any partial
               DrainResult; it never returns a half-formed result. Otherwise
               pure - no I/O, no filesystem, no network, no wall-clock.

Performance: O(n log n) per call (one sort under ORDER_MODE="date"; O(n)
             under the default "arrival" mode, already ordered by input
             position).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Set


CAP = 3
RESERVE = 1


class Outcome(Enum):
    """Exactly NINE members. See PRESENTED_OUTCOMES / UNPRESENTED_OUTCOMES
    for the two-way split this enum partitions into."""

    #: The staged/fresh entry was written to a durable store (memory.md or
    #: an AGENTS.md file) as a brand-new entry.
    APPENDED = auto()

    #: The entry replaced an existing durable entry in place (same topic,
    #: updated or corrected) - fold_model.py's I5/provenance analogue for
    #: the staging layer.
    SUPERSEDED_IN_PLACE = auto()

    #: Skipped because it duplicates the entry's own destination file, or
    #: duplicates another entry already presented earlier THIS SAME run.
    SKIPPED_DUPLICATE_OF_DESTINATION_OR_ALREADY_PRESENTED = auto()

    #: Skipped because the same fact is already captured as a structured
    #: `.agentic/learnings.md` entry (ds-wrap.md:296, "check whether a
    #: proposed memory entry is already captured here as a structured
    #: learning before proposing it").
    SKIPPED_ALREADY_A_STRUCTURED_LEARNING = auto()

    #: Merged with one or more other presented entries into a single
    #: durable entry (the staging-layer analogue of a semantic merge).
    CONSOLIDATED = auto()

    #: Routed to `.agentic/memory-pending.md` / `.agentic/agents-md-pending
    #: .md` rather than the live file (ds-wrap.md:473, :485 - the open-PR
    #: deferral pass: the entry's substance depends on an unmerged PR).
    DEFERRED_TO_MEMORY_PENDING = auto()

    #: Reviewed and explicitly declined on the merits (not a duplicate, not
    #: deferred - the adjudicator judged it not worth keeping).
    REJECTED_ON_THE_MERITS = auto()

    #: NOT presented this run because the per-run CAP (3) was reached before
    #: this entry's turn - an UNPRESENTED outcome, still in the backlog.
    DROPPED_BY_CAP = auto()

    #: NOT presented this run and NOT specifically bumped by the cap either
    #: (it simply has not reached the front of the arrival queue yet) - an
    #: UNPRESENTED outcome, still in the backlog. The default state of any
    #: entry drain() has never had a reason to look at.
    NEVER_ADJUDICATED = auto()


#: This run's judged set - every entry the adjudicator actually looked at.
PRESENTED_OUTCOMES = frozenset(
    {
        Outcome.APPENDED,
        Outcome.SUPERSEDED_IN_PLACE,
        Outcome.SKIPPED_DUPLICATE_OF_DESTINATION_OR_ALREADY_PRESENTED,
        Outcome.SKIPPED_ALREADY_A_STRUCTURED_LEARNING,
        Outcome.CONSOLIDATED,
        Outcome.DEFERRED_TO_MEMORY_PENDING,
        Outcome.REJECTED_ON_THE_MERITS,
    }
)

#: Still in the backlog - DRAINED never touched these this run.
UNPRESENTED_OUTCOMES = frozenset({Outcome.DROPPED_BY_CAP, Outcome.NEVER_ADJUDICATED})

assert PRESENTED_OUTCOMES | UNPRESENTED_OUTCOMES == set(Outcome)
assert PRESENTED_OUTCOMES & UNPRESENTED_OUTCOMES == set()


# --------------------------------------------------------------------------
# Mutation switches - DEFAULTS ARE THE NORMATIVE BEHAVIOUR.
# --------------------------------------------------------------------------

#: "removed" (default): a REJECTED_ON_THE_MERITS entry is terminal - once
#: presented and rejected, it never re-enters the pool. "retained" (non-
#: default): rejected entries are never actually removed from the backlog -
#: they keep re-occupying a presented slot on every future run without ever
#: resolving. Reddens D2 (residency bound - it never truly resolves) and D5
#: (no reserved-slot capture - it keeps recapturing a slot that should have
#: gone to the next entry in arrival order).
REJECT_DISPOSITION = "removed"

#: "arrival" (default): entries are ordered by arrival index (staged
#: entries - the existing backlog - before fresh entries, each in their own
#: list order). "date" (non-default): orders by a `date` field instead,
#: which is NOT guaranteed to be arrival-monotonic (an entry can be staged
#: today for content dated yesterday) and reddens D2.
ORDER_MODE = "arrival"

#: "staged-and-fresh-split" (default): at least RESERVE of the CAP slots on
#: any run are reserved for fresh entries when fresh entries exist,
#: preventing an ever-growing staged backlog from consuming the entire cap
#: indefinitely. "none" (non-default): no reservation - the first CAP
#: entries in arrival order are presented, full stop; a staged backlog >=
#: CAP starves fresh entries forever. Reddens D2.
RESERVE_RULE = "staged-and-fresh-split"


# --------------------------------------------------------------------------
# Result type
# --------------------------------------------------------------------------


@dataclass
class DrainResult:
    """`order` is the full combined staged+fresh set in arrival order (the
    ordering `retained()` and `presented()` preserve). `outcomes` maps sid
    -> Outcome for EVERY entry in `order` (never partial - see D4)."""

    order: List[Dict[str, Any]] = field(default_factory=list)
    outcomes: Dict[str, Outcome] = field(default_factory=dict)
    presented_sids: Set[str] = field(default_factory=set)
    reject_disposition: str = REJECT_DISPOSITION


def presented(result: DrainResult) -> List[Dict[str, Any]]:
    """Arrival-ordered entries DRAINED this run (presented to the
    adjudicator), regardless of what they were subsequently judged."""
    return [e for e in result.order if e["sid"] in result.presented_sids]


def retained(result: DrainResult) -> List[Dict[str, Any]]:
    """Arrival-ordered entries RETAINED - not presented this run, PLUS (only
    under the REJECT_DISPOSITION="retained" mutation) any entry whose
    outcome is REJECTED_ON_THE_MERITS: the mutation's defect is precisely
    that such an entry, though nominally judged, never actually leaves the
    backlog a caller feeds into the next run."""
    out = []
    for e in result.order:
        sid = e["sid"]
        if sid not in result.presented_sids:
            out.append(e)
        elif (
            result.reject_disposition == "retained"
            and result.outcomes.get(sid) == Outcome.REJECTED_ON_THE_MERITS
        ):
            out.append(e)
    return out


# --------------------------------------------------------------------------
# Validation (D4: fail-closed atomicity - raise BEFORE computing anything)
# --------------------------------------------------------------------------


def _validate(combined: List[Dict[str, Any]], dispositions: Dict[str, Any]) -> None:
    seen: Set[str] = set()
    for e in combined:
        sid = e.get("sid")
        if not sid:
            raise ValueError(f"entry missing required 'sid': {e!r}")
        if sid in seen:
            raise ValueError(f"duplicate sid: {sid!r}")
        seen.add(sid)

    for e in combined:
        sid = e["sid"]
        disp = dispositions.get(sid)
        #: An adjudicator can only emit a PRESENTED-category verdict. The two
        #: UNPRESENTED categories are drain()'s OWN labels for entries it did
        #: not present; a caller supplying one is a malformed adjudication
        #: table, rejected fail-closed (D4) rather than honoured.
        if disp is not None and disp not in PRESENTED_OUTCOMES:
            raise ValueError(
                f"entry {sid!r} carries an UNPRESENTED-category disposition "
                f"({disp}); dispositions must come from PRESENTED_OUTCOMES"
            )
        #: A disposition claiming duplication against an existing structured
        #: learning must be backed by a verbatim, non-empty quote - an
        #: unverifiable "trust me" duplicate claim is exactly the failure
        #: mode fail-closed atomicity exists to reject before it can corrupt
        #: a run.
        if disp in (
            Outcome.SKIPPED_DUPLICATE_OF_DESTINATION_OR_ALREADY_PRESENTED,
            Outcome.SKIPPED_ALREADY_A_STRUCTURED_LEARNING,
        ):
            quote = e.get("quote")
            if not quote or not isinstance(quote, str) or not quote.strip():
                raise ValueError(
                    f"entry {sid!r} claims a duplicate disposition "
                    f"({disp}) with no verifiable quote"
                )


# --------------------------------------------------------------------------
# Ordering
# --------------------------------------------------------------------------


def _order(combined: List[Dict[str, Any]], order_mode: str) -> List[Dict[str, Any]]:
    if order_mode == "arrival":
        return list(combined)  # already in arrival order by construction
    if order_mode == "date":
        return sorted(combined, key=lambda e: (e.get("date", ""), e["sid"]))
    raise ValueError("unknown ORDER_MODE: %r" % (order_mode,))


# --------------------------------------------------------------------------
# The drain
# --------------------------------------------------------------------------


def drain(
    staged: List[Dict[str, Any]],
    fresh: List[Dict[str, Any]],
    dispositions: Dict[str, Any],
    *,
    cap: int = CAP,
    reserve: int = RESERVE,
    order_mode: Optional[str] = None,
    reject_disposition: Optional[str] = None,
    reserve_rule: Optional[str] = None,
) -> DrainResult:
    """Drain `staged` (the carried-over backlog, oldest first) plus `fresh`
    (this run's new entries) against a per-run `cap`, reserving `reserve`
    slots for fresh entries. See module docstring for the full contract."""
    order_mode = ORDER_MODE if order_mode is None else order_mode
    reject_disposition = (
        REJECT_DISPOSITION if reject_disposition is None else reject_disposition
    )
    reserve_rule = RESERVE_RULE if reserve_rule is None else reserve_rule

    combined = list(staged) + list(fresh)
    _validate(combined, dispositions)  # D4: raise before computing anything

    ordered = _order(combined, order_mode)

    #: The plain FIFO-cap window, ignoring reserve - used only to label the
    #: two UNPRESENTED outcomes (DROPPED_BY_CAP vs NEVER_ADJUDICATED).
    plain_sids = {e["sid"] for e in ordered[:cap]}

    if reserve_rule == "none":
        chosen = ordered[:cap]
    else:
        #: `reserve` is a FLOOR guarantee for fresh entries, not a ceiling:
        #: staged gets first crack at (cap - reserve) slots; fresh then
        #: gets whatever remains (which can exceed `reserve` when staged's
        #: own backlog is smaller than cap - reserve); any slots still
        #: unused (fresh had fewer entries than the remainder) roll back to
        #: staged.
        staged_sids = {e["sid"] for e in staged}
        staged_ordered = [e for e in ordered if e["sid"] in staged_sids]
        fresh_ordered = [e for e in ordered if e["sid"] not in staged_sids]
        n_staged_base = max(cap - reserve, 0)
        chosen_staged = staged_ordered[:n_staged_base]
        remaining_after_staged = cap - len(chosen_staged)
        chosen_fresh = fresh_ordered[:remaining_after_staged]
        remaining_after_fresh = cap - len(chosen_staged) - len(chosen_fresh)
        if remaining_after_fresh > 0:
            already = {e["sid"] for e in chosen_staged}
            extra = [e for e in staged_ordered if e["sid"] not in already]
            chosen_staged = chosen_staged + extra[:remaining_after_fresh]
        chosen_sids = {e["sid"] for e in chosen_staged} | {
            e["sid"] for e in chosen_fresh
        }
        chosen = [e for e in ordered if e["sid"] in chosen_sids]

    presented_sids = {e["sid"] for e in chosen}

    outcomes: Dict[str, Outcome] = {}
    for e in ordered:
        sid = e["sid"]
        if sid in presented_sids:
            #: Validated above to be a PRESENTED-category outcome, so the
            #: DRAINED <=> PRESENTED correspondence holds by construction.
            outcomes[sid] = dispositions.get(sid, Outcome.REJECTED_ON_THE_MERITS)
        elif sid in plain_sids:
            # Would have fit under plain FIFO-cap ordering, but the reserve
            # carve-out gave its slot to a fresh entry instead.
            outcomes[sid] = Outcome.DROPPED_BY_CAP
        else:
            outcomes[sid] = Outcome.NEVER_ADJUDICATED

    return DrainResult(
        order=ordered,
        outcomes=outcomes,
        presented_sids=presented_sids,
        reject_disposition=reject_disposition,
    )
