"""MaxRects 2D bin packing (Best Short Side Fit + Best Area Fit) and rotation helpers."""

from __future__ import annotations

from typing import Any

from ..geometry_engine import _rotate
from ..models import _bbox, _rotated_shape_preview, _shape_area_mm2, _union_bbox
from .collision import resolve_composite_groups
from .models import NestingCandidate, PlacementDecision


def _maxrects_subtract(
    free_rects: list[tuple[float, float, float, float]],
    blocked: tuple[float, float, float, float],
) -> list[tuple[float, float, float, float]]:
    """Subtract a placed/blocked rectangle from free MaxRects regions and prune dominated rects."""
    bx0, by0, bx1, by1 = blocked
    next_rects: list[tuple[float, float, float, float]] = []
    for fx0, fy0, fx1, fy1 in free_rects:
        if bx1 <= fx0 + 1e-7 or bx0 >= fx1 - 1e-7 or by1 <= fy0 + 1e-7 or by0 >= fy1 - 1e-7:
            next_rects.append((fx0, fy0, fx1, fy1))
            continue
        if bx0 - fx0 > 1e-4:
            next_rects.append((fx0, fy0, min(fx1, bx0), fy1))
        if fx1 - bx1 > 1e-4:
            next_rects.append((max(fx0, bx1), fy0, fx1, fy1))
        if by0 - fy0 > 1e-4:
            next_rects.append((fx0, fy0, fx1, min(fy1, by0)))
        if fy1 - by1 > 1e-4:
            next_rects.append((fx0, max(fy0, by1), fx1, fy1))

    # Deduplicate and discard free rectangles strictly contained inside larger ones
    next_rects.sort(key=lambda r: (r[2] - r[0]) * (r[3] - r[1]), reverse=True)
    pruned: list[tuple[float, float, float, float]] = []
    for cand in next_rects:
        cx0, cy0, cx1, cy1 = cand
        contained = False
        for px0, py0, px1, py1 in pruned:
            if cx0 >= px0 - 1e-6 and cy0 >= py0 - 1e-6 and cx1 <= px1 + 1e-6 and cy1 <= py1 + 1e-6:
                contained = True
                break
        if not contained:
            pruned.append(cand)
    return pruned


def generate_rotation_angles(allow_rotation: bool, rotation_step_deg: float) -> list[float]:
    """Generate deterministic clockwise candidate angles in `[0, 180)` degrees."""
    if not allow_rotation:
        return [0.0]
    angles: list[float] = [0.0]
    k = 1
    while k * rotation_step_deg < 180.0 - 1e-6:
        angles.append(round(k * rotation_step_deg, 4))
        k += 1
    return angles


def build_candidates(targets: list[dict[str, Any]]) -> list[NestingCandidate]:
    """Order candidate shapes deterministically by descending bbox area, max side, then id."""
    items: list[NestingCandidate] = []
    for s in targets:
        bbox = _bbox(s)
        w0 = bbox[2] - bbox[0]
        h0 = bbox[3] - bbox[1]
        items.append(
            NestingCandidate(
                shape=s,
                shape_id=s["id"],
                label=s["label"],
                orig_bbox=bbox,
                width_mm=w0,
                height_mm=h0,
                bbox_area_mm2=w0 * h0,
                shape_area_mm2=_shape_area_mm2(s),
            )
        )
    items.sort(key=lambda c: (-c.bbox_area_mm2, -max(c.width_mm, c.height_mm), c.shape_id))
    return items


def build_composite_candidates(targets: list[dict[str, Any]]) -> list[NestingCandidate]:
    """Build candidates grouped into parent-child composites so nested cuts/creases move together."""
    items: list[NestingCandidate] = []
    for root, children in resolve_composite_groups(targets):
        group_shapes = [root, *children]
        bbox = _union_bbox(group_shapes) or _bbox(root)
        w0 = bbox[2] - bbox[0]
        h0 = bbox[3] - bbox[1]
        items.append(
            NestingCandidate(
                shape=root,
                shape_id=root["id"],
                label=root["label"],
                orig_bbox=bbox,
                width_mm=w0,
                height_mm=h0,
                bbox_area_mm2=w0 * h0,
                shape_area_mm2=_shape_area_mm2(root),
                children=tuple(children),
            )
        )
    items.sort(key=lambda c: (-c.bbox_area_mm2, -max(c.width_mm, c.height_mm), c.shape_id))
    return items


