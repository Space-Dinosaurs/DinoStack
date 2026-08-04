#!/usr/bin/env python3
"""
Purpose: Exhaustive property tests over `reach_model.py`'s route x entry-path
         x reachability contract (R1-R5), asserted over ALL 128 SessionState
         values rather than hand-traced cases. Four of seven prior review
         rounds on this plan found a reachability defect the previous
         round's hand-tracing missed - this is the mechanical replacement.

Public API: unittest TestCases. Run with
              python3 -m pytest bin/tests/test_reach_invariants.py -q
            (.github/workflows/bin-tests.yml runs `python3 -m pytest
            bin/tests/ -q`, auto-discovering; no CI wiring is required.)

Upstream deps: reach_model.py (the single normative definition of the
               routing contract); stdlib `unittest` only. No sampling, no
               seed - every property below is asserted over the FULL 128-
               state space, deterministically.

Downstream consumers: PR 2's edit to content/commands/ds-wrap.md, which this
                      suite is the acceptance test for.

Failure modes: DETERMINISTIC. No randomness anywhere in this file.

Performance: 128-state exhaustive sweeps, a handful of them per test;
             well under a second.
"""

from __future__ import annotations

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import reach_model as rm  # noqa: E402

ALL_STATES = list(rm.all_states())

#: Coverage counters, reported by test_zz_report_coverage. All three are
#: EQUALITIES, not floors - route_evaluations counts (state, route-
#: predicate) pairs evaluated by R3's own sweep. A value of 640 here would
#: be the known prior defect (200 states x an over-broad per-state loop, not
#: 128 x len(ROUTE_PREDICATES)) and must never appear.
COVERAGE = {"states": 0, "route_evaluations": 0, "entry_path_evaluations": 0}


class TestRouteEnumAndPredicateCounts(unittest.TestCase):
    def test_reach_route_enum_and_predicate_counts(self):
        self.assertEqual(len(rm.Route), 6)
        self.assertEqual(len(rm.ROUTE_PREDICATES), 4)
        self.assertNotIn(rm.Route.R_ABORT_WORKERS, rm.ROUTE_PREDICATES)
        self.assertNotIn(rm.Route.R_ZS_FAST, rm.ROUTE_PREDICATES)
        # These four facts make route_evaluations derivable rather than
        # pinned: len(ROUTE_PREDICATES) * len(all_states()) == 4 * 128 == 512.


class TestReachR1StagingAlwaysDrains(unittest.TestCase):
    def test_reach_r1_staging_always_drains(self):
        for s in ALL_STATES:
            if s.L and s.s:
                self.assertTrue(
                    rm.executes_part_b_step0(s),
                    f"R1: staging non-empty but Part B step 0 did not "
                    f"execute for {s}",
                )


class TestReachR2OverGateAlwaysCompresses(unittest.TestCase):
    def test_reach_r2_over_gate_always_compresses(self):
        for s in ALL_STATES:
            if s.L and s.e:
                self.assertTrue(
                    rm.executes_part_e(s),
                    f"R2: target over gate but Part E did not execute "
                    f"for {s}",
                )


