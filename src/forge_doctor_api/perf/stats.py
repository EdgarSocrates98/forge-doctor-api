"""Robust statistics (§89): median, MAD, percentiles.

All helpers are pure + deterministic. `MIN_SAMPLES` is the minimum
sample size before any regression claim may fire - thin samples stay
UNKNOWN instead of producing findings (§190 honesty).
"""

from __future__ import annotations

from dataclasses import dataclass
from math import floor

MIN_SAMPLES = 8


def _sorted(xs: list[float]) -> list[float]:
    return sorted(xs)


def percentile(xs: list[float], p: float) -> float | None:
    """Linear-interpolation percentile; None on empty input."""
    if not xs:
        return None
    s = _sorted(xs)
    if len(s) == 1:
        return s[0]
    rank = (p / 100.0) * (len(s) - 1)
    lo, hi = floor(rank), floor(rank) + 1
    if hi >= len(s):
        return s[-1]
    return s[lo] + (s[hi] - s[lo]) * (rank - lo)


def median(xs: list[float]) -> float | None:
    return percentile(xs, 50)


def mad(xs: list[float]) -> float | None:
    """Median absolute deviation from the median."""
    med = median(xs)
    if med is None:
        return None
    return median([abs(x - med) for x in xs])


@dataclass(frozen=True, kw_only=True)
class RobustStats:
    """§89 robust summary over one sample set."""

    count: int
    p50: float
    p90: float
    p95: float
    p99: float
    mad: float
    mean: float


def robust_stats(xs: list[float]) -> RobustStats | None:
    if not xs:
        return None
    return RobustStats(
        count=len(xs),
        p50=percentile(xs, 50) or 0.0,
        p90=percentile(xs, 90) or 0.0,
        p95=percentile(xs, 95) or 0.0,
        p99=percentile(xs, 99) or 0.0,
        mad=mad(xs) or 0.0,
        mean=sum(xs) / len(xs),
    )
