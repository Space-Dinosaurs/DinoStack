"""
Tests for evals/skill-comparison/aggregate.py.

Coverage:
- N-condition rollup (>2 conditions in one pass)
- Delta-vs-baseline math for all 7 non-baseline conditions
- Envelope derived from baseline-vs-baseline stdev (n=5 replicates)
- Missing cells (None/NaN) handled without crash
- Canonical condition ordering
- rows_to_tsv smoke check
"""
from __future__ import annotations

import math
import statistics
from typing import Optional

import pytest

# conftest.py inserts the skill-comparison/ dir into sys.path.
from aggregate import (
    CANONICAL_CONDITION_ORDER,
    ConditionRow,
    aggregate_conditions,
    rows_to_tsv,
)

# ---------------------------------------------------------------------------
# Fixtures / hand-computed reference data
# ---------------------------------------------------------------------------

# Baseline replicates: 5 runs, hand-picked for simple arithmetic.
# median([0.6, 0.6, 0.8, 0.8, 1.0]) = 0.8
# stdev([0.6, 0.6, 0.8, 0.8, 1.0]) = stdev with N-1 divisor
_BASELINE_SCORES: list[float] = [0.6, 0.6, 0.8, 0.8, 1.0]
_BASELINE_MEDIAN: float = statistics.median(_BASELINE_SCORES)
_BASELINE_STDEV: float = statistics.stdev(_BASELINE_SCORES)

# Per-condition scores, n=3 each. Hand-computed expected medians.
# ae-rules-injected: [0.8, 1.0, 1.0] -> median=1.0
# engineer-direct:   [0.6, 0.8, 1.0] -> median=0.8
# architect-direct:  [0.4, 0.6, 0.8] -> median=0.6
# investigator-direct: [0.0, 0.4, 0.4] -> median=0.4
# debugger-direct:   [1.0, 1.0, 1.0] -> median=1.0
# skeptic-direct:    [0.0, 0.0, 0.2] -> median=0.0
# qa-engineer-direct: [0.6, 0.6, 1.0] -> median=0.6

_ALL_RUNS: dict[str, list[Optional[float]]] = {
    "baseline": _BASELINE_SCORES,
    "ae-rules-injected": [0.8, 1.0, 1.0],
    "engineer-direct": [0.6, 0.8, 1.0],
    "architect-direct": [0.4, 0.6, 0.8],
    "investigator-direct": [0.0, 0.4, 0.4],
    "debugger-direct": [1.0, 1.0, 1.0],
    "skeptic-direct": [0.0, 0.0, 0.2],
    "qa-engineer-direct": [0.6, 0.6, 1.0],
}

# Expected medians (hand-computed).
_EXPECTED_MEDIANS: dict[str, float] = {
    "baseline": 0.8,
    "ae-rules-injected": 1.0,
    "engineer-direct": 0.8,
    "architect-direct": 0.6,
    "investigator-direct": 0.4,
    "debugger-direct": 1.0,
    "skeptic-direct": 0.0,
    "qa-engineer-direct": 0.6,
}


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------


def _row(rows: list[ConditionRow], condition: str) -> ConditionRow:
    for r in rows:
        if r.condition == condition:
            return r
    raise KeyError(f"condition {condition!r} not found in rows")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestNConditionRollup:
    """aggregate_conditions processes N conditions in a single pass."""

    def test_returns_one_row_per_condition(self) -> None:
        rows = aggregate_conditions(_ALL_RUNS)
        assert len(rows) == len(_ALL_RUNS)

    def test_all_8_conditions_present(self) -> None:
        rows = aggregate_conditions(_ALL_RUNS)
        names = {r.condition for r in rows}
        assert names == set(_ALL_RUNS.keys())

    def test_canonical_ordering_respected(self) -> None:
        rows = aggregate_conditions(_ALL_RUNS)
        names = [r.condition for r in rows]
        # First 8 entries must match CANONICAL_CONDITION_ORDER (all are present).
        assert names == CANONICAL_CONDITION_ORDER

    def test_n_counts_are_correct(self) -> None:
        rows = aggregate_conditions(_ALL_RUNS)
        for r in rows:
            expected_n = len(_ALL_RUNS[r.condition])
            assert r.n == expected_n, f"n mismatch for {r.condition}"


