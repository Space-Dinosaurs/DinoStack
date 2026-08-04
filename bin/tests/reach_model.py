#!/usr/bin/env python3
"""
Purpose: (a) Executable reference implementation of `/ds-wrap`'s route x
         entry-path x reachability contract - the SINGLE NORMATIVE DEFINITION
         of which route a `SessionState` resolves to, and whether Part B's
         staging-drain step and Part E's compression step are REACHED from
         that route. (b) `content/commands/ds-wrap.md` does NOT yet conform
         to this model: the defaults below encode the DS-90 TARGET routing
         (staging always drains, an over-gate target always compresses,
         regardless of which route a session takes); `AS_SHIPPED_PRE_DS90`
         reproduces TODAY's routing, under which R1 and R2 are RED - i.e. a
         merged executable record that today's ds-wrap.md has two dead paths
         (a session that is otherwise zero-substance or light-path can still
         silently strand staged learnings or an over-gate compression
         target). PR 2 edits ds-wrap.md to make it conform; this file is the
         spec PR 2 implements against, not a description of current behavior.
         (c) Two-layer structure: `ROUTE_PREDICATES` is a 4-entry PARTITION
         over `SessionState` (every state resolves to exactly one route via
         `route()`); `zs_fast_admissible` is a SEPARATE entry-path predicate
         - Step 0-pre's fast zero-substance short-circuit - that is NOT a
         member of `ROUTE_PREDICATES` and is NOT consulted by `route()`. It
         is consulted only by `executes_part_b_step0` / `executes_part_e`,
         which check it BEFORE ever calling `route()`.

         MANDATED BOUNDARY STATEMENT: This model covers only the routing
         decision derivable from a `SessionState`, plus the two-entry
         structure of the zero-substance procedure. It deliberately does NOT
         model the four lock-held mid-run escalations at ds-wrap.md:433,
         :435, :441, and :649 (Skeptic re-route/format-reinvocation limits
         that escalate to the user), nor :94's open-ended user-abort class
         ("any user-abort path (e.g. drift requiring input, Skeptic scope
         bail)"), nor the background-Worker abort at :63 ("Pre-flight check
         - no active Workers"). :651 is NOT an abort: it skips compression
         for one target ("skip compression for that target this session")
         and the run continues to normal completion at :91 ("successful
         completion at Step 6"). Do not add :651 to the excluded-abort list.
         Only :433 and :435 are excluded by R1/R2's "reaches Step 4"
         qualifier (Skeptic escalations occur INSIDE the draft-worker loop
         that itself is downstream of routing). :441 and :649 are lock-held
         escalations occurring AFTER the modelled mechanisms (Part B step 0,
         Part E) have already run, so R1 and R2 hold on those runs. A reader
         must not conclude from a green R1/R2 that Part B step 0 executed on
         a run that aborted at Step 3 (the pre-Part-B-and-E format/sign-off
         validation, ds-wrap.md:431-435).

Public API:
  SessionState(L, f, a, g, v, s, e) -> frozen dataclass, the seven booleans
                                        a routing decision is derived from
  all_states()                       -> list of all 128 SessionState values,
                                         in deterministic dataclass-field
                                         order (a list, not a generator - may
                                         be iterated more than once)
  Route                              -> enum, exactly 6 members
  ROUTE_PREDICATES                   -> the 4-entry route partition (dict);
                                         R_ABORT_WORKERS and R_ZS_FAST are
                                         DELIBERATELY ABSENT - see their
                                         Route docstrings
  route(state, **switches)           -> Route, or raises RouteResolutionError
                                         if != 1 predicate holds
  zs_fast_admissible(state, **switches) -> bool, the :166-172 entry path.
                                         NOT in ROUTE_PREDICATES, NOT called
                                         by route().
  executes_part_b_step0(state, **switches) -> bool
  executes_part_e(state, **switches)       -> bool
  RouteResolutionError               -> raised by route() when the 4-entry
                                         partition does not resolve to
                                         exactly one holder (R3 defect class)
  Mutation switches (test-only), NINE: ZS_FAST_CRITERIA, ZS_CRITERIA,
  LIGHT_TRIGGER, PART_B_GUARD, PART_E_GUARDS, AS_SHIPPED_PRE_DS90,
  R3_PREDICATE_OVERLAP, R3_PREDICATE_GAP, ABORT_SEMANTICS.

Upstream deps: none (stdlib only: dataclasses, enum, itertools, typing).

Downstream consumers: test_reach_invariants.py (R1-R5 property tests over
                      the full 128-state space); PR 2's edit to
                      content/commands/ds-wrap.md, which must implement the
                      staging-aware / gate-aware defaults this file encodes.

Failure modes: `route()` raises `RouteResolutionError` when the active
               `ROUTE_PREDICATES` (as mutated by R3_PREDICATE_OVERLAP /
               R3_PREDICATE_GAP) do not partition - zero or 2+ holders for a
               given state. `executes_part_b_step0` / `executes_part_e` never
               raise; every mutation switch degrades them to `False` on some
               states rather than raising. Pure - no I/O, no filesystem, no
               network, no wall-clock, no input mutation. `SessionState` is
               frozen (hashable, immutable).

Performance: O(1) per call; `all_states()` is O(128).
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass, fields
from enum import Enum, auto
from typing import Dict, List, Tuple


# --------------------------------------------------------------------------
# Session state
# --------------------------------------------------------------------------


@dataclass(frozen=True)
class SessionState:
    """The seven booleans a `/ds-wrap` routing decision is derivable from.

    L: lock acquired (ds-wrap.md:65-96, "Pre-flight lock acquisition").
    f: fresh memory entries drafted this session (Output 2 non-"None").
    a: AGENTS.md updates drafted this session (Output 3 non-"None").
    g: a specialist agent (perf-analyst / release-orchestrator /
       dependency-auditor) ran with session-scoped issues to capture.
    v: file activity worth preserving in _wrap.md (uncommitted tracked
       changes, new stashes, files touched beyond reads, meaningful next
       steps) - the Step 0.5 "no file activity worth preserving" clause,
       negated.
    s: staging (the DS-90 staged-learnings/memory area) is non-empty.
    e: at least one Part E compression target is over its size gate
       (ds-wrap.md:614-618, the existing per-target Gate).
    """

    L: bool
    f: bool
    a: bool
    g: bool
    v: bool
    s: bool
    e: bool


def all_states() -> List[SessionState]:
    """All 128 (2^7) SessionState values, in deterministic order: itertools
    .product over the dataclass's own field order (L, f, a, g, v, s, e), each
    axis False-before-True. Exhaustive - no sampling, no seed. Returns a
    list (not a generator) - callers may iterate it more than once."""
    field_names = [fld.name for fld in fields(SessionState)]
    return [
        SessionState(**dict(zip(field_names, combo)))
        for combo in itertools.product((False, True), repeat=len(field_names))
    ]


# --------------------------------------------------------------------------
# Route enum and the 4-entry partition
# --------------------------------------------------------------------------


class Route(Enum):
    """Exactly SIX members. Only four are routing-partition destinations
    (see ROUTE_PREDICATES); R_ABORT_WORKERS and R_ZS_FAST are named here for
    completeness but are deliberately excluded from the partition."""

    #: ds-wrap.md:63, "Pre-flight check - no active Workers". Its trigger is
    #: a PROCESS-TABLE LIVENESS PROBE ("check whether any background Workers
    #: or subagents are currently running"), not a SessionState field - there
    #: is no boolean here that can stand in for "is a background Worker
    #: alive right now". Deliberately absent from ROUTE_PREDICATES; adding a
    #: fabricated field for it would model a fact this SessionState cannot
    #: observe.
    R_ABORT_WORKERS = auto()

    #: ds-wrap.md:65-96, "Pre-flight lock acquisition" (the busy/timeout/
    #: fatal exit-code branches at :68-79). Corresponds to `not state.L`.
    R_ABORT_LOCK = auto()

    #: The Step 0-pre fast zero-substance short-circuit's DESTINATION, not
    #: the entry-path predicate itself (that is `zs_fast_admissible`).
    #: Deliberately absent from ROUTE_PREDICATES - see `zs_fast_admissible`'s
    #: docstring for why it is an entry path, not a route.
    R_ZS_FAST = auto()

    #: ds-wrap.md:248-264, the Step 0.5 "Zero-substance path".
    R_ZS = auto()

    #: ds-wrap.md:265-281, the Step 0.5 "Light path".
    R_LIGHT = auto()

    #: ds-wrap.md:285, the Step 0.5 "Standard path".
    R_STD = auto()


class RouteResolutionError(Exception):
    """Raised by route() when the active ROUTE_PREDICATES do not partition
    SessionState - i.e. zero or 2+ predicates hold for a given state. See
    R3_PREDICATE_OVERLAP / R3_PREDICATE_GAP for the two ways this is forced."""


#: The 4-entry route partition. EXACTLY these four keys - R_ABORT_WORKERS and
#: R_ZS_FAST are DELIBERATELY ABSENT (see their Route docstrings above).
#: Adding either one reproduces a defect that took two review rounds to
#: find: R_ABORT_WORKERS because its trigger (:63) is a process-table
#: liveness probe with no SessionState field to key off; R_ZS_FAST because
#: :173 ("On ANY uncertainty, fall through to the full Step 0") is conductor
#: judgement over context this model cannot observe, AND :175 ("go straight
#: to the Zero-substance procedure under Step 0.5") sends a successful
#: short-circuit into R_ZS's OWN procedure rather than a distinct
#: destination - so it is an ENTRY PATH into R_ZS, never a route in its own
#: right.
#:
#: CRITICAL: `s` and `e` must NEVER appear in any of these four lambdas.
#: They are the invariant SUBJECTS (what R1/R2 assert about), not routing
#: inputs - the four predicates below read only L, f, a, g, v. Folding `s`/
#: `e` into a lambda here (e.g. "and not s.s" on P_ZS) breaks the partition:
#: on state (L, ~f, ~a, ~g, ~v, s=True, e=True) zero predicates would hold,
#: route() would raise, and R3 would go RED at DEFAULTS - the exact defect a
#: prior review round caught. The five fix-site switches
#: (ZS_FAST_CRITERIA / ZS_CRITERIA / LIGHT_TRIGGER / PART_B_GUARD /
#: PART_E_GUARDS) model whether `s`/`e` disqualify Part B step 0 / Part E
#: EXECUTION, strictly downstream of routing - never inside the partition.
ROUTE_PREDICATES: Dict[Route, "callable"] = {
    Route.R_ABORT_LOCK: lambda s: not s.L,
    Route.R_ZS:         lambda s: s.L and not s.f and not s.a and not s.g and not s.v,
    Route.R_LIGHT:      lambda s: s.L and not s.f and not s.a and not s.g and     s.v,
    Route.R_STD:        lambda s: s.L and (s.f or s.a or s.g),
}


# --------------------------------------------------------------------------
# Mutation switches - DEFAULTS ARE THE NORMATIVE (DS-90 TARGET) BEHAVIOUR.
#
# These exist so test_reach_invariants.py can reintroduce a specific fix-site
# defect and demonstrate that R1 or R2 goes RED. PR 2 (the ds-wrap.md edit)
# must never leave any of these five sites at its non-default value.
# --------------------------------------------------------------------------

#: Applied inside `zs_fast_admissible`. "staging-and-gate-aware" (default):
#: the :166-172 fast short-circuit also requires staging empty (~s) and no
#: over-gate target (~e) before it is admissible - i.e. it never bypasses a
#: pending drain or compression. "session-only": ignores s/e entirely
#: (today's :166-172 criteria, which have no staging/gate concept at all).
ZS_FAST_CRITERIA = "staging-and-gate-aware"

#: Applied inside the R_ZS route's downstream disqualifier logic (NOT by
#: adding s/e terms to the P_ZS lambda in ROUTE_PREDICATES - see the CRITICAL
#: note above). "staging-and-gate-aware" (default): on route R_ZS, Part B
#: step 0 / Part E still execute when s / e hold respectively.
#: "session-only": on route R_ZS, Part B step 0 / Part E never execute
#: regardless of s/e - reproduces the defect a review round (round 6)
#: caught, where routing to the zero-substance procedure silently dropped a
#: pending drain or compression.
ZS_CRITERIA = "staging-and-gate-aware"

#: Applied inside the R_LIGHT route's downstream disqualifier logic, the
#: R_LIGHT analogue of ZS_CRITERIA. "staging-aware" (default): on route
#: R_LIGHT, Part B step 0 / Part E still execute when s / e hold.
#: "fresh-only": on route R_LIGHT they never execute - reproduces a review
#: round (round 5) finding that the light path's "Skip Part B ... Skip
#: Part E entirely" (ds-wrap.md:274, :276) silently discarded staging.
LIGHT_TRIGGER = "staging-aware"

#: The dominant top-level Part-B gate. "staging-aware" (default): governed
#: by route + ZS_CRITERIA/LIGHT_TRIGGER (see _executes_b_on_route).
#: "fresh-only" (non-default): reproduces TODAY's actual Part B gate exactly
#: - "Skip Part B entirely if the memory entries input above is 'None'"
#: (ds-wrap.md:471) checks ONLY whether fresh memory-entry content (f) was
#: drafted; it has no concept of `route` or `s` at all, because DS-90's
#: drain step does not exist yet in the shipped doc (round 3 finding).
PART_B_GUARD = "staging-aware"

#: The dominant top-level Part-E gate, the PART_B_GUARD analogue for
#: compression. "gate-aware" (default): governed by route + ZS_CRITERIA/
#: LIGHT_TRIGGER, honoring `e`. "inflow-only" (non-default): reproduces
#: TODAY's actual Part E gate exactly - "Skip Part E entirely if Parts B and
#: C both reported no changes" (ds-wrap.md:591) checks only whether upstream
#: Parts produced content (f or a); it ignores a target's own size-gate
#: state (e) entirely, so a target that crossed its gate from PRIOR session
#: drift, with no f/a change this session, is silently never compressed
#: (round 3 finding, the same review round as PART_B_GUARD).
PART_E_GUARDS = "gate-aware"

#: Convenience switch: True flips all five fix-site switches above to their
#: non-default value simultaneously, reproducing today's shipped ds-wrap.md
#: routing in full (no staging/gate-awareness anywhere).
AS_SHIPPED_PRE_DS90 = False

#: R3 mutation. False (default): ROUTE_PREDICATES as declared. True: drops
#: `not s.a` from the R_LIGHT predicate, so on state L∧~f∧a∧~g∧v BOTH
#: P_LIGHT and P_STD hold -> route() sees 2 holders and raises.
R3_PREDICATE_OVERLAP = False

#: R3 mutation. False (default): ROUTE_PREDICATES as declared. True: narrows
#: the R_STD predicate to `L and (s.f or s.g)` (drops the `s.a` disjunct), so
#: on state L∧~f∧a∧~g∧~v ZERO predicates hold -> route() sees 0 holders and
#: raises.
R3_PREDICATE_GAP = False

#: R4 mutation. "pre-lock-inert" (default): a pre-lock abort (route
#: R_ABORT_LOCK, `not state.L`) never executes Part B step 0 or Part E -
#: neither mechanism can run before the lock that guards their shared
#: writes is held. "pre-lock-executes" (non-default): forces both to execute
#: anyway on R_ABORT_LOCK, reproducing an unsafe pre-lock write.
ABORT_SEMANTICS = "pre-lock-inert"

#: The five fix-site switch names AS_SHIPPED_PRE_DS90 flips together.
_AS_SHIPPED_FLIPS: Tuple[str, ...] = (
    "ZS_FAST_CRITERIA",
    "ZS_CRITERIA",
    "LIGHT_TRIGGER",
    "PART_B_GUARD",
    "PART_E_GUARDS",
)

_NON_DEFAULT = {
    "ZS_FAST_CRITERIA": "session-only",
    "ZS_CRITERIA": "session-only",
    "LIGHT_TRIGGER": "fresh-only",
    "PART_B_GUARD": "fresh-only",
    "PART_E_GUARDS": "inflow-only",
}


def _resolve_switches(switches: dict) -> dict:
    """Merge caller-supplied switches with AS_SHIPPED_PRE_DS90's bulk flip.
    Caller-supplied values for an individual fix-site switch still win over
    the bulk flip (explicit beats bulk), matching ordinary kwarg precedence."""
    resolved = dict(switches)
    if resolved.get("AS_SHIPPED_PRE_DS90", AS_SHIPPED_PRE_DS90):
        for name in _AS_SHIPPED_FLIPS:
            resolved.setdefault(name, _NON_DEFAULT[name])
    return resolved


# --------------------------------------------------------------------------
# route() and the entry path
# --------------------------------------------------------------------------


def _route_predicates(**switches) -> Dict[Route, "callable"]:
    overlap = switches.get("R3_PREDICATE_OVERLAP", R3_PREDICATE_OVERLAP)
    gap = switches.get("R3_PREDICATE_GAP", R3_PREDICATE_GAP)
    preds = dict(ROUTE_PREDICATES)
    if overlap:
        preds[Route.R_LIGHT] = (
            lambda s: s.L and not s.f and not s.g and s.v
        )  # R3 mutation: drops `not s.a`
    if gap:
        preds[Route.R_STD] = (
            lambda s: s.L and (s.f or s.g)
        )  # R3 mutation: drops the `s.a` disjunct
    return preds


def route(state: SessionState, **switches) -> Route:
    """Resolve `state` to exactly one Route by counting holders over the
    active (possibly R3-mutated) 4-entry partition. Raises
    RouteResolutionError if != 1 predicate holds."""
    switches = _resolve_switches(switches)
    preds = _route_predicates(**switches)
    holders = [r for r, p in preds.items() if p(state)]
    if len(holders) != 1:
        raise RouteResolutionError(
            f"{len(holders)} predicates hold for {state}: {holders}"
        )
    return holders[0]


def zs_fast_admissible(state: SessionState, **switches) -> bool:
    """The Step 0-pre :166-172 entry path (":173 on ANY uncertainty, fall
    through"; on success, ":175 go straight to the Zero-substance procedure
    under Step 0.5" - R_ZS's own procedure, not a distinct destination).
    NOT a member of ROUTE_PREDICATES. NOT called by route()."""
    switches = _resolve_switches(switches)
    criteria = switches.get("ZS_FAST_CRITERIA", ZS_FAST_CRITERIA)
    base = not state.f and not state.a and not state.g and not state.v
    if criteria == "session-only":
        return base
    # staging-and-gate-aware (default)
    return base and not state.s and not state.e


# --------------------------------------------------------------------------
# Downstream reachability: Part B step 0 (staging drain) and Part E
# (compression)
# --------------------------------------------------------------------------


def _executes_b_on_route(route_: Route, state: SessionState, **switches) -> bool:
    """Part B step 0's downstream disqualifier, consulted only after the
    zs_fast_admissible entry-path check has already passed. See PART_B_GUARD
    / ZS_CRITERIA / LIGHT_TRIGGER for what each branch reproduces."""
    part_b_guard = switches.get("PART_B_GUARD", PART_B_GUARD)
    if part_b_guard == "fresh-only":
        return state.f
    if route_ == Route.R_STD:
        return True
    if route_ == Route.R_ZS:
        zs_criteria = switches.get("ZS_CRITERIA", ZS_CRITERIA)
        if zs_criteria == "session-only":
            return False
        return state.s
    if route_ == Route.R_LIGHT:
        light_trigger = switches.get("LIGHT_TRIGGER", LIGHT_TRIGGER)
        if light_trigger == "fresh-only":
            return False
        return state.s
    return False


def _executes_e_on_route(route_: Route, state: SessionState, **switches) -> bool:
    """Part E's downstream disqualifier - the _executes_b_on_route analogue,
    keyed on `e` (over-gate) instead of `s` (staging)."""
    part_e_guards = switches.get("PART_E_GUARDS", PART_E_GUARDS)
    if part_e_guards == "inflow-only":
        return state.f or state.a
    if route_ == Route.R_STD:
        return True
    if route_ == Route.R_ZS:
        zs_criteria = switches.get("ZS_CRITERIA", ZS_CRITERIA)
        if zs_criteria == "session-only":
            return False
        return state.e
    if route_ == Route.R_LIGHT:
        light_trigger = switches.get("LIGHT_TRIGGER", LIGHT_TRIGGER)
        if light_trigger == "fresh-only":
            return False
        return state.e
    return False


def executes_part_b_step0(state: SessionState, **switches) -> bool:
    """Conservative over BOTH entry paths (fast short-circuit and normal
    Step 0.5 routing). R4 (ABORT_SEMANTICS): a pre-lock abort never executes
    this, by construction - `not state.L` returns False before either entry
    path is even consulted, under both ABORT_SEMANTICS values except the
    explicit non-default override below."""
    switches = _resolve_switches(switches)
    if not state.L:
        abort_semantics = switches.get("ABORT_SEMANTICS", ABORT_SEMANTICS)
        return abort_semantics == "pre-lock-executes"
    if zs_fast_admissible(state, **switches):
        return False   # :175 -> :257 skips Part B
    return _executes_b_on_route(route(state, **switches), state, **switches)


def executes_part_e(state: SessionState, **switches) -> bool:
    """Mirrors executes_part_b_step0, keyed on Part E / `e` instead of Part
    B step 0 / `s`."""
    switches = _resolve_switches(switches)
    if not state.L:
        abort_semantics = switches.get("ABORT_SEMANTICS", ABORT_SEMANTICS)
        return abort_semantics == "pre-lock-executes"
    if zs_fast_admissible(state, **switches):
        return False
    return _executes_e_on_route(route(state, **switches), state, **switches)