class TestReachR3ExactlyOnePredicateHolds(unittest.TestCase):
    def test_reach_r3_exactly_one_predicate_holds(self):
        """Derivation, reproduced here so the 128 total is checked, not
        merely asserted: ~L = 64 states (half the space). L ^ (f v a v g) =
        56 (of the remaining 64, all but the 8 with f=a=g=False - standard
        counting: 64 - 8 = 56). L ^ ~f^~a^~g = 8, splitting 4/4 on v (zero-
        substance vs light). 64 + 56 + 4 + 4 = 128."""
        for s in ALL_STATES:
            COVERAGE["states"] += 1
            holders = []
            for r, p in rm.ROUTE_PREDICATES.items():
                COVERAGE["route_evaluations"] += 1
                if p(s):
                    holders.append(r)
            self.assertEqual(
                len(holders), 1,
                f"R3: {len(holders)} predicates hold for {s}: {holders}",
            )
        # Reconcile the derivation against the actual partition sizes.
        not_l = sum(1 for s in ALL_STATES if not s.L)
        std = sum(1 for s in ALL_STATES if s.L and (s.f or s.a or s.g))
        zs = sum(
            1 for s in ALL_STATES
            if s.L and not s.f and not s.a and not s.g and not s.v
        )
        light = sum(
            1 for s in ALL_STATES
            if s.L and not s.f and not s.a and not s.g and s.v
        )
        self.assertEqual(not_l, 64)
        self.assertEqual(std, 56)
        self.assertEqual(zs, 4)
        self.assertEqual(light, 4)
        self.assertEqual(not_l + std + zs + light, 128)

    def test_reach_r3_raises_when_partition_broken(self):
        with self.assertRaises(rm.RouteResolutionError):
            rm.route(
                rm.SessionState(L=True, f=False, a=True, g=False, v=True,
                                 s=False, e=False),
                R3_PREDICATE_OVERLAP=True,
            )
        with self.assertRaises(rm.RouteResolutionError):
            rm.route(
                rm.SessionState(L=True, f=False, a=True, g=False, v=False,
                                 s=False, e=False),
                R3_PREDICATE_GAP=True,
            )


class TestReachZsFastIsNotARoutingDestination(unittest.TestCase):
    def test_reach_zs_fast_is_not_a_routing_destination(self):
        saw_admissible = False
        for s in ALL_STATES:
            COVERAGE["entry_path_evaluations"] += 1
            if s.L:
                r = rm.route(s)
                self.assertNotEqual(r, rm.Route.R_ZS_FAST)
            if rm.zs_fast_admissible(s):
                saw_admissible = True
        self.assertTrue(
            saw_admissible,
            "zs_fast_admissible was never True over the full state space",
        )


class TestReachR4PrelockAbortRoutesAreSafe(unittest.TestCase):
    def test_reach_r4_prelock_abort_routes_are_safe(self):
        """R4 makes NO claim about the four lock-held mid-run escalations
        (ds-wrap.md:433, :435, :441, :649) - only about the pre-lock abort
        route (`not state.L`), where neither mechanism can have run yet."""
        for s in ALL_STATES:
            if not s.L:
                self.assertFalse(rm.executes_part_b_step0(s))
                self.assertFalse(rm.executes_part_e(s))


class TestReachR5FixSetMinimalAndSufficient(unittest.TestCase):
    def test_reach_r5_fix_set_minimal_and_sufficient(self):
        # Sufficiency: all five defaults -> R1 and R2 both hold everywhere.
        for s in ALL_STATES:
            if s.L and s.s:
                self.assertTrue(rm.executes_part_b_step0(s))
            if s.L and s.e:
                self.assertTrue(rm.executes_part_e(s))

        # Minimality: each of the five fix-site switches flipped
        # individually reddens R1 or R2 somewhere in the state space.
        non_default = {
            "ZS_FAST_CRITERIA": "session-only",
            "ZS_CRITERIA": "session-only",
            "LIGHT_TRIGGER": "fresh-only",
            "PART_B_GUARD": "fresh-only",
            "PART_E_GUARDS": "inflow-only",
        }
        anchors = {
            "ZS_FAST_CRITERIA": "ds-wrap.md:166-172 (Step 0-pre fast short-circuit)",
            "ZS_CRITERIA": "ds-wrap.md:248-264 (Step 0.5 Zero-substance path)",
            "LIGHT_TRIGGER": "ds-wrap.md:265-281 (Step 0.5 Light path)",
            "PART_B_GUARD": "ds-wrap.md:471 (Part B - Write memory.md gate)",
            "PART_E_GUARDS": "ds-wrap.md:591 (Part E gate)",
        }
        for name, value in non_default.items():
            r1_red = any(
                s.L and s.s and not rm.executes_part_b_step0(s, **{name: value})
                for s in ALL_STATES
            )
            r2_red = any(
                s.L and s.e and not rm.executes_part_e(s, **{name: value})
                for s in ALL_STATES
            )
            self.assertTrue(
                r1_red or r2_red,
                f"minimality: flipping {name} alone did not redden R1 or "
                f"R2 (fix site: {anchors[name]})",
            )

        # ZS_FAST_CRITERIA and ZS_CRITERIA must redden INDEPENDENTLY on the
        # canonical witness state, via two distinct code paths (the entry-
        # path short-circuit vs the route-based R_ZS disqualifier).
        witness = rm.SessionState(
            L=True, f=False, a=False, g=False, v=False, s=True, e=True
        )
        self.assertEqual(rm.route(witness), rm.Route.R_ZS)
        self.assertFalse(
            rm.executes_part_b_step0(witness, ZS_FAST_CRITERIA="session-only")
        )
        self.assertFalse(
            rm.executes_part_b_step0(witness, ZS_CRITERIA="session-only")
        )
        self.assertFalse(
            rm.executes_part_e(witness, ZS_FAST_CRITERIA="session-only")
        )
        self.assertFalse(
            rm.executes_part_e(witness, ZS_CRITERIA="session-only")
        )


