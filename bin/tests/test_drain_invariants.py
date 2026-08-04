#!/usr/bin/env python3
"""
Purpose: Property tests for `drain_model.py`'s staging-drain invariants
         D1-D5, asserted over an exhaustive tier-1 sweep (every size
         <= CAP + 2 entries, every one of the 7 PRESENTABLE Outcome values
         per entry - the two UNPRESENTED labels are drain()'s own and
         rejected fail-closed as input) plus a seeded-random tier-2 sweep
         (sizes up to 8, multi-run simulation).

Public API: unittest TestCases. Run with
              python3 -m pytest bin/tests/test_drain_invariants.py -q
            (.github/workflows/bin-tests.yml runs `python3 -m pytest
            bin/tests/ -q`, auto-discovering; no CI wiring is required.)

Upstream deps: drain_model.py (the single normative definition of the drain
               algorithm); stdlib `unittest` + `random` + `itertools` only.
               NO hypothesis - it is not a dependency of this repo and
               adding one is out of scope.

Downstream consumers: PR 2's edit to content/commands/ds-wrap.md, which this
                      suite is the acceptance test for.

Failure modes: DETERMINISTIC. Tier 2 is seeded from SEED below; no unseeded
               RNG, no wall-clock, no filesystem, no network.

Performance: 114381 tier-1 assignments + 14200 tier-2 schedules; a few
             seconds.
"""

from __future__ import annotations

import itertools
import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import drain_model as dmod  # noqa: E402

SEED = 20260803

COVERAGE = {
    "tier1_size_pairs": 0,
    "tier1_assignments": 0,
    "tier2_size_pairs": 0,
    "tier2_schedules": 0,
    "rejected_outcomes_exercised": 0,
    "zero_fresh_schedules": 0,
    "cap_deferred_reentries": 0,
    "single_entry_mode_entered": 0,
    "d1_correspondence_checks": 0,
    "tier2_d1_results_checked": 0,
}

#: The presentable outcomes a random adjudicator draws from (never one of
#: the two UNPRESENTED categories - a real adjudicator never self-assigns
#: "dropped by cap"). Defined here (not in the tier-2 section below) because
#: tier 1 now needs it too - drain() rejects an UNPRESENTED-category
#: disposition fail-closed, so tier 1's own sweep must draw from this set.
_PRESENTABLE = sorted(dmod.PRESENTED_OUTCOMES, key=lambda o: o.name)


def _mk_entries(prefix, n, start=0):
    return [
        {"sid": f"{prefix}{i}", "quote": f"quote-{prefix}{i}"}
        for i in range(start, start + n)
    ]


def _all_dispositions(sids, values):
    """itertools.product over `values` (a caller-supplied set of Outcome
    values - not a fixed universe), one choice per sid, in sid order - the
    literal tier-1 enumeration. Tier 1 calls this with the 7 PRESENTABLE
    outcomes: the 2 UNPRESENTED labels are drain()'s own output for entries
    it did not present, not adjudicator inputs, so they have no place in
    this enumeration. See TestD1TierOne's docstring for the closed-form
    derivation of the resulting assignment count."""
    for combo in itertools.product(values, repeat=len(sids)):
        yield dict(zip(sids, combo))


