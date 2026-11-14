"""Sheet utilization and bounding-envelope metric calculations for nesting."""

from __future__ import annotations

from ..validators import _r4
from .models import NestingMetrics, PlacementDecision


def compute_nesting_metrics(
    usable_w: float,
    usable_h: float,
    decisions: list[PlacementDecision],
) -> NestingMetrics:
    """Calculate usable area, bbox occupancy, true polygon occupancy, and bounding envelope."""
    usable_area = max(usable_w * usable_h, 1e-6)
    occupied_bbox_area = sum(d.width_mm * d.height_mm for d in decisions)
    occupied_shape_area = sum(d.shape_area_mm2 for d in decisions)

    envelope: tuple[float, float, float, float] | None = None
    if decisions:
        raw_env = (
            min(d.bbox_mm[0] for d in decisions),
            min(d.bbox_mm[1] for d in decisions),
            max(d.bbox_mm[2] for d in decisions),
            max(d.bbox_mm[3] for d in decisions),
        )
        envelope = _r4(raw_env)

    return NestingMetrics(
        usable_sheet_width_mm=usable_w,
        usable_sheet_height_mm=usable_h,
        usable_area_mm2=round(usable_area, 2),
        occupied_bbox_area_mm2=round(occupied_bbox_area, 2),
        occupied_shape_area_mm2=round(occupied_shape_area, 2),
        bounding_envelope_mm=envelope,
        utilization_pct=round((occupied_bbox_area / usable_area) * 100.0, 2),
        true_area_utilization_pct=round((occupied_shape_area / usable_area) * 100.0, 2),
    )

