#!/usr/bin/env python3
"""
Purpose: Property tests for the DS-108 task-state fold invariants I1-I5, asserted
         over GENERATED interleavings rather than hand-traced cases. Four prior
         revisions of plan.md were each verified by hand-traced case analysis and
         each round of review found a real hole that the previous round's tracing
         missed. Hand-tracing cannot be exhaustive over interleavings; this is the
         mechanical replacement.

Public API: unittest TestCases. Run with
              python3 -m pytest docs/planning/tasks-jsonl-cross-session/ -q
            or, once shipped to its final home,
              python3 -m pytest bin/tests/test_fold_invariants.py -q
            (.github/workflows/bin-tests.yml:19 runs `python3 -m pytest bin/tests/ -q`,
            auto-discovering; no CI wiring is required.)

Upstream deps: fold_model.py (the single normative definition of the fold);
               stdlib `unittest` + `random` only. NO hypothesis - it is not a
               dependency of this repo and adding one is out of scope.

Downstream consumers: plan.md section 7 (verification step) and AC17/AC18/AC22/AC24.

Failure modes: DETERMINISTIC. Every generator is seeded from SEED below. A
               flaky invariant test is worse than none, so no unseeded RNG,
               no wall-clock, no filesystem, no network.

Performance: about 25k folds in total (`prefix_folds` in the emitted coverage
             line), well under a second.
"""

from __future__ import annotations

import os
import random
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fold_model as fm  # noqa: E402

SEED = 20260728
TASK = "DS-108-unit-a"

#: interleavings exercised, per property. Reported by test_zz_report_coverage.
#: The non-vacuity counters (`tally_logs` and the three that follow it) exist so
#: plan.md section 7's non-vacuity figures are RE-DERIVABLE from what ships
#: rather than asserted from a one-off manual count that nothing regenerates.
#: `tally_logs` is their denominator and counts ONLY the four size sweeps.
COVERAGE = {"I1": 0, "I2": 0, "I3": 0, "I4": 0, "I5": 0,
            "schedules": 0, "prefix_folds": 0,
            "reclaim_logs": 0, "reclaim_honored": 0,
            "legacy_groups": 0, "legacy_rows": 0,
            "tally_logs": 0, "multi_owner": 0,
            "claim_rejected_post_terminal": 0,
            "transition_rejected_unowned": 0,
            # Emitted status census over the four size sweeps. Added in
            # r5-round-3: the terminal-NON-done column (rows 4/10 and the
            # legacy + dispossessed terminal cells) had zero generated
            # coverage, and nothing in what shipped would have shown that.
            # A census the run emits cannot silently drift the way the
            # absence of one did.
            "st_pending": 0, "st_in_progress": 0, "st_failed": 0,
            "st_done": 0, "st_none": 0, "folded_terminal_non_done": 0}


def _sid(r):
    """A record's effective session_id. Absent = legacy (fold_model row 12)."""
    return r.get("session_id", fm.LEGACY_SENTINEL)


# ==========================================================================
# Schedule generation - a session's decision procedure is NON-ATOMIC
# ==========================================================================
#
# A session folds, decides, and only later appends. r3-Major-1 existed precisely
# in that gap: session B decided at t11 and its append landed at t11.5, after A
# had already appended `done` and merged. The scheduler below models the gap
# explicitly: a step evaluates its guard against the log AS IT IS AT DECISION
# TIME, the resulting record is STAGED, and it is released into the log after an
# arbitrary number of intervening events.


class Sess:
    """`label` names the writer; `sid` is the identity a READER can attribute
    records to. For a legacy session (a pre-fix writer that emits no
    `session_id`) those differ: the records it writes carry no id at all, and
    every reader - including itself - sees them as `LEGACY_SENTINEL`. That
    indistinguishability is the whole point of row 12, so the generator models
    it rather than assuming it away."""

    def __init__(self, label: str, steps, stale_view: bool, legacy: bool = False,
                 retry: bool = True):
        self.label = label
        self.legacy = legacy
        #: False = this session stops at `failed` and never retries to `done`,
        #: so the GROUP's folded status stays terminal-non-done and is left
        #: open for another session to claim. Without this, every `failed` is
        #: immediately overwritten by the same session's `done` and the folded
        #: terminal-non-done state is reachable only by a scheduling accident
        #: (measured: 1 of 800 logs before this flag existed).
        self.retry = retry
        self.sid = fm.LEGACY_SENTINEL if legacy else label
        self.steps = list(steps)
        self.i = 0
        self.alive = True
        self.stale_view = stale_view
        self.branch = False

    @property
    def exhausted(self) -> bool:
        return not self.alive or self.i >= len(self.steps)


def _view(log, sess):
    """The fold a session sees at decision time (its own gate read)."""
    idx = fm.fold(log)
    return idx.get(TASK)


def _step_init(sess, res, w2_guard):
    # W2 (content/commands/ds-implement-ticket.md Phase 3b) appends one `pending`
    # entry per planner unit. With the W2 guard active it MUST NOT append when the
    # task_id already has records.
    if w2_guard and res is not None:
        return None
    return {"task_id": TASK, "session_id": sess.label, "status": "pending",
            "created_at": "t0", "inputs": {"quality_cmd": "make test"}}