class TestReachAsShippedIsRed(unittest.TestCase):
    def test_reach_as_shipped_is_red(self):
        r1_failing_routes = set()
        r2_failing_routes = set()
        for s in ALL_STATES:
            if s.L and s.s:
                if not rm.executes_part_b_step0(s, AS_SHIPPED_PRE_DS90=True):
                    r1_failing_routes.add(rm.route(s))
            if s.L and s.e:
                if not rm.executes_part_e(s, AS_SHIPPED_PRE_DS90=True):
                    r2_failing_routes.add(rm.route(s))
        self.assertTrue(r1_failing_routes, "AS_SHIPPED_PRE_DS90: R1 never went RED")
        self.assertTrue(r2_failing_routes, "AS_SHIPPED_PRE_DS90: R2 never went RED")
        combined = r1_failing_routes | r2_failing_routes
        self.assertGreaterEqual(
            len(combined), 3,
            f"AS_SHIPPED_PRE_DS90 failing states must span >=3 distinct "
            f"routes; saw {combined}",
        )


class TestMutationR3OverlapIsRed(unittest.TestCase):
    def test_mutation_r3_overlap_is_red(self):
        s = rm.SessionState(L=True, f=False, a=True, g=False, v=True,
                             s=False, e=False)
        with self.assertRaises(rm.RouteResolutionError) as ctx:
            rm.route(s, R3_PREDICATE_OVERLAP=True)
        self.assertIn("R_LIGHT", str(ctx.exception))
        self.assertIn("R_STD", str(ctx.exception))


class TestMutationR3GapIsRed(unittest.TestCase):
    def test_mutation_r3_gap_is_red(self):
        s = rm.SessionState(L=True, f=False, a=True, g=False, v=False,
                             s=False, e=False)
        with self.assertRaises(rm.RouteResolutionError) as ctx:
            rm.route(s, R3_PREDICATE_GAP=True)
        self.assertIn("0 predicates hold", str(ctx.exception))


class TestMutationAbortSemanticsIsRed(unittest.TestCase):
    def test_mutation_abort_semantics_is_red(self):
        found = False
        for s in ALL_STATES:
            if not s.L and (s.s or s.e):
                default_b = rm.executes_part_b_step0(s)
                mutated_b = rm.executes_part_b_step0(
                    s, ABORT_SEMANTICS="pre-lock-executes"
                )
                if default_b != mutated_b:
                    found = True
        self.assertTrue(
            found, "ABORT_SEMANTICS mutation never changed R4's outcome"
        )


class TestZReport(unittest.TestCase):
    def test_zz_report_coverage(self):
        print(
            "\nreach coverage: states=%(states)d "
            "route_evaluations=%(route_evaluations)d "
            "entry_path_evaluations=%(entry_path_evaluations)d"
            % COVERAGE
        )
        self.assertEqual(COVERAGE["states"], 128)
        self.assertEqual(COVERAGE["route_evaluations"], 512)
        self.assertEqual(COVERAGE["entry_path_evaluations"], 128)


if __name__ == "__main__":
    unittest.main(verbosity=2)
