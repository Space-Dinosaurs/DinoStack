#!/usr/bin/env python3
"""
Purpose: Property tests for `drain_model.py`'s staging-drain invariants
         D1-D5, asserted over an exhaustive tier-1 sweep (every size <= 3
         entries, every one of the 9 Outcome values per entry) plus a
         seeded-random tier-2 sweep (sizes up to 8, multi-run simulation).

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

Performance: 3178 tier-1 assignments + 14200 tier-2 schedules; well under a
             few seconds.
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
}


def _mk_entries(prefix, n, start=0):
    return [
        {"sid": f"{prefix}{i}", "quote": f"quote-{prefix}{i}"}
        for i in range(start, start + n)
    ]


def _all_dispositions(sids, values):
    """itertools.product over `values` (the full 9-member Outcome universe),
    one choice per sid, in sid order - the literal tier-1 enumeration."""
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


class TestD1TierOne(unittest.TestCase):
    """Tier 1: exhaustive over every (n_staged, n_fresh) pair summing to
    <= 3, and every one of the 9^n disposition assignments for that size.
    For n <= 3 the #presented <= CAP(3) filter is NON-BINDING (drain()
    never truncates a group this small), so the assignment count collapses
    to 9^n exactly.

    COVERAGE["tier1_assignments"] must equal 3178, derived as follows.
    For n entries, assignments with #presented <= 3 = sum_{k=0}^{min(n,3)}
    C(n,k) * 7^k * 2^(n-k) (choose which k of n entries are "presented"-
    outcome-tagged, 7 presentable outcomes each, 2 unpresented outcomes for
    the rest). For n <= 3 the binomial filter never excludes anything,
    collapsing the sum to 9^n. Summing over the 10 size pairs (n+1 pairs at
    each total n, for n = 0..3, i.e. (n_staged, n_fresh) with n_staged +
    n_fresh == n):

        sum_{n=0}^{3} (n+1) * 9^n = 1*1 + 2*9 + 3*81 + 4*729
                                   = 1 + 18 + 243 + 2916 = 3178
    """

    def test_d1_partition_total_and_disjoint(self):
        values = list(dmod.Outcome)
        self.assertEqual(len(values), 9)
        for total in range(4):  # 0, 1, 2, 3
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
        self.assertEqual(COVERAGE["tier1_size_pairs"], 10)
        self.assertEqual(COVERAGE["tier1_assignments"], 3178)

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

#: The presentable outcomes a random adjudicator draws from (never one of
#: the two UNPRESENTED categories - a real adjudicator never self-assigns
#: "dropped by cap").
_PRESENTABLE = sorted(dmod.PRESENTED_OUTCOMES, key=lambda o: o.name)


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
            "tier2_schedules=%(tier2_schedules)d\n"
            "incidental: rejected_outcomes_exercised=%(rejected_outcomes_exercised)d "
            "zero_fresh_schedules=%(zero_fresh_schedules)d "
            "cap_deferred_reentries=%(cap_deferred_reentries)d "
            "single_entry_mode_entered=%(single_entry_mode_entered)d"
            % COVERAGE
        )
        self.assertEqual(COVERAGE["tier1_size_pairs"], 10)
        self.assertEqual(COVERAGE["tier1_assignments"], 3178)
        self.assertEqual(COVERAGE["tier2_size_pairs"], 71)
        self.assertEqual(COVERAGE["tier2_schedules"], 14200)
        self.assertGreater(COVERAGE["rejected_outcomes_exercised"], 0)
        self.assertGreater(COVERAGE["zero_fresh_schedules"], 0)
        self.assertGreater(COVERAGE["cap_deferred_reentries"], 0)
        self.assertGreater(COVERAGE["single_entry_mode_entered"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