def _check_d1(tc, result):
    """D1: presented + retained partition `order` exactly - total and
    disjoint, no entry counted twice, no entry dropped from the split."""
    pres = dmod.presented(result)
    ret = dmod.retained(result)
    pres_sids = {e["sid"] for e in pres}
    ret_sids = {e["sid"] for e in ret}
    order_sids = {e["sid"] for e in result.order}
    tc.assertEqual(pres_sids & ret_sids, set(), "D1: presented/retained overlap")
    # Total: every order entry is presented XOR retained, UNLESS the
    # REJECT_DISPOSITION="retained" mutation double-counts a rejected entry
    # into `retained()` alongside `presented()` (by design - see
    # drain_model.retained's docstring). Under the default, union == order
    # and it is a strict partition.
    tc.assertEqual(pres_sids | ret_sids, order_sids, "D1: union != order")
    if result.reject_disposition != "retained":
        tc.assertEqual(len(pres_sids) + len(ret_sids), len(order_sids),
                        "D1: not disjoint under default reject_disposition")
    # D1 SEMANTIC HALF - the partition AXIS, not just the split. The two
    # assertions above derive both operands from `presented_sids` and are
    # true by construction; this one is the falsifiable half.
    for sid in order_sids:
        tc.assertEqual(
            result.outcomes[sid] in dmod.PRESENTED_OUTCOMES,
            sid in result.presented_sids,
            f"D1: {sid} outcome {result.outcomes[sid]} disagrees with "
            f"presented-ness ({sid in result.presented_sids})",
        )
        COVERAGE["d1_correspondence_checks"] += 1


class TestD1TierOne(unittest.TestCase):
    """Tier 1: exhaustive over every (n_staged, n_fresh) pair summing to
    <= CAP + 2, and every assignment of the 7 PRESENTABLE outcomes.

    Base is 7, not 9: outcomes 8-9 are drain()'s OWN labels for entries it
    did not present. No adjudicator can emit them, so drain() now rejects
    them fail-closed and they have no place in the input enumeration.

    The size domain is CAP + 2, not CAP: with CAP = 3, no entry is ever
    retained at n <= 3, so the RETAINED half of the partition is never
    constructed and the correspondence assertion CANNOT FAIL there
    (measured: 0 violations at n <= 3 under the break-7 mutant, 36015 at
    n <= CAP + 2). n = CAP + 1 is the first size where the cap binds;
    n = CAP + 2 is the first size where both UNPRESENTED labels co-occur
    in a single result.

        tier1_size_pairs  = sum_{n=0}^{CAP+2} (n+1)
                          = 1+2+3+4+5+6 = 21
        tier1_assignments = sum_{n=0}^{CAP+2} (n+1) * 7^n
                          = 1*1 + 2*7 + 3*49 + 4*343 + 5*2401 + 6*16807
                          = 1 + 14 + 147 + 1372 + 12005 + 100842
                          = 114381
    """

    def test_d1_partition_total_and_disjoint(self):
        values = _PRESENTABLE
        self.assertEqual(len(values), 7)
        for total in range(dmod.CAP + 3):   # n <= CAP + 2; NOT a literal 5
            for n_staged in range(total + 1):
                n_fresh = total - n_staged
                COVERAGE["tier1_size_pairs"] += 1
                staged = _mk_entries("s", n_staged)
                fresh = _mk_entries("f", n_fresh)
                sids = [e["sid"] for e in staged + fresh]
                for disp in _all_dispositions(sids, values):
                    COVERAGE["tier1_assignments"] += 1
                    result = dmod.drain(staged, fresh, disp)
                    _check_d1(self, result)
        self.assertEqual(COVERAGE["tier1_size_pairs"], 21)
        self.assertEqual(COVERAGE["tier1_assignments"], 114381)

    def test_d1_outcome_enum_is_exhaustively_bucketed(self):
        self.assertEqual(
            dmod.PRESENTED_OUTCOMES | dmod.UNPRESENTED_OUTCOMES,
            set(dmod.Outcome),
        )
        self.assertEqual(
            dmod.PRESENTED_OUTCOMES & dmod.UNPRESENTED_OUTCOMES, set()
        )
        self.assertEqual(len(dmod.PRESENTED_OUTCOMES), 7)
        self.assertEqual(len(dmod.UNPRESENTED_OUTCOMES), 2)


# ==========================================================================
# Tier 2 - seeded random, multi-run simulation
# ==========================================================================