def _step_claim(sess, res, _w2):
    # A legacy session is a PRE-FIX writer: it predates the section 3.3 gate and
    # does not consult it. Modelling it as gated would assume away exactly the
    # unguarded appends row 12 exists to absorb.
    if res is not None and not sess.legacy:
        row = fm.classify(res, sess.sid, branch=sess.branch, stale=sess.stale_view)
        if row not in fm.SPAWN_PERMITTED:
            sess.alive = False
            return None
    sess.branch = True
    return {"task_id": TASK, "session_id": sess.label, "status": "in_progress",
            "branch_name": "%s/branch" % sess.label, "assigned_agent": "engineer"}


def _step_output(sess, res, _w2):
    # W4/W7: output-only append. Carries NO `status` field (plan.md section 3.1).
    return {"task_id": TASK, "session_id": sess.label,
            "commit_sha": "%s-sha" % sess.label, "worker_summary": "ok"}


def _step_failed(sess, res, _w2):
    """A TERMINAL-NON-DONE status, then a retry to `done` at the next step.

    Added in r5-round-3. Through round 2 the generator emitted only
    `pending` / `in_progress` / `done` / no-status, so the terminal-non-done
    column of plan.md section 2 - rows 4 and 10, plus the legacy and
    dispossessed terminal cells - had ZERO generated coverage. That is exactly
    the column where `done` is absorbing and the other terminal values are not,
    i.e. where ownership legitimately still moves: a `failed` group is
    re-claimable, a `done` group is not. `failed` is in `fold_model.SYNC_TERMINAL`
    but NOT in `FOLD_ABSORBING`, and the two sets are deliberately distinct
    (fold_model.py:57-61); nothing exercised that distinction before.

    Gated like `_step_terminal`: section 3.3 gate point 2 forbids a
    dispossessed session appending a terminal status, and `failed` is terminal.
    """
    if res is not None and not sess.legacy and res.session_id != sess.sid:
        sess.alive = False
        return None
    return {"task_id": TASK, "session_id": sess.label, "status": "failed",
            "outputs.skeptic_status": "findings"}


def _step_terminal(sess, res, _w2):
    # A session that does not retry stops at `failed` (see `Sess.retry`), which
    # is what leaves a group folded terminal-NON-done for another session to
    # claim - rows 4 and 10.
    if not sess.retry:
        sess.alive = False
        return None
    # plan.md section 3.3 gate point 2: a dispossessed session MUST NOT append a
    # terminal status. Legacy writers predate that gate (see `_step_claim`).
    if res is not None and not sess.legacy and res.session_id != sess.sid:
        sess.alive = False
        return None
    return {"task_id": TASK, "session_id": sess.label, "status": "done",
            "outputs.skeptic_status": "sign-off"}


PROGRAM = [_step_init, _step_claim, _step_output, _step_failed, _step_terminal]

#: KL10 names one legitimate flow the 4-step PROGRAM cannot express: a session
#: whose claim was superseded (in error or otherwise) re-claiming the task by
#: appending a FRESH `in_progress` through the §3.3 gate. r5 named this as a
#: generator gap; this closes it. `_step_claim` consults `SPAWN_PERMITTED`
#: first, so a session in rows 14/15 (dispossessed) or row 3 (own+done) still
#: cannot re-claim - only rows the gate actually permits produce a second claim.
RECLAIM_PROGRAM = PROGRAM + [_step_claim, _step_output, _step_terminal]


def run_schedule(rng, n_sessions, w2_guard=True, program=None, n_legacy=0,
                 **fold_kwargs):
    """Produce one arrival-ordered log from an arbitrary interleaving.

    `n_legacy` adds pre-fix writers whose records carry NO `session_id`. Row 12
    is the only B value the generator could not previously reach, which is
    precisely why the r5 model could discard those records unnoticed.
    """
    program = PROGRAM if program is None else program
    labels = ["S%d" % i for i in range(1, n_sessions + 1)]
    labels += ["L%d" % i for i in range(1, n_legacy + 1)]
    sessions = [Sess(s, program, stale_view=rng.random() < 0.5,
                     legacy=s.startswith("L"), retry=rng.random() < 0.5)
                for s in labels]
    # Deterministic per-session clock offset. Never `hash()`: PYTHONHASHSEED is
    # random by default and would make this suite flaky in CI.
    skew = {s: i % 3 for i, s in enumerate(labels)}
    log = []
    staged = []
    guard = 0
    while True:
        guard += 1
        if guard > 400:
            break
        runnable = [s for s in sessions if not s.exhausted]
        if not runnable and not staged:
            break
        choices = []
        if runnable:
            choices.append("advance")
        if staged:
            choices.append("release")
        act = rng.choice(choices)
        if act == "advance":
            sess = rng.choice(runnable)
            step = sess.steps[sess.i]
            sess.i += 1
            res = _view(log, sess)
            rec = step(sess, res, w2_guard)
            if rec is not None:
                rec = dict(rec)
                # `updated_at` is second-granular and clock-dependent (KL2). The
                # generator gives each session its own small offset so skewed
                # clocks are exercised, not assumed away.
                rec["updated_at"] = len(log) + len(staged) + skew[sess.label]
                if sess.legacy:
                    # A pre-fix record. The documented schema never mandated
                    # `session_id`, so this is a spec-compliant line, not a
                    # corrupt one.
                    rec.pop("session_id", None)
                staged.append(rec)
        else:
            log.append(staged.pop(rng.randrange(len(staged))))
    log.extend(staged)
    return log


# ==========================================================================
# Invariant checkers
# ==========================================================================


def mergers(log, **kw):
    """Every session that is merge-eligible at ANY prefix. I1 bounds this to 1.

    Scanning every prefix - not just the final state - is what makes this test
    cover the non-atomic decide/append gap exhaustively for a given log.
    """
    out = set()
    for k in range(len(log) + 1):
        res = fm.fold(log[:k], **kw).get(TASK)
        COVERAGE["prefix_folds"] += 1
        if res is None:
            continue
        for sid in {_sid(r) for r in log[:k]}:
            if fm.may_merge(res, sid):
                out.add(sid)
    return out


