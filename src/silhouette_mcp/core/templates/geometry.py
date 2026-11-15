"""Pure 2D curve primitives used by parametric packaging dielines."""

from __future__ import annotations

import math

from ..geometry_engine import _eval_cubic


def _milk_arch_pts(x0: float, y_peak: float, y_valley: float, width: float) -> list[tuple[float, float]]:
    """Evaluate the symmetric four-segment cubic Bezier crown arch for luxury milk boxes."""
    w = width
    dy = y_valley - y_peak
    pts: list[tuple[float, float]] = [(x0, y_valley)]
    pts += _eval_cubic(
        (x0, y_valley),
        (x0 + w * 0.08, y_valley - dy * 0.6),
        (x0 + w * 0.18, y_valley - dy * 0.6),
        (x0 + w * 0.25, y_valley - dy * 0.29),
        8,
    )
    pts += _eval_cubic(
        (x0 + w * 0.25, y_valley - dy * 0.29),
        (x0 + w * 0.33, y_peak + dy * 0.04),
        (x0 + w * 0.40, y_peak),
        (x0 + w * 0.50, y_peak),
        10,
    )
    pts += _eval_cubic(
        (x0 + w * 0.50, y_peak),
        (x0 + w * 0.60, y_peak),
        (x0 + w * 0.67, y_peak + dy * 0.04),
        (x0 + w * 0.75, y_valley - dy * 0.29),
        10,
    )
    pts += _eval_cubic(
        (x0 + w * 0.75, y_valley - dy * 0.29),
        (x0 + w * 0.82, y_valley - dy * 0.6),
        (x0 + w * 0.92, y_valley - dy * 0.6),
        (x0 + w, y_valley),
        8,
    )
    return pts


def _bow_arc(
    xa: float,
    xb: float,
    y_base: float,
    dy: float,
    n: int = 16,
) -> list[tuple[float, float]]:
    """Sample a sinusoidal bow arc between (xa, y_base) and (xb, y_base) with sagitta dy."""
    return [
        (xa + (xb - xa) * i / n, y_base + dy * math.sin(math.pi * i / n))
        for i in range(n + 1)
    ]