def _rotated_group_preview(
    group_shapes: list[dict[str, Any]], deg: float
) -> tuple[float, float, tuple[float, float, float, float], tuple[float, float], list[tuple[float, float, float, float]]]:
    ub = _union_bbox(group_shapes) or _bbox(group_shapes[0])
    gcx, gcy = (ub[0] + ub[2]) / 2.0, (ub[1] + ub[3]) / 2.0
    member_bboxes: list[tuple[float, float, float, float]] = []
    for s in group_shapes:
        if abs(deg) <= 1e-9:
            mb = _bbox(s)
        elif s["kind"] == "circle":
            rcx, rcy = _rotate([(float(s["cx"]), float(s["cy"]))], gcx, gcy, deg)[0]
            r = float(s["r"])
            mb = (rcx - r, rcy - r, rcx + r, rcy + r)
        else:
            rpts = _rotate(s["points"], gcx, gcy, deg)
            mb = (
                min(p[0] for p in rpts),
                min(p[1] for p in rpts),
                max(p[0] for p in rpts),
                max(p[1] for p in rpts),
            )
        member_bboxes.append(mb)
    grbbox = (
        min(b[0] for b in member_bboxes),
        min(b[1] for b in member_bboxes),
        max(b[2] for b in member_bboxes),
        max(b[3] for b in member_bboxes),
    )
    return (grbbox[2] - grbbox[0], grbbox[3] - grbbox[1], grbbox, (gcx, gcy), member_bboxes)


def extract_root_decisions(decisions: list[PlacementDecision]) -> list[PlacementDecision]:
    """Collapse child decisions into one bounding-box decision per composite root for metrics."""
    by_root: dict[int, list[PlacementDecision]] = {}
    root_order: list[int] = []
    for dec in decisions:
        rid = dec.shape_id if dec.parent_id is None else dec.parent_id
        if rid not in by_root:
            by_root[rid] = []
            root_order.append(rid)
        by_root[rid].append(dec)

    roots: list[PlacementDecision] = []
    for rid in root_order:
        grp = by_root[rid]
        root_dec = next((d for d in grp if d.parent_id is None), grp[0])
        if len(grp) == 1:
            roots.append(root_dec)
            continue
        gx0 = min(d.bbox_mm[0] for d in grp)
        gy0 = min(d.bbox_mm[1] for d in grp)
        gx1 = max(d.bbox_mm[2] for d in grp)
        gy1 = max(d.bbox_mm[3] for d in grp)
        gw, gh = gx1 - gx0, gy1 - gy0
        rx0, ry0, rx1, ry1 = root_dec.bbox_mm
        extra_area = 0.0
        for d in grp:
            if d.shape_id == root_dec.shape_id or d.shape_area_mm2 <= 0:
                continue
            cx0, cy0, cx1, cy1 = d.bbox_mm
            inside_root = cx0 >= rx0 - 1e-3 and cy0 >= ry0 - 1e-3 and cx1 <= rx1 + 1e-3 and cy1 <= ry1 + 1e-3
            if not inside_root:
                extra_area += d.shape_area_mm2
        total_area = min(gw * gh, root_dec.shape_area_mm2 + extra_area)
        roots.append(
            PlacementDecision(
                shape_id=root_dec.shape_id,
                label=root_dec.label,
                kind=root_dec.kind,
                placed_x_mm=gx0,
                placed_y_mm=gy0,
                width_mm=gw,
                height_mm=gh,
                rotation_deg=root_dec.rotation_deg,
                orig_rotated_bbox=root_dec.orig_rotated_bbox,
                bbox_mm=(gx0, gy0, gx1, gy1),
                shape_area_mm2=total_area,
                pivot_xy=root_dec.pivot_xy,
                parent_id=None,
            )
        )
    return roots