def check_I1(tc, log, **kw):
    COVERAGE["I1"] += 1
    m = mergers(log, **kw)
    tc.assertLessEqual(len(m), 1, "I1 violated: sessions %s all merge-eligible\nlog=%s"
                       % (sorted(m), _fmt(log)))


def check_I2(tc, log, res=None, **kw):
    """`res` is an injection point, used by
    `test_I2_build_field_check_can_fail` to prove the build-field half can
    fail on a hand-spliced `FoldResult`.

    Corrected in r5-round-3: the claim that NO mutation switch reaches the
    build-field half was true only of the four switches that existed then, not
    of the specification. `WHITELIST_MODE = "drift"` - adding `branch_name` to
    `CROSS_GENERATION_WHITELIST`, the exact drift AC23 exists to prevent -
    reaches it on GENERATED logs (measured below in
    `test_whitelist_drift_breaks_I2`). The injection test is kept because it
    covers all three branches individually, including the dropped-field branch
    that no switch produces."""
    COVERAGE["I2"] += 1
    if res is None:
        res = fm.fold(log, **kw).get(TASK)
    if res is None or res.status != "done":
        return
    tc.assertEqual(res.done_by, res.session_id,
                   "I2 violated: folded done came from %s but folded owner is %s\nlog=%s"
                   % (res.done_by, res.session_id, _fmt(log)))
    # Build fields, recomputed from the RAW group rather than interrogated in
    # `res.provenance`. The provenance form (shipped through r5) could not
    # fail: pass 2 only ever writes `provenance[k] = sid` when `sid == owner`
    # for a non-whitelisted key, so asking provenance whether a build field
    # came from a non-owner is the same shape as the r5-Major-2 defect - the
    # owner filter is applied before the question is asked. Re-measured in
    # r5-round-3 over 400 logs x both `owner_test` settings: 1,125 build-field
    # provenance entries, 0 with provenance != owner; all 19/200 reds credited
    # to I2 under `owner_test=False` come from the `done_by` assertion alone,
    # and the four pre-`WHITELIST_MODE` switches produce 0 build-field reds
    # between them. The form below derives `expected` from the raw arrival
    # order independently of pass 2, so it can disagree with it - which is what
    # lets `WHITELIST_MODE = "drift"` turn it red on generated logs (17/200).
    for name in fm._BUILD_FIELDS:
        owner_vals = [r[name] for r in res.raw
                      if _sid(r) == res.session_id and name in r]
        if name in res.fields:
            tc.assertTrue(owner_vals,
                          "I2 violated: folded %s=%r beside a done owned by %s, "
                          "which never appended that field\nlog=%s"
                          % (name, res.fields[name], res.session_id, _fmt(log)))
            tc.assertEqual(res.fields[name], owner_vals[-1],
                           "I2 violated: folded %s=%r but owner %s last appended %r\nlog=%s"
                           % (name, res.fields[name], res.session_id,
                              owner_vals[-1], _fmt(log)))
        else:
            tc.assertFalse(owner_vals,
                           "I2 violated: owner %s appended %s=%r but it is absent "
                           "from the folded record\nlog=%s"
                           % (res.session_id, name, owner_vals[-1:], _fmt(log)))


def check_I3(tc, log, **kw):
    COVERAGE["I3"] += 1
    frozen_owner = None
    for k in range(len(log) + 1):
        res = fm.fold(log[:k], **kw).get(TASK)
        if res is None:
            continue
        if frozen_owner is not None:
            tc.assertEqual(res.session_id, frozen_owner,
                           "I3 violated: folded owner moved to %s after done froze it at %s\nlog=%s"
                           % (res.session_id, frozen_owner, _fmt(log)))
        elif res.status == "done":
            frozen_owner = res.session_id


def check_I4(tc, log, **kw):
    COVERAGE["I4"] += 1
    res = fm.fold(log, **kw).get(TASK)
    if res is None:
        return
    for t in res.trace:
        if t.kind != "transition":
            continue
        if t.owner_before is None:
            continue  # bootstrap: the earliest record establishes ownership
        tc.assertEqual(t.session_id, t.owner_before,
                       "I4 violated: status transition to %r by %s while owner was %s\nlog=%s"
                       % (t.status, t.session_id, t.owner_before, _fmt(log)))


def check_I5(tc, log, **kw):
    """I5 - owner-scoped freshness. The folded `updated_at` is the one carried by
    the LATEST ARRIVAL-ORDER RECORD OF THE FOLDED OWNER, and nothing else.

    Corollary asserted directly below: a record from a non-owner can never
    refresh it. That corollary is the load-bearing half - the reading it rules
    out (`latest record in the group`) lets a foreign stray `pending` renew the
    incumbent's freshness, pinning row 7 forever and hard-blocking the orphan
    recovery rows 7/8 exist to arbitrate.
    """
    COVERAGE["I5"] += 1
    res = fm.fold(log, **kw).get(TASK)
    if res is None:
        return
    owner_recs = [r for r in log if _sid(r) == res.session_id
                  and "updated_at" in r]
    expected = owner_recs[-1]["updated_at"] if owner_recs else None
    tc.assertEqual(res.updated_at, expected,
                   "I5 violated: folded updated_at=%r but owner %s last appended %r\nlog=%s"
                   % (res.updated_at, res.session_id, expected, _fmt(log)))
    # Corollary, asserted constructively: a FOREIGN stray `pending` carrying a
    # far-future timestamp - exactly the AC20 defence-in-depth case - moves
    # neither the folded owner nor the folded freshness.
    stray = dict(log[-1]) if log else None
    if stray is not None:
        stray = {"task_id": TASK, "session_id": "STRAY", "status": "pending",
                 "updated_at": 10 ** 9}
        after = fm.fold(list(log) + [stray], **kw)[TASK]
        tc.assertEqual((after.session_id, after.updated_at),
                       (res.session_id, res.updated_at),
                       "I5 violated: a foreign stray refreshed the incumbent\nlog=%s"
                       % _fmt(log))