#: TestCase instance used to run D1's correspondence assertion against every
#: tier-2 result (see _run_schedule below) - tier 2 must not be a D1 blind
#: spot just because it iterates DrainResult objects rather than unittest
#: test methods.
_TC = unittest.TestCase()


def _run_schedule(rng, n_staged, n_fresh, n_runs=6, fresh_every_run=True,
                   **switches):
    """Simulate `n_runs` successive drain() calls: whatever `retained()`
    returns from run k becomes the incoming `staged` backlog for run k+1.
    When `fresh_every_run` is True (D3/D5's steady-state scenario: inflow
    rate <= throughput, sustainable indefinitely) `n_fresh` entries are
    freshly minted every run. When False (D2's scenario: a one-off arrival,
    matching D3/D5's own single-run fresh guarantee - continuous unbounded
    injection at a rate exceeding CAP has no finite residency bound in ANY
    cap-limited system and is not what D2 asserts), `n_fresh` entries are
    minted only at run 0; later runs drain the residual backlog with no new
    arrivals. Returns the list of per-run DrainResult objects plus the
    sid->first-presented-run map."""
    staged = _mk_entries("s", n_staged)
    results = []
    presented_at_run = {}
    next_fresh_id = 0
    for run_idx in range(n_runs):
        if run_idx > 0 and staged:
            # Entries carried forward (unpresented last run, re-entering
            # this run's staged backlog) - the CAP-truncation reentry count.
            COVERAGE["cap_deferred_reentries"] += len(staged)
        run_fresh_n = n_fresh if (fresh_every_run or run_idx == 0) else 0
        fresh = _mk_entries("f", run_fresh_n, start=next_fresh_id)
        next_fresh_id += run_fresh_n
        combined = staged + fresh
        disp = {}
        for e in combined:
            outcome = rng.choice(_PRESENTABLE)
            if outcome == dmod.Outcome.REJECTED_ON_THE_MERITS:
                COVERAGE["rejected_outcomes_exercised"] += 1
            disp[e["sid"]] = outcome
        if n_fresh == 0:
            COVERAGE["zero_fresh_schedules"] += 1
        result = dmod.drain(staged, fresh, disp, **switches)
        _check_d1(_TC, result)
        COVERAGE["tier2_d1_results_checked"] += 1
        for e in dmod.presented(result):
            presented_at_run.setdefault(e["sid"], run_idx)
        results.append(result)
        staged = dmod.retained(result)
        if len(combined) == 1:
            COVERAGE["single_entry_mode_entered"] += 1
    return results, presented_at_run


def _size_pairs_tier2():
    """71 pairs: n_staged, n_fresh in 0..8 with sum > 3."""
    pairs = [
        (ns, nf)
        for ns in range(9)
        for nf in range(9)
        if ns + nf > 3
    ]
    return pairs


