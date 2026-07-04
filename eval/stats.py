"""Small statistics helpers for reporting rates with honest uncertainty."""

from __future__ import annotations

import math

Z_95 = 1.959963984540054  # z for a two-sided 95% interval


def wilson_upper_bound(successes: int, n: int, z: float = Z_95) -> float:
    """Upper bound of the Wilson score interval for a proportion.

    Works for any observed count, including 0 successes (where a naive interval
    would collapse to zero and overstate confidence). Reporting this turns a bare
    "0%" into an honest "0%, and at 95% confidence no worse than X%".
    """
    if n <= 0:
        return 0.0
    phat = successes / n
    denom = 1.0 + z * z / n
    center = phat + z * z / (2 * n)
    margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return min(1.0, (center + margin) / denom)


def wilson_interval(successes: int, n: int, z: float = Z_95) -> tuple[float, float]:
    """(lower, upper) Wilson score interval for a proportion."""
    if n <= 0:
        return (0.0, 0.0)
    phat = successes / n
    denom = 1.0 + z * z / n
    center = phat + z * z / (2 * n)
    margin = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))
    return (max(0.0, (center - margin) / denom), min(1.0, (center + margin) / denom))