def check_legacy(tc, log, **kw):
    """Row 12 / AC25. The disposition of a group whose folded owner is legacy.

    Three assertions, each pinning one clause of `fold_model.LEGACY_SENTINEL`:
    the group FOLDS (r5 discarded it, so row 12 was unreachable and the reader
    took the no-task-state spawn-and-merge path); no viewer reads it as `own`
    or may merge it; and it routes to rows 6/8/9/10 (9 splitting to 16 by
    `holds-a-branch`, per the matrix's `legacy` row) - NEVER row 7.
    """
    res = fm.fold(log, **kw).get(TASK)
    if any(isinstance(r, dict) and "task_id" in r for r in log):
        tc.assertIsNotNone(
            res, "legacy records were discarded by the fold - row 12 is "
                 "unreachable and the reader sees no task state\nlog=%s" % _fmt(log))
    if res is None or res.session_id != fm.LEGACY_SENTINEL:
        return
    COVERAGE["legacy_groups"] += 1
    viewers = sorted({_sid(r) for r in log} | {"OUTSIDER"})
    for v in viewers:
        COVERAGE["legacy_rows"] += 1
        row = fm.classify(res, v, stale=False)  # stale=False: forced True anyway
        tc.assertFalse(fm.may_merge(res, v),
                       "row 12 violated: %s may merge a legacy-owned group\nlog=%s"
                       % (v, _fmt(log)))
        tc.assertNotEqual(row, "row7",
                          "row 12 violated: viewer %s routed to row 7 on a legacy "
                          "owner; an absent session_id cannot be shown live\nlog=%s"
                          % (v, _fmt(log)))
        tc.assertNotIn(row, ("row1", "row2", "row3", "row4"),
                       "row 12 violated: viewer %s read a legacy group as OWN (%s)\nlog=%s"
                       % (v, row, _fmt(log)))
        superseded = any(t.session_id == v and t.kind == "claim" for t in res.trace)
        if not superseded:
            # Row 16 is admitted here because it is row 9's `holds-a-branch`
            # split, exactly as plan.md's B x C matrix (the `legacy` row) says:
            # "row 9 / row 16 by holds-a-branch". Row 12's prose sentence said
            # only "rows 6/8/9/10" and so contradicted the matrix directly
            # above it - a prose defect this test found on its first run, on
            # both a generated 3-session log and the named `done` case. The
            # PROSE was corrected; the assertion follows the matrix.
            tc.assertIn(row, ("row6", "row8", "row9", "row10", "row16"),
                        "row 12 violated: viewer %s routed to %s, outside rows "
                        "6/8/9/10/16\nlog=%s" % (v, row, _fmt(log)))


def tally(log, **kw):
    """Non-vacuity census. Emitted by COVERAGE so plan.md section 7's figures
    are regenerable rather than asserted from an unrepeatable manual count."""
    COVERAGE["tally_logs"] += 1
    for r in log:
        s = r.get("status")
        COVERAGE["st_" + (s if s in ("pending", "in_progress", "failed", "done")
                          else "none")] += 1
    res = fm.fold(log, **kw).get(TASK)
    if res is None:
        return
    if res.status is not None and res.status not in fm.FOLD_ABSORBING \
            and res.status in fm.SYNC_TERMINAL:
        COVERAGE["folded_terminal_non_done"] += 1
    if len({t.session_id for t in res.trace if t.kind == "claim"}) > 1:
        COVERAGE["multi_owner"] += 1
    kinds = {t.kind for t in res.trace}
    if "claim_rejected_post_terminal" in kinds:
        COVERAGE["claim_rejected_post_terminal"] += 1
    if "transition_rejected_unowned" in kinds:
        COVERAGE["transition_rejected_unowned"] += 1


def _fmt(log):
    return "\n  " + "\n  ".join(
        "%s %s%s" % (_sid(r), r.get("status", "(no-status)"),
                     " ua=%s" % r.get("updated_at")) for r in log)


# ==========================================================================
# Named regression cases from prior reviews
# ==========================================================================

#: (a) r3-Major-1. B decides a stale-orphan takeover, A appends `done` and
#: merges, then B's claim lands post-terminal. Both sessions merged.
R3_MAJOR_1 = [
    {"task_id": TASK, "session_id": "A", "status": "pending", "updated_at": 1},
    {"task_id": TASK, "session_id": "A", "status": "in_progress", "updated_at": 2,
     "branch_name": "A/b"},
    {"task_id": TASK, "session_id": "A", "commit_sha": "a1", "updated_at": 10},
    {"task_id": TASK, "session_id": "A", "status": "done", "updated_at": 11,
     "outputs.skeptic_status": "sign-off"},
    # B decided at ua=3; its append lands here, at ua=12.
    {"task_id": TASK, "session_id": "B", "status": "in_progress", "updated_at": 12,
     "branch_name": "B/b"},
    {"task_id": TASK, "session_id": "B", "status": "done", "updated_at": 20,
     "commit_sha": "b1", "outputs.skeptic_status": "sign-off"},
]