def pack_candidates_maxrects(
    candidates: list[NestingCandidate],
    initial_free_rects: list[tuple[float, float, float, float]],
    sheet_x0: float,
    sheet_y0: float,
    spacing_mm: float,
    angles: list[float],
) -> tuple[list[PlacementDecision], list[int]]:
    """Run deterministic MaxRects BSSF+BAF packing and return `(placed_decisions, unplaced_ids)`."""
    free_rects = list(initial_free_rects)
    decisions: list[PlacementDecision] = []
    unplaced_ids: list[int] = []

    for cand in candidates:
        s = cand.shape
        has_children = bool(cand.children)
        item_angles = [0.0] if (s["kind"] == "circle" and not has_children) else angles
        best_score: tuple[float, float, float, float, float] | None = None
        best_choice: tuple[
            float,
            float,
            float,
            float,
            float,
            tuple[float, float, float, float],
            tuple[float, float] | None,
            list[tuple[float, float, float, float]] | None,
        ] | None = None

        for deg in item_angles:
            if has_children:
                rw, rh, rbbox, pivot_xy, member_bboxes = _rotated_group_preview([s, *cand.children], deg)
            else:
                rw, rh, rbbox = _rotated_shape_preview(s, deg)
                pivot_xy = None
                member_bboxes = None
            is_open_line = s["kind"] == "poly" and not s.get("closed", True)
            if (rw <= 0 and rh <= 0) or (not is_open_line and not has_children and (rw <= 0 or rh <= 0)):
                continue
            for fx0, fy0, fx1, fy1 in free_rects:
                fw, fh = fx1 - fx0, fy1 - fy0
                if rw <= fw + 1e-6 and rh <= fh + 1e-6:
                    rem_w = fw - rw
                    rem_h = fh - rh
                    short_fit = min(rem_w, rem_h)
                    long_fit = max(rem_w, rem_h)
                    area_fit = fw * fh - rw * rh
                    score = (
                        round(short_fit, 5),
                        round(long_fit, 5),
                        round(area_fit, 5),
                        round(fy0, 5),
                        round(fx0, 5),
                    )
                    if best_score is None or score < best_score:
                        best_score = score
                        best_choice = (fx0, fy0, rw, rh, deg, rbbox, pivot_xy, member_bboxes)

        if best_choice is None:
            unplaced_ids.append(cand.shape_id)
            for child in cand.children:
                unplaced_ids.append(child["id"])
            continue

        lx, ly, rw, rh, deg, rbbox, pivot_xy, member_bboxes = best_choice
        px0, py0 = sheet_x0 + lx, sheet_y0 + ly

        free_rects = _maxrects_subtract(
            free_rects,
            (lx - spacing_mm, ly - spacing_mm, lx + rw + spacing_mm, ly + rh + spacing_mm),
        )

        if not has_children:
            px1, py1 = px0 + rw, py0 + rh
            decisions.append(
                PlacementDecision(
                    shape_id=cand.shape_id,
                    label=cand.label,
                    kind=s["kind"],
                    placed_x_mm=px0,
                    placed_y_mm=py0,
                    width_mm=rw,
                    height_mm=rh,
                    rotation_deg=deg,
                    orig_rotated_bbox=rbbox,
                    bbox_mm=(px0, py0, px1, py1),
                    shape_area_mm2=cand.shape_area_mm2,
                )
            )
        else:
            gdx = px0 - rbbox[0]
            gdy = py0 - rbbox[1]
            assert member_bboxes is not None
            for idx, (member, mb) in enumerate(zip([s, *cand.children], member_bboxes)):
                mx0, my0, mx1, my1 = mb
                m_px0, m_py0 = mx0 + gdx, my0 + gdy
                m_px1, m_py1 = mx1 + gdx, my1 + gdy
                decisions.append(
                    PlacementDecision(
                        shape_id=member["id"],
                        label=member["label"],
                        kind=member["kind"],
                        placed_x_mm=m_px0,
                        placed_y_mm=m_py0,
                        width_mm=mx1 - mx0,
                        height_mm=my1 - my0,
                        rotation_deg=deg,
                        orig_rotated_bbox=mb,
                        bbox_mm=(m_px0, m_py0, m_px1, m_py1),
                        shape_area_mm2=_shape_area_mm2(member),
                        pivot_xy=pivot_xy,
                        parent_id=None if idx == 0 else cand.shape_id,
                    )
                )

    return decisions, unplaced_ids


def apply_placement_to_shape(shape: dict[str, Any], decision: PlacementDecision) -> None:
    """Apply a computed `PlacementDecision` in-place to a shape dict."""
    dx = decision.dx
    dy = decision.dy
    if shape["kind"] == "circle":
        cx, cy = float(shape["cx"]), float(shape["cy"])
        if decision.rotation_deg and decision.pivot_xy is not None:
            cx, cy = _rotate([(cx, cy)], decision.pivot_xy[0], decision.pivot_xy[1], decision.rotation_deg)[0]
        shape["cx"] = round(cx + dx, 4)
        shape["cy"] = round(cy + dy, 4)
        return

    if decision.pivot_xy is not None:
        cx, cy = decision.pivot_xy
    else:
        bx0, by0, bx1, by1 = _bbox(shape)
        cx, cy = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
    pts = (
        _rotate(shape["points"], cx, cy, decision.rotation_deg)
        if decision.rotation_deg
        else [(float(x), float(y)) for x, y in shape["points"]]
    )
    shape["points"] = [[round(x + dx, 4), round(y + dy, 4)] for x, y in pts]