class TestMedianMath:
    """Median values match hand-computed expectations."""

    def test_baseline_median(self) -> None:
        rows = aggregate_conditions(_ALL_RUNS)
        row = _row(rows, "baseline")
        assert row.median == pytest.approx(_BASELINE_MEDIAN, abs=1e-6)

    @pytest.mark.parametrize(
        "condition,expected",
        [
            ("ae-rules-injected", 1.0),
            ("engineer-direct", 0.8),
            ("architect-direct", 0.6),
            ("investigator-direct", 0.4),
            ("debugger-direct", 1.0),
            ("skeptic-direct", 0.0),
            ("qa-engineer-direct", 0.6),
        ],
    )
    def test_non_baseline_medians(self, condition: str, expected: float) -> None:
        rows = aggregate_conditions(_ALL_RUNS)
        row = _row(rows, condition)
        assert row.median == pytest.approx(expected, abs=1e-6), (
            f"median mismatch for {condition}: got {row.median}, expected {expected}"
        )


class TestDeltaVsBaseline:
    """Delta-vs-baseline math for all 7 non-baseline conditions."""

    def test_baseline_has_no_delta(self) -> None:
        rows = aggregate_conditions(_ALL_RUNS)
        row = _row(rows, "baseline")
        assert row.delta_vs_baseline is None

    @pytest.mark.parametrize(
        "condition",
        [
            "ae-rules-injected",
            "engineer-direct",
            "architect-direct",
            "investigator-direct",
            "debugger-direct",
            "skeptic-direct",
            "qa-engineer-direct",
        ],
    )
    def test_delta_equals_median_minus_baseline(self, condition: str) -> None:
        rows = aggregate_conditions(_ALL_RUNS)
        baseline_row = _row(rows, "baseline")
        cond_row = _row(rows, condition)
        expected_delta = _EXPECTED_MEDIANS[condition] - _EXPECTED_MEDIANS["baseline"]
        assert cond_row.delta_vs_baseline == pytest.approx(expected_delta, abs=1e-6), (
            f"delta mismatch for {condition}: "
            f"got {cond_row.delta_vs_baseline}, expected {expected_delta}"
        )

    def test_all_7_non_baseline_conditions_have_delta(self) -> None:
        rows = aggregate_conditions(_ALL_RUNS)
        non_baseline = [r for r in rows if r.condition != "baseline"]
        assert len(non_baseline) == 7
        for r in non_baseline:
            assert r.delta_vs_baseline is not None, (
                f"expected delta for {r.condition} but got None"
            )


class TestEnvelopeFromBaselineStdev:
    """Envelope column derived from baseline-vs-baseline replicate stdev."""

    def test_baseline_row_has_envelope(self) -> None:
        rows = aggregate_conditions(_ALL_RUNS)
        row = _row(rows, "baseline")
        assert row.envelope is not None

    def test_envelope_equals_baseline_stdev(self) -> None:
        rows = aggregate_conditions(_ALL_RUNS)
        row = _row(rows, "baseline")
        assert row.envelope == pytest.approx(_BASELINE_STDEV, abs=1e-6), (
            f"envelope mismatch: got {row.envelope}, expected {_BASELINE_STDEV}"
        )

    def test_non_baseline_rows_have_no_envelope(self) -> None:
        rows = aggregate_conditions(_ALL_RUNS)
        for r in rows:
            if r.condition != "baseline":
                assert r.envelope is None, (
                    f"expected envelope=None for {r.condition}, got {r.envelope}"
                )

    def test_envelope_n5_produces_real_stdev(self) -> None:
        """n=5 baseline replicates must yield a real (non-zero, non-None) stdev."""
        # Scores have variance so stdev must be > 0.
        runs = {"baseline": [0.6, 0.6, 0.8, 0.8, 1.0]}
        rows = aggregate_conditions(runs)
        row = _row(rows, "baseline")
        assert row.envelope is not None
        assert row.envelope > 0.0

    def test_envelope_n1_baseline_is_none(self) -> None:
        """With only 1 baseline run, stdev is undefined; envelope must be None."""
        runs = {"baseline": [0.8], "engineer-direct": [0.6, 0.8, 1.0]}
        rows = aggregate_conditions(runs)
        baseline_row = _row(rows, "baseline")
        assert baseline_row.envelope is None