#: (b) r4-Major-1. A concurrent session's Phase-3b init (W2,
#: content/commands/ds-implement-ticket.md) appends `pending` per planner unit,
#: regressing a live `in_progress` and routing the reader to row 6
#: ("Spawn permitted"), bypassing row 7 - the headline duplicate-fan-out guard.
R4_MAJOR_1 = [
    {"task_id": TASK, "session_id": "A", "status": "pending", "updated_at": 1},
    {"task_id": TASK, "session_id": "A", "status": "in_progress", "updated_at": 2,
     "branch_name": "A/b"},
    {"task_id": TASK, "session_id": "B", "status": "pending", "updated_at": 3},
]

#: (c) Ordering. A record arriving late but carrying an EARLIER `updated_at`.
#: Under the r4 ordering key ((updated_at ASC, line order ASC)) it sorts BEFORE
#: the already-observed `done`, so the fold is not prefix-monotonic and the
#: freeze lemma does not hold.
CLOCK_SKEW = [
    {"task_id": TASK, "session_id": "A", "status": "pending", "updated_at": 1},
    {"task_id": TASK, "session_id": "A", "status": "in_progress", "updated_at": 10,
     "branch_name": "A/b"},
    {"task_id": TASK, "session_id": "A", "status": "done", "updated_at": 20,
     "commit_sha": "a1", "outputs.skeptic_status": "sign-off"},
    {"task_id": TASK, "session_id": "B", "status": "in_progress", "updated_at": 15,
     "branch_name": "B/b"},
    {"task_id": TASK, "session_id": "B", "status": "done", "updated_at": 25,
     "commit_sha": "b1"},
]

#: (d) r5-round-2 Major-1. A pre-fix log: no record carries `session_id`. The
#: documented schema (content/references/task-state-file.md) never mandated the
#: field, so this is spec-compliant, not corrupt. Under the r5 model it folded
#: to NOTHING and `fold_group` raised `KeyError`, making row 12's entire
#: disposition unreachable for exactly the population it was written for.
LEGACY_ONLY = [
    {"task_id": TASK, "status": "pending", "updated_at": 1},
    {"task_id": TASK, "status": "in_progress", "updated_at": 2,
     "branch_name": "L/b"},
]

#: (e) The mixed case. A legacy claim precedes a modern one; the modern claim
#: supersedes it monotonically, and the legacy generation's `branch_name` is
#: dropped from the folded record by the whitelist exactly as a superseded
#: modern generation's would be.
LEGACY_MIXED = LEGACY_ONLY + [
    {"task_id": TASK, "session_id": "B", "status": "in_progress", "updated_at": 3,
     "branch_name": "B/b"},
]


# ==========================================================================
# Tests
# ==========================================================================


class TestGeneratedInterleavings(unittest.TestCase):
    """I1-I4 over generated interleavings across 2, 3, 4 and 5 sessions.

    r4 claimed 4+-session sequences were covered "for free" by the freeze lemma.
    That claim is TESTED here, not assumed: 4- and 5-session counts get the same
    per-schedule assertions as the 2-session case.
    """

    N_PER_SIZE = 200

    def _sweep(self, n_sessions, **kw):
        rng = random.Random(SEED + n_sessions)
        for _ in range(self.N_PER_SIZE):
            log = run_schedule(rng, n_sessions, **kw)
            COVERAGE["schedules"] += 1
            check_I1(self, log)
            check_I2(self, log)
            check_I3(self, log)
            check_I4(self, log)
            check_I5(self, log)
            tally(log)

    def test_two_sessions(self):
        self._sweep(2)

    def test_three_sessions(self):
        self._sweep(3)

    def test_four_sessions(self):
        self._sweep(4)

    def test_five_sessions(self):
        self._sweep(5)

    def test_reclaim_after_dispossession(self):
        """KL10's legitimate re-claim flow - a named generator gap through r5.
        Sessions may append a SECOND `in_progress` when the §3.3 gate permits
        it, so a schedule can contain more claims than sessions.

        Widened in r5-round-2: the sweep was 200 schedules at 3 sessions and
        reported only the APPENDED count, which overstated the slice - most
        repeat appends are rejected post-terminal and exercise I3's rejection
        path, not the reclaim flow. It now runs 2, 3 and 4 sessions (fewer
        concurrent sessions produce more honored reclaims, measured) and
        asserts on the HONORED count, which is the one that measures what this
        test exists for. Both counts are reported."""
        rng = random.Random(SEED + 41)
        reclaims = 0
        honored = 0
        for n_sessions in (2, 3, 4):
            for _ in range(self.N_PER_SIZE):
                log = run_schedule(rng, n_sessions, program=RECLAIM_PROGRAM)
                COVERAGE["schedules"] += 1
                claims = [r for r in log if r.get("status") == "in_progress"]
                per_sid = {}
                for r in claims:
                    per_sid[_sid(r)] = per_sid.get(_sid(r), 0) + 1
                if any(v > 1 for v in per_sid.values()):
                    reclaims += 1
                # APPENDED twice is not the same as RECLAIMED. A second
                # `in_progress` the fold rejects (post-terminal, I3) exercises
                # the rejection path, not KL10's reclaim flow, so the honored
                # count is the one that measures this test's own slice.
                res = fm.fold(log)[TASK]
                per_owner = {}
                for t in res.trace:
                    if t.kind == "claim":
                        per_owner[t.session_id] = per_owner.get(t.session_id, 0) + 1
                if any(v > 1 for v in per_owner.values()):
                    honored += 1
                check_I1(self, log)
                check_I2(self, log)
                check_I3(self, log)
                check_I4(self, log)
                check_I5(self, log)
        COVERAGE["reclaim_logs"] = reclaims
        COVERAGE["reclaim_honored"] = honored
        self.assertGreater(reclaims, 0,
                           "no schedule exercised a re-claim - the gap is not closed")
        # Measured 40 of 600 (the appended count is 97 of 600), re-baselined in
        # r5-round-3 when `_step_failed` widened the program - a `failed` group
        # is re-claimable, so more repeat claims are honored than before (was
        # 16 of 600 at a floor of 10). Floored at 24, ~60% of measured, rather
        # than at 0: the generator is seeded and deterministic, so a drop below
        # the floor means the reclaim slice thinned, which is the exact drift
        # r5-round-2 review caught by hand.
        self.assertGreaterEqual(honored, 24,
                                "the honored-reclaim slice thinned to %d/600; "
                                "repeat claims are being rejected rather than "
                                "honored, so KL10's flow is unexercised" % honored)

    def test_legacy_mixed_interleavings(self):
        """Row 12 over generated logs: legacy writers (no `session_id`) mixed
        with modern ones, and legacy-only. r5's fold discarded these records
        entirely, so no generated schedule could reach row 12 - a sentinel
        without generated coverage would drift the same way."""
        rng = random.Random(SEED + 12)
        for n_sess, n_leg in ((2, 1), (1, 2), (0, 2), (3, 2)):
            for _ in range(self.N_PER_SIZE):
                log = run_schedule(rng, n_sess, n_legacy=n_leg)
                COVERAGE["schedules"] += 1
                check_I1(self, log)
                check_I2(self, log)
                check_I3(self, log)
                check_I4(self, log)
                check_I5(self, log)
                check_legacy(self, log)

    def test_w2_guard_off_still_holds_by_I4(self):
        """Even with W2's suppression disabled, I4 must keep a foreign `pending`
        from regressing a live `in_progress`. The W2 guard is defence in depth,
        not the load-bearing mechanism."""
        rng = random.Random(SEED + 99)
        for _ in range(self.N_PER_SIZE):
            log = run_schedule(rng, 3, w2_guard=False)
            COVERAGE["schedules"] += 1
            check_I1(self, log)
            check_I4(self, log)


