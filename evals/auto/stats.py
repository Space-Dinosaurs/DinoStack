"""
Purpose: Statistical core for the auto-harness keep gate. Computes paired
         per-fixture deltas and decides keep/revert via a one-sided exact
         conditional sign-flip permutation test gated on significance,
         minimum mean effect, and minimum evidence.

Public API:
    pair_deltas(baseline_rows, post_rows, *, key="fixture_id") -> list[float]
    signflip_test(deltas) -> dict
    keep_decision(deltas, *, alpha, epsilon, min_nonzero_pairs) -> dict

    Constants: MIN_NONZERO_PAIRS, ALPHA, EPSILON, EXACT_MAX

Upstream deps: stdlib only - itertools, math, fractions, statistics.

Downstream consumers: evals.auto.loop.

Failure modes: never raises on empty or degenerate input. keep_decision returns
               keep=False with a descriptive reason string. signflip_test returns
               p_value=None when k==0 (no nonzero pairs). The exact enumeration
               path is bounded at k<=EXACT_MAX (22) which enumerates at most 2^22
               = 4,194,304 sign assignments; above that the normal approximation
               is used.

Performance: exact path - enumerates all 2^k sign assignments over |delta|
             magnitudes, bounded by k<=22 => <=4.2M iterations, sub-second on
             typical hardware. Normal approx path is O(k) arithmetic above that
             threshold.
"""
from __future__ import annotations

import fractions
import itertools
import math
import statistics
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

MIN_NONZERO_PAIRS: int = 5
"""Minimum number of nonzero pairs required for the keep gate.

5 is the minimum number of nonzero pairs at which the one-sided sign-flip test
can reach p<=0.05: k=5 with all deltas the same sign gives p=1/2^5=0.03125
which is <=0.05. k=4 gives 1/16=0.0625, which cannot reach the threshold
regardless of the data.
"""

ALPHA: float = 0.05
"""One-sided significance threshold for the sign-flip permutation test."""

EPSILON: float = 0.02
"""Minimum mean delta (effect floor) required to keep an edit."""

EXACT_MAX: int = 22
"""Maximum k (nonzero pairs) for exact enumeration. Above this the normal
approximation is used. 2^22 = 4,194,304 sign assignments."""


# ---------------------------------------------------------------------------
# pair_deltas
# ---------------------------------------------------------------------------

def pair_deltas(
    baseline_rows: list[dict[str, Any]],
    post_rows: list[dict[str, Any]],
    *,
    key: str = "fixture_id",
) -> list[float]:
    """Pair baseline and post rows by a stable key and return per-fixture deltas.

    For each fixture present in BOTH sides, delta = float(post[primary_score_median])
    - float(base[primary_score_median]). Fixtures present on only one side are
    silently dropped (the caller is responsible for logging dropped fixtures).

    Deltas are returned in baseline iteration order (stable).

    Positional fallback: when ``key`` is absent from EVERY row on either side
    (legacy 9-column rows that predate the fixture_id column), rows are paired
    by index, producing min(len(baseline_rows), len(post_rows)) pairs. This
    preserves backward compatibility with older result TSVs.

    Args:
        baseline_rows: list of dicts, each with at least ``key`` and
                       ``primary_score_median``.
        post_rows: list of dicts, each with at least ``key`` and
                   ``primary_score_median``.
        key: column name used to pair rows (default ``fixture_id``).

    Returns:
        List of float deltas (post - base), in baseline order.
    """
    # Detect positional fallback: key absent from every row on either side.
    base_has_key = any(key in row for row in baseline_rows)
    post_has_key = any(key in row for row in post_rows)

    if not base_has_key or not post_has_key:
        # Legacy positional pairing.
        n = min(len(baseline_rows), len(post_rows))
        return [
            float(post_rows[i]["primary_score_median"])
            - float(baseline_rows[i]["primary_score_median"])
            for i in range(n)
        ]

    # Key-based pairing: build lookup from post rows.
    post_by_key: dict[str, dict[str, Any]] = {
        row[key]: row for row in post_rows if key in row
    }

    deltas: list[float] = []
    for base_row in baseline_rows:
        if key not in base_row:
            continue
        fid = base_row[key]
        if fid not in post_by_key:
            continue
        post_row = post_by_key[fid]
        deltas.append(
            float(post_row["primary_score_median"])
            - float(base_row["primary_score_median"])
        )
    return deltas


# ---------------------------------------------------------------------------
# signflip_test
# ---------------------------------------------------------------------------

