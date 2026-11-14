"""Pure domain unit tests for `silhouette_mcp.core.nesting`."""

from __future__ import annotations

import math

from silhouette_mcp.core.nesting import (
    NestingConfig,
    _maxrects_subtract,
    apply_placement_to_shape,
    boxes_overlap,
    build_candidates,
    compute_nesting_metrics,
    compute_regmark_obstacles,
    generate_rotation_angles,
    min_clearance_between_boxes,
    pack_candidates_maxrects,
    validate_placements_in_bounds,
)


def test_collision_and_clearance_primitives():
    a = (10.0, 10.0, 30.0, 30.0)
    b = (25.0, 25.0, 45.0, 45.0)
    c = (35.0, 10.0, 50.0, 30.0)
    d = (33.0, 34.0, 40.0, 42.0)

    assert boxes_overlap(a, b) is True
    assert min_clearance_between_boxes(a, b) == 0.0

    # Adjacent/touching at edge is non-overlapping within eps
    touching = (30.0, 10.0, 40.0, 30.0)
    assert boxes_overlap(a, touching) is False

    # Horizontal gap = 5 mm, diagonal gap = hypot(3, 4) = 5 mm
    assert math.isclose(min_clearance_between_boxes(a, c), 5.0, abs_tol=1e-6)
    assert math.isclose(min_clearance_between_boxes(a, d), 5.0, abs_tol=1e-6)


def test_validate_placements_in_bounds():
    bounds = (10.0, 10.0, 110.0, 110.0)
    valid_boxes = [(10.0, 10.0, 30.0, 30.0), (35.0, 10.0, 55.0, 30.0)]
    assert validate_placements_in_bounds(valid_boxes, bounds, spacing_mm=5.0) is True
    assert validate_placements_in_bounds(valid_boxes, bounds, spacing_mm=6.0) is False

    out_of_bounds = [(5.0, 10.0, 30.0, 30.0)]
    assert validate_placements_in_bounds(out_of_bounds, bounds, spacing_mm=0.0) is False

    overlapping = [(10.0, 10.0, 40.0, 40.0), (35.0, 35.0, 55.0, 55.0)]
    assert validate_placements_in_bounds(overlapping, bounds, spacing_mm=0.0) is False


def test_regmark_obstacles_and_config_properties():
    cfg = NestingConfig(sheet_x0=10.0, sheet_y0=10.0, sheet_x1=210.0, sheet_y1=210.0, spacing_mm=2.0)
    assert cfg.usable_width == 200.0
    assert cfg.usable_height == 200.0
    assert cfg.sheet_bounds == (10.0, 10.0, 210.0, 210.0)

    shapes = [
        {"id": 1, "label": "rm1", "layer": "REGMARK", "kind": "poly", "closed": True, "points": [[12, 12], [17, 12], [17, 17], [12, 17]]},
        {"id": 2, "label": "part", "layer": "CUT", "kind": "poly", "closed": True, "points": [[20, 20], [50, 20], [50, 40], [20, 40]]},
    ]
    obstacles, count = compute_regmark_obstacles(shapes, {2}, cfg.sheet_x0, cfg.sheet_y0, cfg.spacing_mm)
    assert count == 1
    assert obstacles == [(0.0, 0.0, 9.0, 9.0)]


def test_rotation_candidates_determinism_and_metrics():
    assert generate_rotation_angles(False, 45.0) == [0.0]
    assert generate_rotation_angles(True, 45.0) == [0.0, 45.0, 90.0, 135.0]

    shapes = [
        {"id": 1, "label": "small", "kind": "poly", "closed": True, "points": [[0, 0], [10, 0], [10, 10], [0, 10]]},
        {"id": 2, "label": "large", "kind": "poly", "closed": True, "points": [[0, 0], [50, 0], [50, 20], [0, 20]]},
        {"id": 3, "label": "circle", "kind": "circle", "cx": 15, "cy": 15, "r": 10},
        {"id": 4, "label": "oversize", "kind": "poly", "closed": True, "points": [[0, 0], [500, 0], [500, 20], [0, 20]]},
        {"id": 5, "label": "zero", "kind": "poly", "closed": True, "points": [[0, 0], [0, 0], [0, 0]]},
    ]
    candidates = build_candidates(shapes)
    # Deterministically sorted: oversize (10000), large (1000), circle (400), small (100), zero (0)
    assert [c.shape_id for c in candidates] == [4, 2, 3, 1, 5]

    free_rects = _maxrects_subtract([(0.0, 0.0, 100.0, 100.0)], (0.0, 0.0, 10.0, 10.0))
    decisions1, unplaced1 = pack_candidates_maxrects(
        candidates, free_rects, 10.0, 10.0, spacing_mm=2.0, angles=[0.0, 90.0]
    )
    decisions2, unplaced2 = pack_candidates_maxrects(
        candidates, free_rects, 10.0, 10.0, spacing_mm=2.0, angles=[0.0, 90.0]
    )
    assert decisions1 == decisions2
    assert unplaced1 == unplaced2 == [4, 5]
    assert validate_placements_in_bounds(
        [d.bbox_mm for d in decisions1], (10.0, 10.0, 110.0, 110.0), spacing_mm=2.0
    )

    metrics = compute_nesting_metrics(100.0, 100.0, decisions1)
    assert metrics.usable_area_mm2 == 10000.0
    assert 0.0 < metrics.utilization_pct < 100.0
    assert metrics.true_area_utilization_pct <= metrics.utilization_pct

    empty_metrics = compute_nesting_metrics(100.0, 100.0, [])
    assert empty_metrics.bounding_envelope_mm is None
    assert empty_metrics.utilization_pct == 0.0

    # Verify in-place application on both polygon and circle
    shape_by_id = {s["id"]: s for s in shapes}
    for dec in decisions1:
        apply_placement_to_shape(shape_by_id[dec.shape_id], dec)
    assert shape_by_id[3]["cx"] >= 10.0 and shape_by_id[3]["cy"] >= 10.0