class TestNamedRegressions(unittest.TestCase):
    def test_r3_major_1_single_merger(self):
        self.assertEqual(mergers(R3_MAJOR_1), {"A"})
        check_I1(self, R3_MAJOR_1)
        check_I3(self, R3_MAJOR_1)
        res = fm.fold(R3_MAJOR_1)[TASK]
        self.assertEqual((res.session_id, res.status), ("A", "done"))
        # B reads row 16: foreign `done` while holding its own branch. The
        # `branch` predicate is NOT supplied - a test that hands the model the
        # answer cannot detect the model's inability to compute it (r5-Major-2).
        self.assertTrue(fm.holds_branch(res, "B"))
        self.assertFalse(fm.holds_branch(res, "C"))
        self.assertEqual(fm.classify(res, "B"), "row16")
        # ...and a session with no build record of its own still reads row 9.
        self.assertEqual(fm.classify(res, "C"), "row9")

    def test_r4_major_1_pending_does_not_regress_in_progress(self):
        res = fm.fold(R4_MAJOR_1)[TASK]
        self.assertEqual((res.session_id, res.status), ("A", "in_progress"))
        self.assertEqual(fm.classify(res, "B", stale=False), "row7")
        self.assertNotIn(fm.classify(res, "B", stale=False), fm.SPAWN_PERMITTED)
        check_I4(self, R4_MAJOR_1)

    def test_legacy_only_group_folds_and_routes_to_row_8(self):
        idx = fm.fold(LEGACY_ONLY)
        self.assertEqual(list(idx), [TASK], "a legacy group must not fold to nothing")
        res = idx[TASK]
        self.assertEqual((res.session_id, res.status),
                         (fm.LEGACY_SENTINEL, "in_progress"))
        self.assertEqual(res.skipped, 0, "a legacy record is not `skipped`")
        # `fold_group` accepts it - through r5 this raised KeyError.
        self.assertEqual(fm.fold_group(LEGACY_ONLY).session_id, fm.LEGACY_SENTINEL)
        # Row 12: foreign and stale, so row 8 and NEVER row 7 - even when the
        # caller asserts freshness. Takeover permitted; deadlock avoided.
        self.assertEqual(fm.classify(res, "B", stale=False), "row8")
        self.assertIn(fm.classify(res, "B", stale=False), fm.SPAWN_PERMITTED)
        # No viewer - not even an unattributed one - reads it as own or merges.
        for v in ("B", fm.LEGACY_SENTINEL):
            self.assertFalse(fm.may_merge(res, v))
            self.assertNotIn(fm.classify(res, v), ("row1", "row2", "row3", "row4"))
        # An unattributed `branch_name` is claimable by nobody.
        self.assertFalse(fm.holds_branch(res, fm.LEGACY_SENTINEL))
        self.assertFalse(fm.holds_branch(res, "B"))
        check_legacy(self, LEGACY_ONLY)
        check_I1(self, LEGACY_ONLY)
        check_I5(self, LEGACY_ONLY)

    def test_legacy_done_routes_9_or_16_by_the_viewers_own_records(self):
        log = LEGACY_ONLY + [
            {"task_id": TASK, "status": "done", "updated_at": 3},
            {"task_id": TASK, "session_id": "B", "commit_sha": "b1", "updated_at": 4},
        ]
        res = fm.fold(log)[TASK]
        self.assertEqual((res.session_id, res.status),
                         (fm.LEGACY_SENTINEL, "done"))
        self.assertEqual(fm.classify(res, "C"), "row9")   # no build record
        self.assertEqual(fm.classify(res, "B"), "row16")  # holds its own
        self.assertFalse(fm.may_merge(res, "B"))
        check_legacy(self, log)

    def test_legacy_claim_is_superseded_monotonically(self):
        res = fm.fold(LEGACY_MIXED)[TASK]
        self.assertEqual((res.session_id, res.status), ("B", "in_progress"))
        self.assertEqual(res.fields.get("branch_name"), "B/b")
        self.assertEqual(fm.classify(res, "B"), "row2")
        check_I1(self, LEGACY_MIXED)
        check_I4(self, LEGACY_MIXED)
        check_I5(self, LEGACY_MIXED)

    def test_clock_skew_single_merger(self):
        self.assertEqual(mergers(CLOCK_SKEW), {"A"})
        check_I1(self, CLOCK_SKEW)
        check_I3(self, CLOCK_SKEW)