class TestD2ResidencyBound(unittest.TestCase):
    N_PER_SIZE = 200

    def test_d2_residency_bound(self):
        """D2: an entry at arrival index k (0-based, within its own
        staged+fresh combined ordering at the run it first appears) is
        presented within k+1 runs of first appearing - including zero-fresh
        and all-rejected schedules.

        Fresh entries arrive ONCE (run 0 only, `fresh_every_run=False`) - a
        one-off arrival, not a sustained inflow. D3/D5 already cover the
        steady-state case (inflow <= throughput, sustainable indefinitely);
        a sustained inflow EXCEEDING cap has no finite residency bound in
        any cap-limited system and is not what D2 asserts. Worst case here
        is 16 entries total (8+8) at cap=3/run once no new fresh arrive,
        needing ceil(16/3)=6 runs to fully clear - `n_runs=8` leaves margin."""
        pairs = _size_pairs_tier2()
        COVERAGE["tier2_size_pairs"] += len(pairs)
        self.assertEqual(len(pairs), 71)
        for (n_staged, n_fresh) in pairs:
            rng = random.Random(SEED + n_staged * 100 + n_fresh)
            for _ in range(self.N_PER_SIZE):
                COVERAGE["tier2_schedules"] += 1
                results, presented_at_run = _run_schedule(
                    rng, n_staged, n_fresh, n_runs=8, fresh_every_run=False
                )
                # Every entry that ever appeared in staged/fresh across the
                # simulation must have been presented by the time its
                # residency bound elapses. Index k = its position in the
                # arrival order of the run it FIRST appeared in.
                first_run_order = {}
                for run_idx, r in enumerate(results):
                    for k, e in enumerate(r.order):
                        first_run_order.setdefault(e["sid"], (run_idx, k))
                for sid, (first_run, k) in first_run_order.items():
                    self.assertIn(
                        sid, presented_at_run,
                        f"D2: {sid} (arrival index {k}, first seen run "
                        f"{first_run}) was never presented across "
                        f"{len(results)} runs",
                    )
                    presented_run = presented_at_run[sid]
                    runs_elapsed = presented_run - first_run + 1
                    self.assertLessEqual(
                        runs_elapsed, k + 1,
                        f"D2: {sid} at arrival index {k} took "
                        f"{runs_elapsed} runs to present (bound: k+1="
                        f"{k + 1})",
                    )


class TestD3NoFreshStarvation(unittest.TestCase):
    def test_d3_no_fresh_starvation(self):
        """Under defaults, a fresh entry submitted alongside an arbitrarily
        large staged backlog is presented on its own submitting run (the
        RESERVE floor guarantee)."""
        rng = random.Random(SEED + 1)
        for _ in range(200):
            n_staged = rng.randint(dmod.CAP, 20)
            staged = _mk_entries("s", n_staged)
            fresh = _mk_entries("f", 1)
            disp = {e["sid"]: dmod.Outcome.APPENDED for e in staged + fresh}
            result = dmod.drain(staged, fresh, disp)
            self.assertIn("f0", result.presented_sids)


class TestD4FailClosedAtomicity(unittest.TestCase):
    def test_d4_fail_closed_atomicity(self):
        staged = [{"sid": "s0", "quote": "q0"}]
        fresh = [{"sid": "s0", "quote": "q1"}]  # duplicate sid
        with self.assertRaises(ValueError):
            dmod.drain(staged, fresh, {})

        no_sid = [{"quote": "q0"}]
        with self.assertRaises(ValueError):
            dmod.drain(no_sid, [], {})


class TestD5NoReservedSlotCapture(unittest.TestCase):
    def test_d5_no_reserved_slot_capture(self):
        """Under defaults, a fresh entry is never permanently blocked by a
        stale presented entry re-capturing its reserved slot run after
        run."""
        rng = random.Random(SEED + 2)
        for _ in range(100):
            n_staged = rng.randint(5, 15)
            _, presented_at_run = _run_schedule(rng, n_staged, 1, n_runs=8)
            self.assertIn("f0", presented_at_run)
            self.assertEqual(presented_at_run["f0"], 0)


class TestMissingOrDuplicateSidAborts(unittest.TestCase):
    def test_missing_or_duplicate_sid_aborts(self):
        with self.assertRaises(ValueError):
            dmod.drain([{"sid": "a"}, {"sid": "a"}], [], {})
        with self.assertRaises(ValueError):
            dmod.drain([{"sid": ""}], [], {})
        with self.assertRaises(ValueError):
            dmod.drain([{}], [], {})


