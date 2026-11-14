"""Bounding-box collision detection, clearance checks, and regmark obstacle computation."""

from __future__ import annotations

import math
from typing import Any

from ...config.settings import _NON_CUT_LAYERS
from ..geometry_engine import _point_in_polygon, _point_to_polygon_dist
from ..models import _bbox


def boxes_overlap(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
    eps: float = 1e-6,
) -> bool:
    """Return True if two axis-aligned boxes `(x0, y0, x1, y1)` strictly overlap beyond `eps`."""
    return a[0] < b[2] - eps and a[2] > b[0] + eps and a[1] < b[3] - eps and a[3] > b[1] + eps


def min_clearance_between_boxes(
    a: tuple[float, float, float, float],
    b: tuple[float, float, float, float],
) -> float:
    """Return the Euclidean clearance in mm between two disjoint boxes, or `0.0` if overlapping."""
    dx = max(0.0, a[0] - b[2], b[0] - a[2])
    dy = max(0.0, a[1] - b[3], b[1] - a[3])
    if dx == 0.0 and dy == 0.0:
        return 0.0
    return math.hypot(dx, dy)


def validate_placements_in_bounds(
    boxes: list[tuple[float, float, float, float]],
    bounds: tuple[float, float, float, float],
    spacing_mm: float = 0.0,
    eps: float = 1e-5,
) -> bool:
    """Verify every placed box stays within `bounds` and maintains pairwise `spacing_mm` clearance."""
    bx0, by0, bx1, by1 = bounds
    for x0, y0, x1, y1 in boxes:
        if x0 < bx0 - eps or y0 < by0 - eps or x1 > bx1 + eps or y1 > by1 + eps:
            return False

    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            if boxes_overlap(boxes[i], boxes[j], eps=eps):
                return False
            if spacing_mm > 0.0 and min_clearance_between_boxes(boxes[i], boxes[j]) < spacing_mm - eps:
                return False
    return True


def _shape_to_obstacle(
    s: dict[str, Any],
    sheet_x0: float,
    sheet_y0: float,
    pad: float,
) -> tuple[float, float, float, float]:
    rx0, ry0, rx1, ry1 = _bbox(s)
    return (
        rx0 - sheet_x0 - pad,
        ry0 - sheet_y0 - pad,
        rx1 - sheet_x0 + pad,
        ry1 - sheet_y0 + pad,
    )


def _compute_layer_obstacles(
    shapes: list[dict[str, Any]],
    selected_ids: set[int],
    sheet_x0: float,
    sheet_y0: float,
    pad: float,
    *,
    regmark_only: bool,
) -> tuple[list[tuple[float, float, float, float]], int]:
    obstacles: list[tuple[float, float, float, float]] = []
    avoided = 0
    for s in shapes:
        if s["id"] in selected_ids:
            continue
        is_reg = s.get("layer") == "REGMARK"
        if (regmark_only and is_reg) or (not regmark_only and not is_reg):
            avoided += 1
            obstacles.append(_shape_to_obstacle(s, sheet_x0, sheet_y0, pad))
    return obstacles, avoided


def compute_regmark_obstacles(
    shapes: list[dict[str, Any]],
    selected_ids: set[int],
    sheet_x0: float,
    sheet_y0: float,
    spacing_mm: float,
) -> tuple[list[tuple[float, float, float, float]], int]:
    """Compute sheet-local blocked rectangles `(x0, y0, x1, y1)` around non-selected REGMARK shapes."""
    return _compute_layer_obstacles(
        shapes,
        selected_ids,
        sheet_x0,
        sheet_y0,
        max(1.0, float(spacing_mm)),
        regmark_only=True,
    )


def compute_unselected_obstacles(
    shapes: list[dict[str, Any]],
    selected_ids: set[int],
    sheet_x0: float,
    sheet_y0: float,
    spacing_mm: float,
) -> tuple[list[tuple[float, float, float, float]], int]:
    """Compute sheet-local blocked rectangles around non-selected non-REGMARK shapes."""
    return _compute_layer_obstacles(
        shapes,
        selected_ids,
        sheet_x0,
        sheet_y0,
        max(0.0, float(spacing_mm)),
        regmark_only=False,
    )