def signflip_test(deltas: list[float]) -> dict[str, Any]:
    """One-sided exact conditional sign-flip permutation test for H1: improvement.

    The null hypothesis is that the sign of each nonzero delta is equally likely
    to be positive or negative (conditional on the observed magnitudes). The
    test statistic W is the sum of the deltas assigned positive sign. Under the
    null, each of the 2^k sign assignments over the k nonzero magnitudes is
    equally probable. p-value = P(W >= W_obs | magnitudes).

    This is the exact conditional permutation null given the observed |delta|
    multiset. It is tie-robust by construction because it conditions on
    magnitudes rather than ranks - ties in magnitude simply produce the same
    contribution under multiple assignments. It is NOT the textbook Wilcoxon
    signed-rank distribution (which assigns ranks to magnitudes); the statistic
    here is the raw sum of positively-signed magnitudes.

    Zeros are retained in the input list for bookkeeping (n_nonzero counts them
    correctly) but contribute 0 to W under every sign assignment, so they are
    excluded from the enumeration.

    Exact path (k <= EXACT_MAX): enumerates all 2^k sign assignments using
    fractions.Fraction for the count ratio to avoid floating-point rounding,
    then converts to float.

    Normal approximation path (k > EXACT_MAX): uses E[W] = 0.5 * sum(mags),
    Var[W] = 0.25 * sum(m^2 for m in mags), with a 0.5 continuity correction:
    z = (w_obs - E[W] - 0.5) / sqrt(Var), p = 0.5 * erfc(z / sqrt(2)).

    Args:
        deltas: list of float deltas (may include zeros).

    Returns:
        dict with keys:
            p_value   - float or None (None when k==0)
            w_obs     - float, sum of positive deltas
            n_nonzero - int, number of nonzero deltas
            method    - str: "undefined" | "exact" | "normal_approx"
    """
    nz = [d for d in deltas if d != 0.0]
    k = len(nz)
    w_obs = sum(d for d in nz if d > 0)

    if k == 0:
        return {"p_value": None, "w_obs": 0.0, "n_nonzero": 0, "method": "undefined"}

    mags = [abs(d) for d in nz]

    if k <= EXACT_MAX:
        # Exact enumeration over all 2^k sign assignments.
        count_ge = fractions.Fraction(0)
        total = fractions.Fraction(2 ** k)
        for bits in itertools.product((0, 1), repeat=k):
            w = sum(mags[i] for i in range(k) if bits[i] == 1)
            if w >= w_obs:
                count_ge += 1
        p_value = float(count_ge / total)
        return {
            "p_value": p_value,
            "w_obs": float(w_obs),
            "n_nonzero": k,
            "method": "exact",
        }
    else:
        # Normal approximation with continuity correction.
        e_w = 0.5 * sum(mags)
        var_w = 0.25 * sum(m * m for m in mags)
        sqrt_var = math.sqrt(var_w) if var_w > 0 else 0.0
        if sqrt_var == 0.0:
            # All magnitudes zero after floating-point - degenerate.
            p_value = 1.0
        else:
            z = (w_obs - e_w - 0.5) / sqrt_var
            p_value = 0.5 * math.erfc(z / math.sqrt(2))
        return {
            "p_value": p_value,
            "w_obs": float(w_obs),
            "n_nonzero": k,
            "method": "normal_approx",
        }


# ---------------------------------------------------------------------------
# keep_decision
# ---------------------------------------------------------------------------

def keep_decision(
    deltas: list[float],
    *,
    alpha: float = ALPHA,
    epsilon: float = EPSILON,
    min_nonzero_pairs: int = MIN_NONZERO_PAIRS,
) -> dict[str, Any]:
    """Decide whether to keep a proposed edit based on paired per-fixture deltas.

    Applies three gates in order:
    1. n_nonzero >= min_nonzero_pairs  (minimum evidence)
    2. p_value <= alpha                (one-sided significance via signflip_test)
    3. effect_mean_delta >= epsilon    (minimum mean effect)

    All three must hold for keep=True. The reason string names the first failing
    clause, or summarises the passed values on keep=True.

    Note: ``effect_mean_delta`` holds the MEAN of ALL deltas (including zeros).
    The ledger column has the same name.

    Args:
        deltas: list of float deltas (may include zeros).
        alpha: significance threshold (default ALPHA=0.05).
        epsilon: minimum mean effect (default EPSILON=0.02).
        min_nonzero_pairs: minimum nonzero pair count (default MIN_NONZERO_PAIRS=5).

    Returns:
        dict with keys:
            keep              - bool
            p_value           - float or None
            effect_mean_delta - float (mean of ALL deltas including zeros)
            n_nonzero         - int
            method            - str
            reason            - str
    """
    n_nonzero = sum(1 for d in deltas if d != 0.0)
    effect = statistics.mean(deltas) if deltas else 0.0

    result = signflip_test(deltas)
    p_value: float | None = result["p_value"]
    method: str = result["method"]

    if n_nonzero < min_nonzero_pairs:
        reason = f"n_nonzero={n_nonzero}<{min_nonzero_pairs}"
        keep = False
    elif p_value is None or p_value > alpha:
        p_str = "None" if p_value is None else f"{p_value:.4g}"
        reason = f"p={p_str}>{alpha}"
        keep = False
    elif effect < epsilon:
        reason = f"effect={effect:.4g}<{epsilon}"
        keep = False
    else:
        reason = f"kept: p={p_value:.4g},effect={effect:.4g},n_nonzero={n_nonzero}"
        keep = True

    return {
        "keep": keep,
        "p_value": p_value,
        "effect_mean_delta": effect,
        "n_nonzero": n_nonzero,
        "method": method,
        "reason": reason,
    }