class TestMissingCells:
    """None/NaN entries are handled without crash; n reflects valid-only count."""

    def test_all_none_cell_does_not_crash(self) -> None:
        runs = {
            "baseline": [0.6, 0.8, 1.0],
            "engineer-direct": [None, None, None],
        }
        rows = aggregate_conditions(runs)
        row = _row(rows, "engineer-direct")
        assert row.median is None
        assert row.stdev is None
        assert row.n == 0

    def test_partial_none_cell_uses_valid_scores(self) -> None:
        runs = {
            "baseline": [0.6, 0.8, 1.0],
            "engineer-direct": [None, 0.6, 1.0],
        }
        rows = aggregate_conditions(runs)
        row = _row(rows, "engineer-direct")
        # Valid scores: [0.6, 1.0]; median = 0.8
        assert row.n == 2
        assert row.median == pytest.approx(0.8, abs=1e-6)

    def test_nan_scores_excluded(self) -> None:
        runs = {
            "baseline": [0.6, 0.8, 1.0],
            "engineer-direct": [float("nan"), 0.8, 1.0],
        }
        rows = aggregate_conditions(runs)
        row = _row(rows, "engineer-direct")
        assert row.n == 2
        assert row.median == pytest.approx(0.9, abs=1e-6)

    def test_delta_none_when_condition_missing(self) -> None:
        """Delta is None when condition cell is all-None (no valid scores)."""
        runs = {
            "baseline": [0.6, 0.8, 1.0],
            "engineer-direct": [None, None, None],
        }
        rows = aggregate_conditions(runs)
        row = _row(rows, "engineer-direct")
        assert row.delta_vs_baseline is None

    def test_delta_none_when_baseline_missing(self) -> None:
        """Delta is None when baseline itself has no valid scores."""
        runs = {
            "baseline": [None, None],
            "engineer-direct": [0.6, 0.8, 1.0],
        }
        rows = aggregate_conditions(runs)
        row = _row(rows, "engineer-direct")
        assert row.delta_vs_baseline is None

    def test_empty_runs_dict_returns_empty_list(self) -> None:
        rows = aggregate_conditions({})
        assert rows == []

    def test_single_condition_no_delta(self) -> None:
        """Only baseline present: delta=None (it IS the baseline)."""
        runs = {"baseline": [0.6, 0.8, 1.0]}
        rows = aggregate_conditions(runs)
        assert len(rows) == 1
        assert rows[0].delta_vs_baseline is None


class TestNonDefaultBaselineKey:
    """Caller can nominate a different condition as the baseline."""

    def test_custom_baseline_key(self) -> None:
        runs = {
            "control": [0.6, 0.8, 1.0],
            "treatment": [0.8, 1.0, 1.0],
        }
        rows = aggregate_conditions(runs, baseline_key="control")
        control_row = next(r for r in rows if r.condition == "control")
        treatment_row = next(r for r in rows if r.condition == "treatment")
        assert control_row.delta_vs_baseline is None
        assert control_row.envelope is not None
        assert treatment_row.delta_vs_baseline is not None


class TestRowsToTsv:
    """rows_to_tsv renders valid TSV."""

    def test_header_and_rows_count(self) -> None:
        rows = aggregate_conditions(_ALL_RUNS)
        tsv = rows_to_tsv(rows)
        lines = tsv.strip().split("\n")
        # 1 header + 8 data rows
        assert len(lines) == 9

    def test_header_contains_expected_columns(self) -> None:
        rows = aggregate_conditions(_ALL_RUNS)
        tsv = rows_to_tsv(rows)
        header = tsv.split("\n")[0]
        for col in ["condition", "n", "median", "stdev", "delta_vs_baseline", "envelope"]:
            assert col in header

    def test_task_id_column_when_provided(self) -> None:
        rows = aggregate_conditions({"baseline": [0.8]})
        tsv = rows_to_tsv(rows, task_id="task-001")
        header_cols = tsv.split("\n")[0].split("\t")
        assert header_cols[0] == "task_id"
        data_row = tsv.split("\n")[1].split("\t")
        assert data_row[0] == "task-001"

    def test_missing_median_renders_as_empty_string(self) -> None:
        rows = aggregate_conditions({"baseline": [None, None]})
        tsv = rows_to_tsv(rows)
        data_line = tsv.split("\n")[1]
        cols = data_line.split("\t")
        # median column (index 2) should be empty string
        assert cols[2] == ""