def _shape_sample_points(shape: dict[str, Any]) -> list[tuple[float, float]]:
    if shape["kind"] == "circle":
        cx, cy, r = float(shape["cx"]), float(shape["cy"]), float(shape["r"])
        pts = [(cx, cy)]
        for k in range(8):
            ang = k * (math.pi / 4.0)
            pts.append((cx + r * math.cos(ang), cy + r * math.sin(ang)))
        return pts
    raw = [(float(p[0]), float(p[1])) for p in shape["points"]]
    samples = list(raw)
    closed = bool(shape.get("closed", True))
    seg_count = len(raw) if closed else max(0, len(raw) - 1)
    for i in range(seg_count):
        a = raw[i]
        b = raw[(i + 1) % len(raw)]
        samples.append(((a[0] + b[0]) * 0.5, (a[1] + b[1]) * 0.5))
    return samples


def _shape_encloses_child(parent: dict[str, Any], child: dict[str, Any]) -> bool:
    """Return True if closed `CUT` `parent` strictly (or boundary-tolerant for non-CUT) encloses `child`."""
    if parent["id"] == child["id"] or parent.get("layer", "CUT") != "CUT":
        return False
    if parent["kind"] == "poly" and (not parent.get("closed", True) or len(parent["points"]) < 3):
        return False

    px0, py0, px1, py1 = _bbox(parent)
    cx0, cy0, cx1, cy1 = _bbox(child)
    p_area = (px1 - px0) * (py1 - py0)
    c_area = (cx1 - cx0) * (cy1 - cy0)
    if p_area <= 1e-6 or c_area >= p_area - 1e-6:
        return False

    child_non_cut = child.get("layer", "CUT") in _NON_CUT_LAYERS
    tol = 1e-2
    if child_non_cut:
        if cx0 < px0 - tol or cy0 < py0 - tol or cx1 > px1 + tol or cy1 > py1 + tol:
            return False
    else:
        # Strict interior check avoids falsely grouping distinct CUT parts stacked at origin (e.g. 10, 10)
        if cx0 <= px0 + tol or cy0 <= py0 + tol or cx1 >= px1 - tol or cy1 >= py1 - tol:
            return False

    samples = _shape_sample_points(child)
    if parent["kind"] == "circle":
        pcx, pcy, pr = float(parent["cx"]), float(parent["cy"]), float(parent["r"])
        limit = pr + tol if child_non_cut else pr - 1e-3
        return all(math.hypot(pt[0] - pcx, pt[1] - pcy) <= limit if child_non_cut else math.hypot(pt[0] - pcx, pt[1] - pcy) < limit for pt in samples)

    p_pts = [(float(p[0]), float(p[1])) for p in parent["points"]]
    if child_non_cut:
        return all(_point_in_polygon(pt, p_pts, boundary_tol=tol) for pt in samples)
    return all(_point_in_polygon(pt, p_pts, boundary_tol=0.0) and _point_to_polygon_dist(pt, p_pts) > 1e-3 for pt in samples)


def resolve_composite_groups(targets: list[dict[str, Any]]) -> list[tuple[dict[str, Any], list[dict[str, Any]]]]:
    """Group composite shapes (explicit `parent_id` or enclosed child contours) under root shapes."""
    by_id = {s["id"]: s for s in targets}
    bboxes = {s["id"]: _bbox(s) for s in targets}
    bbox_areas = {sid: (b[2] - b[0]) * (b[3] - b[1]) for sid, b in bboxes.items()}
    parent_of: dict[int, int] = {}

    for s in targets:
        pid = s.get("parent_id")
        if isinstance(pid, int) and not isinstance(pid, bool) and pid in by_id and pid != s["id"]:
            parent_of[s["id"]] = pid

    cut_parents = [
        s for s in targets
        if s.get("layer", "CUT") == "CUT"
        and (s["kind"] == "circle" or (s["kind"] == "poly" and s.get("closed", True) and len(s["points"]) >= 3))
    ]
    cut_parents.sort(key=lambda s: (bbox_areas[s["id"]], s["id"]))

    for s in targets:
        if s["id"] in parent_of:
            continue
        for cand_p in cut_parents:
            if _shape_encloses_child(cand_p, s):
                parent_of[s["id"]] = cand_p["id"]
                break

    def _find_root(sid: int) -> int:
        cur = sid
        seen: set[int] = set()
        while cur in parent_of and cur not in seen:
            seen.add(cur)
            nxt = parent_of[cur]
            if nxt in seen:
                break
            cur = nxt
        return cur

    children_by_root: dict[int, list[dict[str, Any]]] = {s["id"]: [] for s in targets if _find_root(s["id"]) == s["id"]}
    for s in targets:
        root_id = _find_root(s["id"])
        if root_id != s["id"]:
            children_by_root[root_id].append(s)

    groups: list[tuple[dict[str, Any], list[dict[str, Any]]]] = []
    for s in targets:
        if s["id"] in children_by_root:
            groups.append((s, children_by_root[s["id"]]))
    return groups