class TestMutationsGoRed(unittest.TestCase):
    """Prove the tests can fail. Each mutation reintroduces a defect a prior
    review found; the corresponding property MUST go RED."""

    def test_removing_done_guard_breaks_I1_and_I3(self):
        with self.assertRaises(AssertionError):
            check_I1(self, R3_MAJOR_1, done_guard=False)
        with self.assertRaises(AssertionError):
            check_I3(self, R3_MAJOR_1, done_guard=False)
        self.assertEqual(mergers(R3_MAJOR_1, done_guard=False), {"A", "B"})

    def test_removing_owner_test_breaks_I4(self):
        with self.assertRaises(AssertionError):
            check_I4(self, R4_MAJOR_1, owner_test=False)
        res = fm.fold(R4_MAJOR_1, owner_test=False)[TASK]
        self.assertEqual(res.status, "pending")
        self.assertEqual(fm.classify(res, "B"), "row6")
        self.assertIn(fm.classify(res, "B"), fm.SPAWN_PERMITTED)

    def test_updated_at_ordering_breaks_I1(self):
        """The r4 ordering key. Not a hypothetical: KL2 already concedes clock
        skew is reachable, and this is the sequence it makes reachable."""
        with self.assertRaises(AssertionError):
            check_I1(self, CLOCK_SKEW, order_mode="updated_at")
        self.assertEqual(mergers(CLOCK_SKEW, order_mode="updated_at"), {"A", "B"})
        # NO generated sweep here, deliberately - unlike every sibling mutation
        # test. Measured incidence of an I1 red under order_mode="updated_at" on
        # generated logs: 10 / 9600 (0.104%), and 6 of 12 seed offsets yield
        # ZERO. An assertion of `red > 0` over an 800-log sweep would therefore
        # pass or fail on the seed - a flaky invariant test, which is worse than
        # none. The generated half of the ordering claim is carried by the
        # mutation-table row instead (flip the ORDER_MODE constant and re-run the
        # whole suite), not by a per-log assertion here. See plan.md's ordering
        # paragraph, which states this rarity rather than claiming this test
        # covers generated logs.

    def test_removing_owner_test_breaks_I2(self):
        """I2 had NO mutation test through r5 - AC22's claim that weakening any
        of I1-I4 turns `TestMutationsGoRed` red was false for I2 specifically.
        `owner_test=False` lets a non-owner's `done` be honored beside the
        owner's build fields, which is precisely a fictitious record."""
        rng = random.Random(SEED + 11)
        red = 0
        for _ in range(200):
            log = run_schedule(rng, 3)
            try:
                check_I2(self, log, owner_test=False)
            except AssertionError:
                red += 1
        self.assertGreater(red, 0, "owner_test mutation was never caught by I2")

    def test_updated_at_from_group_latest_breaks_I5(self):
        """The rejected reading of Major-1: freshness taken from the latest
        record in the GROUP rather than the latest record of the OWNER. A
        foreign stray then refreshes the incumbent and row 7 pins forever."""
        log = R4_MAJOR_1  # A owns, in_progress ua=2; B's stray pending ua=3
        res = fm.fold(log)[TASK]
        self.assertEqual((res.session_id, res.updated_at), ("A", 2))
        group_latest = max(r["updated_at"] for r in log)
        self.assertEqual(group_latest, 3)
        self.assertNotEqual(res.updated_at, group_latest)
        self.assertEqual(fm.fold(log, freshness_mode="group")[TASK].updated_at, 3)
        with self.assertRaises(AssertionError):
            check_I5(self, log, freshness_mode="group")

    def test_whitelist_drift_breaks_I2(self):
        """AC23's own failure mode, as a MUTATION on generated logs.

        Added in r5-round-3. Through round 2 the plan called I2's build-field
        half "the one assertion no mutation switch reaches" and rested it
        entirely on a spliced `FoldResult`. That was true of the four switches
        that existed, not of the specification: adding `branch_name` to
        `CROSS_GENERATION_WHITELIST` is a plausible one-token edit to a real
        constant - precisely what AC23's whitelist-not-blacklist rule exists to
        prevent - and it makes a superseded generation's `branch_name` survive
        beside the current owner's `done`. That is a folded record describing a
        build that did not happen (OR6), and I2's build-field half catches it
        WITHOUT any injection."""
        # The named case first: A owns and is `done`; B's post-terminal claim
        # carries `B/b`. Under drift the folded `branch_name` is B's.
        drifted = fm.fold(R3_MAJOR_1, whitelist_mode="drift")[TASK]
        self.assertEqual((drifted.session_id, drifted.status), ("A", "done"))
        self.assertEqual(drifted.fields["branch_name"], "B/b")
        self.assertEqual(fm.fold(R3_MAJOR_1)[TASK].fields["branch_name"], "A/b")
        with self.assertRaises(AssertionError):
            check_I2(self, R3_MAJOR_1, res=drifted)
        # ...and on generated logs.
        rng = random.Random(SEED + 23)
        red = 0
        for _ in range(200):
            log = run_schedule(rng, 3)
            try:
                check_I2(self, log, whitelist_mode="drift")
            except AssertionError:
                red += 1
        self.assertGreater(red, 0,
                           "whitelist drift was never caught by I2's "
                           "build-field half")

    def test_I2_build_field_check_can_fail(self):
        """The build-field half of I2, proved able to fail.

        Measured over 200 logs x 3 generator shapes x all four other mutation
        switches: **0 reds** from this half - every red credited to I2 comes
        from the `done_by` assertion. That is not a correctness gap (the
        generation-purity lemma says a fold cannot produce such a record) but
        an assertion no evidence shows able to fire is exactly what r5-round-2
        Minor-1 flagged in its predecessor. A spliced record is therefore
        injected directly: a `commit_sha` in the folded record that its owner
        never appended, and an owner-appended `branch_name` the fold dropped.
        Both must be caught."""
        res = fm.fold(R3_MAJOR_1)[TASK]
        self.assertEqual((res.session_id, res.status), ("A", "done"))
        check_I2(self, R3_MAJOR_1, res=res)  # clean before splicing

        spliced = fm.fold(R3_MAJOR_1)[TASK]
        spliced.fields["commit_sha"] = "b1"  # B's, beside A's done
        spliced.raw = [r for r in spliced.raw
                       if not (r.get("session_id") == "A" and "commit_sha" in r)]
        with self.assertRaises(AssertionError):
            check_I2(self, R3_MAJOR_1, res=spliced)

        dropped = fm.fold(R3_MAJOR_1)[TASK]
        del dropped.fields["commit_sha"]  # owner appended it; fold lost it
        with self.assertRaises(AssertionError):
            check_I2(self, R3_MAJOR_1, res=dropped)

        stale = fm.fold(R3_MAJOR_1)[TASK]
        stale.fields["branch_name"] = "A/older"  # not the owner's LATEST
        with self.assertRaises(AssertionError):
            check_I2(self, R3_MAJOR_1, res=stale)

    def test_legacy_drop_mode_discards_the_group(self):
        """`LEGACY_MODE = 'drop'` is the r5 model verbatim: a record with no
        `session_id` is discarded by `fold` and raises in `fold_group`, so the
        group folds to nothing, the reader takes the no-task-state path, and
        rows 9/16 are unreachable for every pre-fix project."""
        self.assertEqual(fm.fold(LEGACY_ONLY, legacy_mode="drop"), {})
        with self.assertRaises(KeyError):
            fm.fold_group(LEGACY_ONLY, legacy_mode="drop")
        with self.assertRaises(AssertionError):
            check_legacy(self, LEGACY_ONLY, legacy_mode="drop")
        # And on generated logs, not just the named case. Legacy-ONLY
        # schedules deliberately: a mixed log still folds to a modern owner
        # under `drop`, so the discarded records leave no trace for the check
        # to catch - which is exactly why r5's defect was invisible in a repo
        # whose logs are mostly modern.
        rng = random.Random(SEED + 13)
        red = 0
        for _ in range(200):
            log = run_schedule(rng, 0, n_legacy=2)
            try:
                check_legacy(self, log, legacy_mode="drop")
            except AssertionError:
                red += 1
        self.assertGreater(red, 0, "legacy_mode mutation was never caught")

    def test_mutations_are_detected_on_generated_logs_too(self):
        rng = random.Random(SEED + 7)
        red = 0
        for _ in range(200):
            log = run_schedule(rng, 3)
            try:
                check_I4(self, log, owner_test=False)
            except AssertionError:
                red += 1
        self.assertGreater(red, 0, "owner_test mutation was never caught on generated logs")


class TestZReport(unittest.TestCase):
    def test_zz_report_coverage(self):
        print("\ninterleavings exercised: schedules=%(schedules)d "
              "I1=%(I1)d I2=%(I2)d I3=%(I3)d I4=%(I4)d I5=%(I5)d "
              "prefix_folds=%(prefix_folds)d reclaim_logs=%(reclaim_logs)d "
              "reclaim_honored=%(reclaim_honored)d "
              "legacy_groups=%(legacy_groups)d legacy_rows=%(legacy_rows)d\n"
              "non-vacuity over %(tally_logs)d size-sweep logs: "
              "multi_owner=%(multi_owner)d "
              "claim_rejected_post_terminal=%(claim_rejected_post_terminal)d "
              "transition_rejected_unowned=%(transition_rejected_unowned)d\n"
              "status census over the same 800 logs: pending=%(st_pending)d "
              "in_progress=%(st_in_progress)d failed=%(st_failed)d "
              "done=%(st_done)d no-status=%(st_none)d; "
              "folded_terminal_non_done=%(folded_terminal_non_done)d"
              % COVERAGE)
        self.assertGreater(COVERAGE["schedules"], 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