class TestUnverifiableDuplicateQuoteAborts(unittest.TestCase):
    def test_unverifiable_duplicate_quote_aborts(self):
        entry = {"sid": "a"}  # no quote field
        disp = {"a": dmod.Outcome.SKIPPED_ALREADY_A_STRUCTURED_LEARNING}
        with self.assertRaises(ValueError):
            dmod.drain([entry], [], disp)

        entry2 = {"sid": "b", "quote": "   "}  # whitespace-only
        disp2 = {"b": dmod.Outcome.SKIPPED_DUPLICATE_OF_DESTINATION_OR_ALREADY_PRESENTED}
        with self.assertRaises(ValueError):
            dmod.drain([entry2], [], disp2)

        # A verifiable quote passes.
        entry3 = {"sid": "c", "quote": "the actual quoted text"}
        disp3 = {"c": dmod.Outcome.SKIPPED_ALREADY_A_STRUCTURED_LEARNING}
        result = dmod.drain([entry3], [], disp3)
        self.assertIn("c", result.presented_sids)


class TestAbortPathTerminates(unittest.TestCase):
    def test_abort_path_terminates(self):
        """Single-entry mode: a lone entry (n=1) is always presented within
        3 attempts (in fact within 1, since n=1 <= CAP). D2 holds at its
        own k+1 (k=0 -> presented within 1 run). Staging is never destroyed
        - the entry is never silently dropped from `order`."""
        for attempt in range(3):
            staged = _mk_entries("s", 1)
            disp = {"s0": dmod.Outcome.APPENDED}
            result = dmod.drain(staged, [], disp)
            self.assertIn("s0", result.presented_sids)
            self.assertEqual({e["sid"] for e in result.order}, {"s0"})
            COVERAGE["single_entry_mode_entered"] += 1


# ==========================================================================
# Mutation tests
# ==========================================================================


class TestMutationRejectDispositionRetainedIsRed(unittest.TestCase):
    def test_mutation_reject_disposition_retained_is_red(self):
        rng = random.Random(SEED + 3)
        staged = _mk_entries("s", 1)
        disp = {"s0": dmod.Outcome.REJECTED_ON_THE_MERITS}
        results = []
        cur_staged = staged
        for run_idx in range(5):
            result = dmod.drain(cur_staged, [], disp, reject_disposition="retained")
            results.append(result)
            cur_staged = dmod.retained(result)
        # D5/D2 defect: the rejected entry never leaves the backlog, so it
        # is still present after every run.
        self.assertTrue(all("s0" in {e["sid"] for e in r.order} for r in results))
        self.assertTrue(
            any("s0" in {e["sid"] for e in dmod.retained(r)} for r in results),
            "REJECT_DISPOSITION='retained' never caused a rejected entry "
            "to stay in the backlog (D2/D5 mutation was never caught)",
        )


class TestMutationOrderModeDateIsRed(unittest.TestCase):
    def test_mutation_order_mode_date_is_red(self):
        """ORDER_MODE='date' can reorder an OLDER-arrival entry behind a
        newer one that carries an earlier `date`, breaking D2's residency
        bound (which is keyed on arrival index, never date)."""
        staged = [
            {"sid": "old", "quote": "q", "date": "2026-01-05"},
        ]
        fresh = [
            {"sid": "new", "quote": "q", "date": "2020-01-01"},
        ]
        disp = {"old": dmod.Outcome.APPENDED, "new": dmod.Outcome.APPENDED}
        result = dmod.drain(staged, fresh, disp, order_mode="date")
        # Under date ordering, "new" (dated earlier) sorts before "old"
        # despite arriving later - its arrival-index bound is violated.
        self.assertEqual([e["sid"] for e in result.order], ["new", "old"])
        arrival_result = dmod.drain(staged, fresh, disp, order_mode="arrival")
        self.assertEqual(
            [e["sid"] for e in arrival_result.order], ["old", "new"]
        )
        self.assertNotEqual(
            [e["sid"] for e in result.order],
            [e["sid"] for e in arrival_result.order],
            "ORDER_MODE='date' never diverged from arrival order "
            "(mutation was never caught)",
        )


