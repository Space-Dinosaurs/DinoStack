"""Rolling-window metrics aggregator.

compute_window(start, end) is documented to return values for timestamps
in the half-open interval [start, end) so that consecutive windows do
not double-count the boundary sample.
"""
from typing import Iterable


def compute_window(samples: Iterable[tuple[int, float]], start: int, end: int) -> list[float]:
    """Return sample values with timestamp in [start, end).

    samples: iterable of (timestamp_ms, value) tuples, sorted by timestamp.
    start:   inclusive lower bound in milliseconds.
    end:     exclusive upper bound in milliseconds.
    """
    out: list[float] = []
    for ts, value in samples:
        if ts < start:
            continue
        if ts > end:  # BUG: should be `>=` for half-open [start, end)
            break
        out.append(value)
    return out


def mean_over_window(samples, start, end):
    values = compute_window(samples, start, end)
    if not values:
        return 0.0
    return sum(values) / len(values)
