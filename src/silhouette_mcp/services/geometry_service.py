"""Vector primitives, transformations, offsetting, duplication, regmarks, and typography service."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ..config.settings import (
    MAX_POINTS_PER_SHAPE,
    MAX_TEXT_LENGTH,
    _ALLOWED_FONT_EXTS,
    _FALLBACK_GLYPHS,
    _FONT_ALIASES,
    get_runtime_attr,
)
from ..core.exceptions import SilhouetteValueError
from ..core.geometry_engine import (
    _arc,
    _dedupe_closed,
    _eval_cubic,
    _eval_quad,
    _has_self_intersection,
    _is_collinear_points,
    _offset_polygon,
    _polygon_area2,
    _rotate,
    _rounded_rect,
)
from ..core.models import (
    _add_line_to_doc,
    _append_shape_in_memory,
    _bbox,
    _clone_shifted,
    _shape_warnings,
    _union_bbox,
)
from ..core.validators import _check_shape_capacity, _int, _is_finite_coord, _norm_layer, _num, _pos, _r4
from ..persistence.repository import _add, load_design, save_design
from ..persistence.storage import _LOCK


def add_rectangle(
    design: str,
    x_mm: float,
    y_mm: float,
    width_mm: float,
    height_mm: float,
    corner_radius_mm: float = 0,
    rotation_deg: float = 0,
    layer: str = "CUT",
    label: str = "",
) -> dict[str, Any]:
    """Create and persist a rectangle (optionally rounded and rotated)."""
    _num(x_mm=x_mm, y_mm=y_mm, corner_radius_mm=corner_radius_mm, rotation_deg=rotation_deg)
    _pos(width_mm=width_mm, height_mm=height_mm)
    radius = max(0.0, min(corner_radius_mm, width_mm / 2, height_mm / 2))
    pts = _rounded_rect(x_mm, y_mm, width_mm, height_mm, radius)
    if rotation_deg:
        cx = x_mm + width_mm / 2
        cy = y_mm + height_mm / 2
        pts = _rotate(pts, cx, cy, rotation_deg)
    return _add(design, label or "rectangle", kind="poly", closed=True, points=pts, layer=layer)


def add_circle(
    design: str,
    cx_mm: float,
    cy_mm: float,
    radius_mm: float,
    layer: str = "CUT",
    label: str = "",
) -> dict[str, Any]:
    """Create and persist a true circle centered at `(cx_mm, cy_mm)`."""
    _num(cx_mm=cx_mm, cy_mm=cy_mm)
    _pos(radius_mm=radius_mm)
    return _add(design, label or "circle", kind="circle", cx=cx_mm, cy=cy_mm, r=radius_mm, layer=layer)


def add_ellipse(
    design: str,
    cx_mm: float,
    cy_mm: float,
    rx_mm: float,
    ry_mm: float,
    rotation_deg: float = 0,
    layer: str = "CUT",
    label: str = "",
) -> dict[str, Any]:
    """Create and persist a discretized closed ellipse."""
    _num(cx_mm=cx_mm, cy_mm=cy_mm, rotation_deg=rotation_deg)
    _pos(rx_mm=rx_mm, ry_mm=ry_mm)
    pts = _dedupe_closed(_arc(cx_mm, cy_mm, rx_mm, ry_mm, 0, 2 * math.pi))
    return _add(
        design,
        label or "ellipse",
        kind="poly",
        closed=True,
        points=_rotate(pts, cx_mm, cy_mm, rotation_deg),
        layer=layer,
    )


def add_polygon(
    design: str,
    cx_mm: float,
    cy_mm: float,
    radius_mm: float,
    sides: int,
    rotation_deg: float = 0,
    layer: str = "CUT",
    label: str = "",
) -> dict[str, Any]:
    """Create and persist a regular N-sided polygon (3..64)."""
    _num(cx_mm=cx_mm, cy_mm=cy_mm, rotation_deg=rotation_deg)
    _pos(radius_mm=radius_mm)
    if isinstance(sides, bool) or not isinstance(sides, int) or not 3 <= sides <= 64:
        raise SilhouetteValueError("sides must be an integer between 3 and 64")
    a0 = math.radians(rotation_deg) - math.pi / 2
    pts = [
        (
            cx_mm + radius_mm * math.cos(a0 + 2 * math.pi * k / sides),
            cy_mm + radius_mm * math.sin(a0 + 2 * math.pi * k / sides),
        )
        for k in range(sides)
    ]
    return _add(design, label or f"polygon-{sides}", kind="poly", closed=True, points=pts, layer=layer)


def add_star(
    design: str,
    cx_mm: float,
    cy_mm: float,
    outer_radius_mm: float,
    inner_radius_mm: float,
    points: int = 5,
    rotation_deg: float = 0,
    layer: str = "CUT",
    label: str = "",
) -> dict[str, Any]:
    """Create and persist a star polygon with alternating outer and inner vertices."""
    _num(cx_mm=cx_mm, cy_mm=cy_mm, rotation_deg=rotation_deg)
    _pos(outer_radius_mm=outer_radius_mm, inner_radius_mm=inner_radius_mm)
    if inner_radius_mm >= outer_radius_mm:
        raise SilhouetteValueError("inner_radius_mm must be smaller than outer_radius_mm")
    if isinstance(points, bool) or not isinstance(points, int) or not 3 <= points <= 64:
        raise SilhouetteValueError("points must be an integer between 3 and 64")
    a0 = math.radians(rotation_deg) - math.pi / 2
    pts = []
    for k in range(points * 2):
        radius = outer_radius_mm if k % 2 == 0 else inner_radius_mm
        angle = a0 + math.pi * k / points
        pts.append((cx_mm + radius * math.cos(angle), cy_mm + radius * math.sin(angle)))
    return _add(design, label or f"star-{points}", kind="poly", closed=True, points=pts, layer=layer)


def add_line(
    design: str,
    x1_mm: float,
    y1_mm: float,
    x2_mm: float,
    y2_mm: float,
    dashed: bool = False,
    dash_len_mm: float = 3.0,
    gap_len_mm: float = 2.0,
    layer: str = "CUT",
    label: str = "",
) -> dict[str, Any]:
    """Create and persist a straight continuous or perforated dashed line."""
    _num(x1_mm=x1_mm, y1_mm=y1_mm, x2_mm=x2_mm, y2_mm=y2_mm)
    length = math.hypot(x2_mm - x1_mm, y2_mm - y1_mm)
    if length <= 1e-4:
        raise SilhouetteValueError("Line length must be greater than zero")

    if not dashed:
        return _add(
            design,
            label or "line",
            kind="poly",
            closed=False,
            points=[(x1_mm, y1_mm), (x2_mm, y2_mm)],
            layer=layer,
        )

    _pos(dash_len_mm=dash_len_mm, gap_len_mm=gap_len_mm)
    with _LOCK:
        doc = load_design(design)
        added_shapes = _add_line_to_doc(
            doc,
            x1_mm,
            y1_mm,
            x2_mm,
            y2_mm,
            dashed=True,
            dash_len_mm=dash_len_mm,
            gap_len_mm=gap_len_mm,
            layer=layer,
            label=label,
        )
        save_design(doc)
        return {
            "design": doc["name"],
            "segments_added": len(added_shapes),
            "shape_ids": [s["id"] for s in added_shapes],
            "layer": _norm_layer(layer),
            "bbox_mm": _r4(_union_bbox(added_shapes)),
        }


def add_polyline(
    design: str,
    points: list[list[float]],
    closed: bool = True,
    layer: str = "CUT",
    label: str = "",
) -> dict[str, Any]:
    """Validate and persist a custom open or closed polyline."""
    if not isinstance(points, list) or any(not isinstance(p, (list, tuple)) or len(p) != 2 for p in points):
        raise SilhouetteValueError("points must be a list of [x, y] pairs")
    for p in points:
        _num(x=p[0], y=p[1])
    need = 3 if closed else 2
    if len(points) < need:
        raise SilhouetteValueError(f"Need at least {need} points")
    if len(points) > MAX_POINTS_PER_SHAPE:
        raise SilhouetteValueError(f"Too many points (max {MAX_POINTS_PER_SHAPE})")

    pts_f = [(float(p[0]), float(p[1])) for p in points]
    if closed:
        distinct = _dedupe_closed(pts_f)
        if len(distinct) < 3:
            raise SilhouetteValueError("Need at least 3 distinct points")
        if _is_collinear_points(distinct):
            raise SilhouetteValueError("Closed polygon has zero area")
        if _has_self_intersection(distinct, closed=True):
            raise SilhouetteValueError("Closed polygon cannot have self-intersecting edges")
        if abs(_polygon_area2(distinct)) <= 1e-6:
            raise SilhouetteValueError("Closed polygon has zero area")

    return _add(design, label or "polyline", kind="poly", closed=bool(closed), points=pts_f, layer=layer)


def transform_shape(
    design: str,
    shape_id: int,
    dx_mm: float = 0,
    dy_mm: float = 0,
    scale: float = 1.0,
    rotation_deg: float = 0,
    flip_x: bool = False,
    flip_y: bool = False,
) -> dict[str, Any]:
    """Translate, scale, mirror, and rotate an existing shape around its bbox center."""
    _int(shape_id=shape_id)
    _num(dx_mm=dx_mm, dy_mm=dy_mm, scale=scale, rotation_deg=rotation_deg)
    if scale <= 0:
        raise SilhouetteValueError("scale must be > 0")

    with _LOCK:
        doc = load_design(design)
        target = next((s for s in doc["shapes"] if s["id"] == shape_id), None)
        if not target:
            raise SilhouetteValueError(f"No shape with id {shape_id}")

        bx0, by0, bx1, by1 = _bbox(target)
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2

        if target["kind"] == "circle":
            new_cx = round(target["cx"] + dx_mm, 4)
            new_cy = round(target["cy"] + dy_mm, 4)
            new_r = round(target["r"] * scale, 4)
            if new_r <= 1e-4:
                raise SilhouetteValueError("Transformed circle radius collapsed below minimum precision")
            _num(
                cx=new_cx,
                cy=new_cy,
                r=new_r,
                x0=new_cx - new_r,
                y0=new_cy - new_r,
                x1=new_cx + new_r,
                y1=new_cy + new_r,
            )
            target["cx"] = new_cx
            target["cy"] = new_cy
            target["r"] = new_r
        else:
            pts = [(float(x), float(y)) for x, y in target["points"]]
            if flip_x:
                pts = [(2 * cx - x, y) for x, y in pts]
            if flip_y:
                pts = [(x, 2 * cy - y) for x, y in pts]
            if scale != 1.0:
                pts = [(cx + (x - cx) * scale, cy + (y - cy) * scale) for x, y in pts]
            if rotation_deg:
                pts = _rotate(pts, cx, cy, rotation_deg)
            new_pts = [[round(x + dx_mm, 4), round(y + dy_mm, 4)] for x, y in pts]
            for px, py in new_pts:
                if not (_is_finite_coord(px) and _is_finite_coord(py)):
                    raise SilhouetteValueError("Transformed shape exceeds maximum coordinate magnitude")
            pt_tuples = [(p[0], p[1]) for p in new_pts]
            if target.get("closed", True):
                xs = [p[0] for p in pt_tuples]
                ys = [p[1] for p in pt_tuples]
                if (max(xs) - min(xs) <= 1e-4 and max(ys) - min(ys) <= 1e-4) or abs(_polygon_area2(pt_tuples)) <= 1e-6:
                    raise SilhouetteValueError("Transformed polygon collapsed to zero area")
            else:
                total_len = sum(
                    math.hypot(pt_tuples[i + 1][0] - pt_tuples[i][0], pt_tuples[i + 1][1] - pt_tuples[i][1])
                    for i in range(len(pt_tuples) - 1)
                )
                if total_len <= 1e-4:
                    raise SilhouetteValueError("Transformed polyline collapsed to zero length")
            target["points"] = new_pts

        save_design(doc)
        return {
            "design": doc["name"],
            "shape_id": shape_id,
            "bbox_mm": _r4(_bbox(target)),
            "warnings": _shape_warnings(doc, target),
        }


def offset_shape(
    design: str,
    shape_id: int,
    offset_mm: float,
    join: str = "round",
    layer: str = "",
    label: str = "",
) -> dict[str, Any]:
    """Generate an inward or outward offset contour from a circle or closed polygon."""
    _int(shape_id=shape_id)
    _num(offset_mm=offset_mm)
    if abs(offset_mm) <= 1e-6:
        raise SilhouetteValueError("offset_mm must be non-zero")
    join_norm = str(join).strip().lower()
    if join_norm not in ("round", "miter", "bevel"):
        raise SilhouetteValueError("join must be one of: round, miter, bevel")

    with _LOCK:
        doc = load_design(design)
        target = next((s for s in doc["shapes"] if s["id"] == shape_id), None)
        if not target:
            raise SilhouetteValueError(f"No shape with id {shape_id}")

        out_layer = _norm_layer(layer) if str(layer).strip() else target.get("layer", "CUT")
        out_label = label or f"{target['label']}-offset"

        if target["kind"] == "circle":
            new_r = target["r"] + offset_mm
            if new_r <= 0.1:
                raise SilhouetteValueError("Inward offset is too large for this circle")
            shape = _append_shape_in_memory(
                doc,
                out_label,
                kind="circle",
                cx=target["cx"],
                cy=target["cy"],
                r=round(new_r, 4),
                layer=out_layer,
            )
        else:
            if not target.get("closed", True):
                raise SilhouetteValueError("Offset is only supported for circles and closed polygons")
            new_pts = _offset_polygon(target["points"], float(offset_mm), join_norm)
            shape = _append_shape_in_memory(
                doc, out_label, kind="poly", closed=True, points=new_pts, layer=out_layer
            )

        save_design(doc)
        return {
            "design": doc["name"],
            "source_id": shape_id,
            "shape_id": shape["id"],
            "layer": shape["layer"],
            "bbox_mm": _r4(_bbox(shape)),
            "warnings": _shape_warnings(doc, shape),
        }


def duplicate_shape(
    design: str,
    shape_id: int,
    dx_mm: float = 0,
    dy_mm: float = 0,
    count: int = 1,
) -> dict[str, Any]:
    """Duplicate a shape `count` times with cumulative `(dx_mm, dy_mm)` step offsets."""
    _int(shape_id=shape_id)
    _num(dx_mm=dx_mm, dy_mm=dy_mm)
    if isinstance(count, bool) or not isinstance(count, int) or count < 1 or count > 100:
        raise SilhouetteValueError("count must be an integer between 1 and 100")

    with _LOCK:
        doc = load_design(design)
        target = next((s for s in doc["shapes"] if s["id"] == shape_id), None)
        if not target:
            raise SilhouetteValueError(f"No shape with id {shape_id}")

        _check_shape_capacity(doc, count)
        bx0, by0, bx1, by1 = _bbox(target)
        max_dx, max_dy = dx_mm * count, dy_mm * count
        _num(x0=bx0 + max_dx, y0=by0 + max_dy, x1=bx1 + max_dx, y1=by1 + max_dy)
        created_ids: list[int] = []
        for step in range(1, count + 1):
            new_id = doc["next_id"]
            doc["next_id"] += 1
            new_s = _clone_shifted(target, new_id, dx_mm * step, dy_mm * step, f"copy{step}")
            doc["shapes"].append(new_s)
            created_ids.append(new_id)

        save_design(doc)
        return {"design": doc["name"], "source_id": shape_id, "created_ids": created_ids, "count": len(created_ids)}


def grid_duplicates(
    design: str,
    shape_id: int,
    cols: int,
    rows: int,
    spacing_x_mm: float = 5.0,
    spacing_y_mm: float = 5.0,
) -> dict[str, Any]:
    """Arrange copies of a shape in a `cols x rows` rectangular grid."""
    _int(shape_id=shape_id, cols=cols, rows=rows)
    _num(spacing_x_mm=spacing_x_mm, spacing_y_mm=spacing_y_mm)
    if cols < 1 or rows < 1:
        raise SilhouetteValueError("cols and rows must be >= 1")
    if cols * rows < 2:
        raise SilhouetteValueError("cols * rows must be >= 2 to create duplicates")
    if cols * rows > 500:
        raise SilhouetteValueError("cols * rows cannot exceed 500")
    if spacing_x_mm < 0 or spacing_y_mm < 0:
        raise SilhouetteValueError("spacing_x_mm and spacing_y_mm must be >= 0")

    with _LOCK:
        doc = load_design(design)
        target = next((s for s in doc["shapes"] if s["id"] == shape_id), None)
        if not target:
            raise SilhouetteValueError(f"No shape with id {shape_id}")

        needed = cols * rows - 1
        _check_shape_capacity(doc, needed)

        bx0, by0, bx1, by1 = _bbox(target)
        step_x = (bx1 - bx0) + spacing_x_mm
        step_y = (by1 - by0) + spacing_y_mm
        max_dx = (cols - 1) * step_x
        max_dy = (rows - 1) * step_y
        _num(step_x=step_x, step_y=step_y, x0=bx0 + max_dx, y0=by0 + max_dy, x1=bx1 + max_dx, y1=by1 + max_dy)

        created_ids: list[int] = []
        created_shapes: list[dict[str, Any]] = []
        for r in range(rows):
            for c in range(cols):
                if r == 0 and c == 0:
                    continue
                new_id = doc["next_id"]
                doc["next_id"] += 1
                new_s = _clone_shifted(target, new_id, c * step_x, r * step_y, f"r{r+1}c{c+1}")
                doc["shapes"].append(new_s)
                created_ids.append(new_id)
                created_shapes.append(new_s)

        save_design(doc)
        all_grid = [target] + created_shapes
        return {
            "design": doc["name"],
            "source_id": shape_id,
            "cols": cols,
            "rows": rows,
            "created_ids": created_ids,
            "count": len(created_ids),
            "grid_bbox_mm": _r4(_union_bbox(all_grid)),
        }


def add_registration_marks(
    design: str,
    inset_mm: float = 10.0,
    mark_size_mm: float = 5.0,
    arm_len_mm: float = 15.0,
    arm_thick_mm: float = 1.0,
    layer: str = "REGMARK",
) -> dict[str, Any]:
    """Add standard 3-corner Silhouette Print & Cut registration marks."""
    _pos(inset_mm=inset_mm, mark_size_mm=mark_size_mm, arm_len_mm=arm_len_mm, arm_thick_mm=arm_thick_mm)
    with _LOCK:
        doc = load_design(design)
        _check_shape_capacity(doc, 3)
        width, height = doc["width_mm"], doc["height_mm"]
        if inset_mm * 2 + arm_len_mm * 2 >= min(width, height):
            raise SilhouetteValueError("Page is too small for the requested registration marks")

        tl = [
            (inset_mm, inset_mm),
            (inset_mm + mark_size_mm, inset_mm),
            (inset_mm + mark_size_mm, inset_mm + mark_size_mm),
            (inset_mm, inset_mm + mark_size_mm),
        ]
        rx = width - inset_mm
        ry = inset_mm
        tr = [
            (rx - arm_len_mm, ry),
            (rx, ry),
            (rx, ry + arm_len_mm),
            (rx - arm_thick_mm, ry + arm_len_mm),
            (rx - arm_thick_mm, ry + arm_thick_mm),
            (rx - arm_len_mm, ry + arm_thick_mm),
        ]
        bx = inset_mm
        by = height - inset_mm
        bl = [
            (bx, by - arm_len_mm),
            (bx + arm_thick_mm, by - arm_len_mm),
            (bx + arm_thick_mm, by - arm_thick_mm),
            (bx + arm_len_mm, by - arm_thick_mm),
            (bx + arm_len_mm, by),
            (bx, by),
        ]
        s1 = _append_shape_in_memory(doc, "regmark-top-left", kind="poly", closed=True, points=tl, layer=layer)
        s2 = _append_shape_in_memory(doc, "regmark-top-right", kind="poly", closed=True, points=tr, layer=layer)
        s3 = _append_shape_in_memory(doc, "regmark-bottom-left", kind="poly", closed=True, points=bl, layer=layer)
        save_design(doc)

        pad = inset_mm + max(mark_size_mm, arm_thick_mm) + 2.0
        arm_span = inset_mm + max(mark_size_mm, arm_len_mm)
        arm_pad = arm_span + 2.0 if (arm_span + 2.0) * 2.0 < min(width, height) else arm_span
        return {
            "design": doc["name"],
            "shape_ids": [s1["id"], s2["id"], s3["id"]],
            "layer": s1["layer"],
            "safe_print_area_mm": [round(pad, 3), round(pad, 3), round(width - pad, 3), round(height - pad, 3)],
            "inner_arm_safe_area_mm": [
                round(arm_pad, 3),
                round(arm_pad, 3),
                round(width - arm_pad, 3),
                round(height - arm_pad, 3),
            ],
        }


def _resolve_font_path(font: str) -> Path | None:
    """Resolve a font alias or explicit `.ttf/.otf/.ttc` font path on the host."""
    raw = str(font or "").strip()
    if raw:
        if raw.startswith("\\\\") or raw.startswith("//"):
            raise SilhouetteValueError("Network/UNC font paths are not allowed")
        path = Path(raw).expanduser()
        if path.is_file():
            if path.suffix.lower() not in _ALLOWED_FONT_EXTS:
                raise SilhouetteValueError("Custom font file must have a .ttf, .otf, or .ttc extension")
            return path
    key = raw.lower()
    candidates = list(_FONT_ALIASES.get(key, []))
    if raw:
        for ext in ("", ".ttf", ".otf"):
            candidates.insert(0, f"{raw}{ext}")
    font_dirs: list[Path] = get_runtime_attr("_FONT_DIRS")
    for directory in font_dirs:
        if not directory.is_dir():
            continue
        for cand in candidates:
            fp = directory / cand
            if fp.is_file():
                return fp
        if key:
            for fp in directory.rglob("*.ttf"):
                if key in fp.stem.lower():
                    return fp
    for directory in font_dirs:
        if directory.is_dir():
            for fp in sorted(directory.glob("*.ttf")):
                return fp
    return None


def _pen_ops_to_contours(ops: list[tuple[str, tuple[Any, ...]]]) -> list[list[tuple[float, float]]]:
    """Convert FontTools RecordingPen operations into closed polygonal contours."""
    contours: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []

    def flush() -> None:
        nonlocal cur
        pts = _dedupe_closed(cur)
        if len(pts) >= 3:
            contours.append(pts)
        cur = []

    for cmd, args in ops:
        if cmd == "moveTo":
            flush()
            cur = [(float(args[0][0]), float(args[0][1]))]
        elif cmd == "lineTo":
            if not cur:
                cur = [(float(args[0][0]), float(args[0][1]))]
            else:
                cur.append((float(args[0][0]), float(args[0][1])))
        elif cmd == "qCurveTo":
            if not args:
                continue
            if args[-1] is None:
                offs = [(float(p[0]), float(p[1])) for p in args[:-1]]
                if len(offs) >= 2:
                    start = ((offs[-1][0] + offs[0][0]) / 2, (offs[-1][1] + offs[0][1]) / 2)
                    cur = [start]
                    for i, ctrl in enumerate(offs):
                        nxt = offs[(i + 1) % len(offs)]
                        on = ((ctrl[0] + nxt[0]) / 2, (ctrl[1] + nxt[1]) / 2)
                        cur.extend(_eval_quad(cur[-1], ctrl, on, n=8))
            else:
                if not cur:
                    cur = [(float(args[0][0]), float(args[0][1]))]
                pts_q = [(float(p[0]), float(p[1])) for p in args]
                for i in range(len(pts_q) - 1):
                    ctrl = pts_q[i]
                    if i == len(pts_q) - 2:
                        on = pts_q[-1]
                    else:
                        nxt = pts_q[i + 1]
                        on = ((ctrl[0] + nxt[0]) / 2, (ctrl[1] + nxt[1]) / 2)
                    cur.extend(_eval_quad(cur[-1], ctrl, on, n=8))
        elif cmd == "curveTo":
            if not cur or len(args) < 3:
                continue
            for idx in range(0, len(args) - 2, 3):
                p1 = (float(args[idx][0]), float(args[idx][1]))
                p2 = (float(args[idx + 1][0]), float(args[idx + 1][1]))
                p3 = (float(args[idx + 2][0]), float(args[idx + 2][1]))
                cur.extend(_eval_cubic(cur[-1], p1, p2, p3, n=10))
        elif cmd in ("closePath", "endPath"):
            flush()
    flush()
    return contours


def _fallback_text_polygons(text: str, size_mm: float, letter_spacing_mm: float) -> list[list[tuple[float, float]]]:
    """Generate geometric fallback glyph outlines when system fonts are absent."""
    contours: list[list[tuple[float, float]]] = []
    line_h = size_mm * 1.35
    char_w = size_mm * 0.72
    space_w = size_mm * 0.45
    step_gap = size_mm * 0.16 + letter_spacing_mm

    for line_idx, line in enumerate(text.splitlines() or [text]):
        cx = 0.0
        cy = line_idx * line_h
        for ch in line:
            key = ch.upper()
            if ch.isspace():
                cx += space_w + letter_spacing_mm
                continue
            glyph = _FALLBACK_GLYPHS.get(key)
            if glyph is None:
                glyph = [
                    [(0.1, 0.0), (0.9, 0.0), (0.9, 1.0), (0.1, 1.0)],
                    [(0.25, 0.15), (0.75, 0.15), (0.75, 0.85), (0.25, 0.85)],
                ]
            for poly in glyph:
                contours.append([(cx + px * char_w, cy + py * size_mm) for px, py in poly])
            cx += char_w + step_gap
    return contours


def _font_text_polygons(
    text: str, font_path: Path, size_mm: float, letter_spacing_mm: float
) -> list[list[tuple[float, float]]]:
    """Extract vector contours from an OpenType/TrueType font file using fontTools."""
    from fontTools.pens.recordingPen import DecomposingRecordingPen
    from fontTools.ttLib import TTFont

    tt = TTFont(str(font_path), fontNumber=0)
    try:
        gs = tt.getGlyphSet()
        cmap = tt.getBestCmap() or {}
        hmtx = tt["hmtx"].metrics
        upm = float(tt["head"].unitsPerEm or 1000)
        cap = 0.0
        if "OS/2" in tt and getattr(tt["OS/2"], "sCapHeight", 0):
            cap = float(tt["OS/2"].sCapHeight)
        if cap <= 0:
            cap = upm * 0.72

        scale = size_mm / cap
        line_h = size_mm * 1.35
        space_g = cmap.get(ord(" "))
        space_adv = hmtx[space_g][0] if space_g and space_g in hmtx else upm * 0.3

        contours: list[list[tuple[float, float]]] = []
        for line_idx, line in enumerate(text.splitlines() or [text]):
            cursor_x = 0.0
            baseline_y = line_idx * line_h
            for ch in line:
                if ch.isspace():
                    cursor_x += space_adv * scale + letter_spacing_mm
                    continue
                gname = cmap.get(ord(ch)) or cmap.get(ord(ch.upper())) or ".notdef"
                if gname not in gs:
                    cursor_x += space_adv * scale + letter_spacing_mm
                    continue
                pen = DecomposingRecordingPen(gs)
                gs[gname].draw(pen)
                for poly in _pen_ops_to_contours(pen.value):
                    contours.append([(cursor_x + gx * scale, baseline_y - gy * scale) for gx, gy in poly])
                adv = hmtx[gname][0] if gname in hmtx else upm * 0.5
                cursor_x += adv * scale + letter_spacing_mm
        return contours
    finally:
        tt.close()


def add_text(
    design: str,
    text: str,
    x_mm: float,
    y_mm: float,
    size_mm: float = 15.0,
    font: str = "Arial",
    align: str = "left",
    letter_spacing_mm: float = 0.0,
    rotation_deg: float = 0.0,
    layer: str = "CUT",
    label: str = "",
) -> dict[str, Any]:
    """Vectorize text outlines and add the resulting closed contours to the design."""
    if not isinstance(text, str) or not text.strip():
        raise SilhouetteValueError("text must be a non-empty string")
    if len(text) > MAX_TEXT_LENGTH:
        raise SilhouetteValueError(f"text exceeds maximum length of {MAX_TEXT_LENGTH} characters")
    _num(x_mm=x_mm, y_mm=y_mm, letter_spacing_mm=letter_spacing_mm, rotation_deg=rotation_deg)
    _pos(size_mm=size_mm)
    align_norm = str(align).strip().lower()
    if align_norm not in ("left", "center", "right"):
        raise SilhouetteValueError("align must be one of: left, center, right")

    font_path = None if font == "__fallback__" else _resolve_font_path(font)
    used_font = str(font_path) if font_path else "builtin-vector-fallback"
    if font_path is not None:
        try:
            contours = _font_text_polygons(text, font_path, float(size_mm), float(letter_spacing_mm))
        except Exception:
            contours = _fallback_text_polygons(text, float(size_mm), float(letter_spacing_mm))
            used_font = "builtin-vector-fallback"
    else:
        contours = _fallback_text_polygons(text, float(size_mm), float(letter_spacing_mm))

    if not contours:
        raise SilhouetteValueError("Could not generate any vector contours for the given text")

    all_x = [p[0] for c in contours for p in c]
    all_y = [p[1] for c in contours for p in c]
    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)

    if align_norm == "left":
        dx = x_mm - min_x
    elif align_norm == "center":
        dx = x_mm - (min_x + max_x) / 2.0
    else:
        dx = x_mm - max_x
    dy = y_mm - min_y

    cx = (min_x + max_x) / 2.0 + dx
    cy = (min_y + max_y) / 2.0 + dy

    transformed: list[list[tuple[float, float]]] = []
    for poly in contours:
        shifted = [(px + dx, py + dy) for px, py in poly]
        if rotation_deg:
            shifted = _rotate(shifted, cx, cy, rotation_deg)
        transformed.append(shifted)

    base_label = label or f"text:{text.strip()[:20]}"
    with _LOCK:
        doc = load_design(design)
        _check_shape_capacity(doc, len(transformed))
        added_shapes: list[dict[str, Any]] = []
        for idx, poly in enumerate(transformed, 1):
            shape = _append_shape_in_memory(
                doc, f"{base_label}#{idx}", kind="poly", closed=True, points=poly, layer=layer
            )
            added_shapes.append(shape)
        if len(added_shapes) > 1:
            root_id = added_shapes[0]["id"]
            for child in added_shapes[1:]:
                child["parent_id"] = root_id
        save_design(doc)
        warnings = [
            f"shape {s['id']} ({s['label']}): {w}"
            for s in added_shapes
            for w in _shape_warnings(doc, s)
        ]
        return {
            "design": doc["name"],
            "contours_added": len(added_shapes),
            "shape_ids": [s["id"] for s in added_shapes],
            "font_used": used_font,
            "layer": _norm_layer(layer),
            "bbox_mm": _r4(_union_bbox(added_shapes)),
            "warnings": warnings,
        }

