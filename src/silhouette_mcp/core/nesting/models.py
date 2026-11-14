"""Domain models for 2D rectangular sheet nesting."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class NestingConfig:
    """Configuration for a 2D sheet nesting run in millimetres."""

    sheet_x0: float
    sheet_y0: float
    sheet_x1: float
    sheet_y1: float
    spacing_mm: float = 3.0
    rotation_step_deg: float = 90.0
    allow_rotation: bool = True
    preserve_regmarks: bool = True
    dry_run: bool = False

    @property
    def usable_width(self) -> float:
        """Usable sheet width in millimetres."""
        return self.sheet_x1 - self.sheet_x0

    @property
    def usable_height(self) -> float:
        """Usable sheet height in millimetres."""
        return self.sheet_y1 - self.sheet_y0

    @property
    def sheet_bounds(self) -> tuple[float, float, float, float]:
        """Usable sheet bounding box `(x0, y0, x1, y1)` in mm."""
        return (self.sheet_x0, self.sheet_y0, self.sheet_x1, self.sheet_y1)


@dataclass(frozen=True, slots=True)
class NestingCandidate:
    """Shape candidate prepared for deterministic 2D packing."""

    shape: dict[str, Any]
    shape_id: int
    label: str
    orig_bbox: tuple[float, float, float, float]
    width_mm: float
    height_mm: float
    bbox_area_mm2: float
    shape_area_mm2: float
    children: tuple[dict[str, Any], ...] = ()


@dataclass(frozen=True, slots=True)
class PlacementDecision:
    """Computed placement for a single shape without mutating the source dict."""

    shape_id: int
    label: str
    kind: str
    placed_x_mm: float
    placed_y_mm: float
    width_mm: float
    height_mm: float
    rotation_deg: float
    orig_rotated_bbox: tuple[float, float, float, float]
    bbox_mm: tuple[float, float, float, float]
    shape_area_mm2: float
    pivot_xy: tuple[float, float] | None = None
    parent_id: int | None = None

    @property
    def dx(self) -> float:
        """Horizontal shift from rotated source bbox to placed target coordinate."""
        return self.placed_x_mm - self.orig_rotated_bbox[0]

    @property
    def dy(self) -> float:
        """Vertical shift from rotated source bbox to placed target coordinate."""
        return self.placed_y_mm - self.orig_rotated_bbox[1]


@dataclass(frozen=True, slots=True)
class NestingMetrics:
    """Sheet utilization and envelope metrics for a completed nesting pass."""

    usable_sheet_width_mm: float
    usable_sheet_height_mm: float
    usable_area_mm2: float
    occupied_bbox_area_mm2: float
    occupied_shape_area_mm2: float
    bounding_envelope_mm: tuple[float, float, float, float] | None
    utilization_pct: float
    true_area_utilization_pct: float

