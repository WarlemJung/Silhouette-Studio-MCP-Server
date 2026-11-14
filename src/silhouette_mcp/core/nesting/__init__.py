"""2D sheet nesting domain package (MaxRects BSSF+BAF, collisions, regmarks, metrics)."""

from .collision import (
    boxes_overlap,
    compute_regmark_obstacles,
    compute_unselected_obstacles,
    min_clearance_between_boxes,
    resolve_composite_groups,
    validate_placements_in_bounds,
)
from .maxrects import (
    _maxrects_subtract,
    apply_placement_to_shape,
    build_candidates,
    build_composite_candidates,
    extract_root_decisions,
    generate_rotation_angles,
    pack_candidates_maxrects,
)
from .metrics import compute_nesting_metrics
from .models import NestingCandidate, NestingConfig, NestingMetrics, PlacementDecision

__all__ = [
    "NestingCandidate",
    "NestingConfig",
    "NestingMetrics",
    "PlacementDecision",
    "_maxrects_subtract",
    "apply_placement_to_shape",
    "boxes_overlap",
    "build_candidates",
    "build_composite_candidates",
    "compute_nesting_metrics",
    "compute_regmark_obstacles",
    "compute_unselected_obstacles",
    "extract_root_decisions",
    "generate_rotation_angles",
    "min_clearance_between_boxes",
    "pack_candidates_maxrects",
    "resolve_composite_groups",
    "validate_placements_in_bounds",
]