class TestMutationReserveRuleNoneIsRed(unittest.TestCase):
    def test_mutation_reserve_rule_none_is_red(self):
        staged = _mk_entries("s", dmod.CAP)
        fresh = _mk_entries("f", 1)
        disp = {e["sid"]: dmod.Outcome.APPENDED for e in staged + fresh}
        result = dmod.drain(staged, fresh, disp, reserve_rule="none")
        self.assertNotIn(
            "f0", result.presented_sids,
            "RESERVE_RULE='none' never starved a fresh entry "
            "(mutation was never caught)",
        )
        default_result = dmod.drain(staged, fresh, disp)
        self.assertIn("f0", default_result.presented_sids)


class TestUnpresentableDispositionAborts(unittest.TestCase):
    def test_unpresentable_disposition_aborts(self):
        """Outcomes 8-9 are drain()'s own labels, never adjudicator input."""
        for bad in (dmod.Outcome.DROPPED_BY_CAP, dmod.Outcome.NEVER_ADJUDICATED):
            with self.assertRaises(ValueError):
                dmod.drain([{"sid": "a", "quote": "q"}], [], {"a": bad})
        # A presentable outcome does not raise.
        r = dmod.drain([{"sid": "a", "quote": "q"}], [],
                       {"a": dmod.Outcome.APPENDED})
        self.assertIn("a", r.presented_sids)


class TestNoSkipGuardSwitchExists(unittest.TestCase):
    def test_no_skip_guard_switch_exists(self):
        """drain_model must NOT expose a SKIP_GUARD attribute - route-level
        guards belong to reach_model only. Modelling it in both is a defect
        a prior revision of this plan shipped."""
        self.assertFalse(hasattr(dmod, "SKIP_GUARD"))


class TestZReport(unittest.TestCase):
    def test_zz_report_coverage(self):
        print(
            "\ndrain coverage: tier1_size_pairs=%(tier1_size_pairs)d "
            "tier1_assignments=%(tier1_assignments)d "
            "tier2_size_pairs=%(tier2_size_pairs)d "
            "tier2_schedules=%(tier2_schedules)d "
            "tier2_d1_results_checked=%(tier2_d1_results_checked)d\n"
            "incidental: rejected_outcomes_exercised=%(rejected_outcomes_exercised)d "
            "zero_fresh_schedules=%(zero_fresh_schedules)d "
            "cap_deferred_reentries=%(cap_deferred_reentries)d "
            "single_entry_mode_entered=%(single_entry_mode_entered)d "
            "d1_correspondence_checks=%(d1_correspondence_checks)d"
            % COVERAGE
        )
        self.assertEqual(COVERAGE["tier1_size_pairs"], 21)
        self.assertEqual(COVERAGE["tier1_assignments"], 114381)
        self.assertEqual(COVERAGE["tier2_size_pairs"], 71)
        self.assertEqual(COVERAGE["tier2_schedules"], 14200)
        self.assertGreater(COVERAGE["rejected_outcomes_exercised"], 0)
        self.assertGreater(COVERAGE["zero_fresh_schedules"], 0)
        self.assertGreater(COVERAGE["cap_deferred_reentries"], 0)
        self.assertGreater(COVERAGE["single_entry_mode_entered"], 0)
        # tier2_d1_results_checked: every _run_schedule() call runs _check_d1
        # once per drain() call. Only D2 and D5 route through _run_schedule
        # (D3 and the mutation tests call drain() directly, uncounted here):
        #   D2: 71 size pairs * N_PER_SIZE(200) * n_runs(8) = 113600
        #   D5: 100 iterations * n_runs(8)                  =    800
        #   total                                           = 114400
        self.assertEqual(COVERAGE["tier2_d1_results_checked"], 114400)
        # No closed form for this one - it is a per-entry-per-result count
        # across a random simulation, not a derivable arithmetic sum. A
        # floor (>0) is the honest assertion; inventing a pinned value
        # would be an uninvestigated pin, exactly what this revision exists
        # to eliminate.
        self.assertGreater(COVERAGE["d1_correspondence_checks"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
