"""2D computational geometry engine: curves, polygons, intersections, offsets, and MaxRects splits."""

from __future__ import annotations

import math
from typing import Any

from ..config.settings import CHORD_TOL_MM, MAX_ARC_SEGMENTS
from .exceptions import SilhouetteValueError


def _n_segments(r: float, sweep: float) -> int:
    r = max(r, 1e-6)
    step = math.pi / 2 if r <= CHORD_TOL_MM else 2 * math.acos(max(-1.0, min(1.0, 1 - CHORD_TOL_MM / r)))
    return min(MAX_ARC_SEGMENTS, max(2, math.ceil(abs(sweep) / max(step, 1e-6))))


def _arc(cx: float, cy: float, rx: float, ry: float, a0: float, a1: float) -> list[tuple[float, float]]:
    n = _n_segments(max(rx, ry), a1 - a0)
    return [
        (cx + rx * math.cos(a0 + (a1 - a0) * i / n), cy + ry * math.sin(a0 + (a1 - a0) * i / n))
        for i in range(n + 1)
    ]


def _dedupe_closed(pts: list[Any]) -> list[Any]:
    out: list[Any] = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-6:
            out.append(p)
    if len(out) > 1 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= 1e-6:
        out.pop()
    return out


def _polygon_area2(pts: list[tuple[float, float]]) -> float:
    """Signed double area (shoelace formula). In Y-down, > 0 means visual clockwise."""
    n = len(pts)
    if n < 3:
        return 0.0
    return sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))


def _is_collinear_points(pts: list[tuple[float, float]], eps: float = 1e-6) -> bool:
    if len(pts) < 3:
        return True
    p0 = pts[0]
    far = max(pts[1:], key=lambda q: math.hypot(q[0] - p0[0], q[1] - p0[1]))
    dx, dy = far[0] - p0[0], far[1] - p0[1]
    base_len = math.hypot(dx, dy)
    if base_len <= eps:
        return True
    return all(abs(dx * (p[1] - p0[1]) - dy * (p[0] - p0[0])) / base_len <= eps for p in pts[1:])


def _clean_polygon(pts_in: list[tuple[float, float]], eps: float = 1e-6) -> list[tuple[float, float]]:
    """Remove duplicate, collinear and 180-degree backtracking vertices from a closed polygon."""
    pts = _dedupe_closed([(float(p[0]), float(p[1])) for p in pts_in])
    changed = True
    while changed and len(pts) >= 3:
        changed = False
        keep: list[tuple[float, float]] = []
        n = len(pts)
        for i in range(n):
            p_prev = pts[(i - 1) % n]
            p_curr = pts[i]
            p_next = pts[(i + 1) % n]
            v1x, v1y = p_curr[0] - p_prev[0], p_curr[1] - p_prev[1]
            v2x, v2y = p_next[0] - p_curr[0], p_next[1] - p_curr[1]
            l1 = math.hypot(v1x, v1y)
            l2 = math.hypot(v2x, v2y)
            if l1 <= eps or l2 <= eps:
                changed = True
                continue
            cross = v1x * v2y - v1y * v2x
            perp = abs(cross) / max(l1, l2)
            dot = v1x * v2x + v1y * v2y
            if perp <= eps and (dot >= 0 or l1 <= eps or l2 <= eps):
                changed = True
                continue
            if perp <= eps and dot < 0:
                # 180-degree spike reversal
                changed = True
                continue
            keep.append(p_curr)
        pts = _dedupe_closed(keep)
    return pts


def _segments_intersect(
    a0: tuple[float, float],
    a1: tuple[float, float],
    b0: tuple[float, float],
    b1: tuple[float, float],
    eps: float = 1e-7,
) -> tuple[bool, tuple[float, float] | None]:
    """Return (intersects, intersection_point) for segments (a0,a1) and (b0,b1)."""
    if (
        max(a0[0], a1[0]) + eps < min(b0[0], b1[0])
        or max(b0[0], b1[0]) + eps < min(a0[0], a1[0])
        or max(a0[1], a1[1]) + eps < min(b0[1], b1[1])
        or max(b0[1], b1[1]) + eps < min(a0[1], a1[1])
    ):
        return False, None

    rx, ry = a1[0] - a0[0], a1[1] - a0[1]
    sx, sy = b1[0] - b0[0], b1[1] - b0[1]
    denom = rx * sy - ry * sx
    qpx, qpy = b0[0] - a0[0], b0[1] - a0[1]

    if abs(denom) <= eps:
        scale = max(1.0, math.hypot(rx, ry), math.hypot(sx, sy))
        if abs(qpx * ry - qpy * rx) > eps * scale:
            return False, None
        # Collinear overlap check
        if abs(rx) >= abs(ry):
            a_lo, a_hi = sorted((a0[0], a1[0]))
            b_lo, b_hi = sorted((b0[0], b1[0]))
        else:
            a_lo, a_hi = sorted((a0[1], a1[1]))
            b_lo, b_hi = sorted((b0[1], b1[1]))
        if min(a_hi, b_hi) + eps >= max(a_lo, b_lo):
            return True, None
        return False, None

    t = (qpx * sy - qpy * sx) / denom
    u = (qpx * ry - qpy * rx) / denom
    if -eps <= t <= 1.0 + eps and -eps <= u <= 1.0 + eps:
        tc = min(1.0, max(0.0, t))
        return True, (a0[0] + tc * rx, a0[1] + tc * ry)
    return False, None


def _has_self_intersection(pts: list[tuple[float, float]], closed: bool = True) -> bool:
    """Detect non-adjacent segment intersections or overlapping reversals in a polygon/polyline."""
    n = len(pts)
    seg_count = n if closed else max(0, n - 1)
    if seg_count < 3:
        return False

    bboxes = [
        (
            min(pts[i][0], pts[(i + 1) % n][0]),
            min(pts[i][1], pts[(i + 1) % n][1]),
            max(pts[i][0], pts[(i + 1) % n][0]),
            max(pts[i][1], pts[(i + 1) % n][1]),
        )
        for i in range(seg_count)
    ]

    for i in range(seg_count):
        a0, a1 = pts[i], pts[(i + 1) % n]
        ab = bboxes[i]
        adx, ady = a1[0] - a0[0], a1[1] - a0[1]
        al = math.hypot(adx, ady)
        for j in range(i + 1, seg_count):
            adjacent = (j == i + 1) or (closed and i == 0 and j == seg_count - 1)
            b0, b1 = pts[j], pts[(j + 1) % n]
            if adjacent:
                # Adjacent segments sharing a vertex must not fold straight back (180-deg overlap)
                bdx, bdy = b1[0] - b0[0], b1[1] - b0[1]
                bl = math.hypot(bdx, bdy)
                if al > 1e-8 and bl > 1e-8:
                    cos_ang = (adx * bdx + ady * bdy) / (al * bl)
                    if cos_ang <= -1.0 + 1e-7:
                        return True
                continue
            bb = bboxes[j]
            if ab[2] + 1e-7 < bb[0] or bb[2] + 1e-7 < ab[0] or ab[3] + 1e-7 < bb[1] or bb[3] + 1e-7 < ab[1]:
                continue
            hit, _ = _segments_intersect(a0, a1, b0, b1, eps=1e-7)
            if hit:
                return True
    return False


def _point_to_segment_dist(pt: tuple[float, float], a: tuple[float, float], b: tuple[float, float]) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    l2 = dx * dx + dy * dy
    if l2 <= 1e-16:
        return math.hypot(pt[0] - a[0], pt[1] - a[1])
    t = max(0.0, min(1.0, ((pt[0] - a[0]) * dx + (pt[1] - a[1]) * dy) / l2))
    return math.hypot(pt[0] - (a[0] + t * dx), pt[1] - (a[1] + t * dy))


def _point_to_polygon_dist(pt: tuple[float, float], poly: list[tuple[float, float]]) -> float:
    n = len(poly)
    if n == 0:
        return float("inf")
    return min(_point_to_segment_dist(pt, poly[i], poly[(i + 1) % n]) for i in range(n))


def _point_in_polygon(
    pt: tuple[float, float],
    poly: list[tuple[float, float]],
    boundary_tol: float = 1e-5,
) -> bool:
    if _point_to_polygon_dist(pt, poly) <= boundary_tol:
        return True
    px, py = pt
    inside = False
    n = len(poly)
    j = n - 1
    for i in range(n):
        xi, yi = poly[i]
        xj, yj = poly[j]
        if ((yi > py) != (yj > py)) and (px < (xj - xi) * (py - yi) / ((yj - yi) or 1e-18) + xi):
            inside = not inside
        j = i
    return inside


def _prune_self_intersection_loops(
    pts: list[tuple[float, float]], target_orient: float, max_passes: int = 200
) -> list[tuple[float, float]]:
    """Iteratively resolve self-crossing loops by splitting at intersections and keeping the largest valid cycle."""
    cur = _dedupe_closed(pts)
    for _ in range(max_passes):
        n = len(cur)
        if n < 4:
            break
        split_done = False
        for i in range(n):
            a0, a1 = cur[i], cur[(i + 1) % n]
            for j in range(i + 2, n):
                if i == 0 and j == n - 1:
                    continue
                b0, b1 = cur[j], cur[(j + 1) % n]
                hit, ip = _segments_intersect(a0, a1, b0, b1, eps=1e-7)
                if not hit or ip is None:
                    continue
                loop_a = _dedupe_closed([ip] + cur[i + 1 : j + 1])
                loop_b = _dedupe_closed([ip] + cur[j + 1 :] + cur[: i + 1])
                aa = _polygon_area2(loop_a)
                ab = _polygon_area2(loop_b)
                va = len(loop_a) >= 3 and (aa * target_orient) > 1e-6
                vb = len(loop_b) >= 3 and (ab * target_orient) > 1e-6
                if va and vb:
                    nxt = loop_a if abs(aa) >= abs(ab) else loop_b
                elif va:
                    nxt = loop_a
                elif vb:
                    nxt = loop_b
                else:
                    return cur
                if len(nxt) <= n and nxt != cur:
                    cur = nxt
                    split_done = True
                    break
            if split_done:
                break
        if not split_done:
            break
    return cur


def _rotate(pts: list[Any], cx: float, cy: float, deg: float) -> list[tuple[float, float]]:
    if not deg:
        return [(float(x), float(y)) for x, y in pts]
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [(cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c) for x, y in pts]


def _rounded_rect(x: float, y: float, w: float, h: float, r: float) -> list[tuple[float, float]]:
    if r <= 0:
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    d = math.pi / 180
    pts: list[tuple[float, float]] = []
    pts += _arc(x + r, y + r, r, r, 180 * d, 270 * d)          # topo-esquerdo
    pts += _arc(x + w - r, y + r, r, r, 270 * d, 360 * d)      # topo-direito
    pts += _arc(x + w - r, y + h - r, r, r, 0, 90 * d)         # base-direita
    pts += _arc(x + r, y + h - r, r, r, 90 * d, 180 * d)       # base-esquerda
    return _dedupe_closed(pts)


def _eval_cubic(
    p0: tuple[float, float], p1: tuple[float, float], p2: tuple[float, float], p3: tuple[float, float], n: int
) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for i in range(1, n + 1):
        t = i / n
        mt = 1.0 - t
        x = (mt ** 3) * p0[0] + 3 * (mt ** 2) * t * p1[0] + 3 * mt * (t ** 2) * p2[0] + (t ** 3) * p3[0]
        y = (mt ** 3) * p0[1] + 3 * (mt ** 2) * t * p1[1] + 3 * mt * (t ** 2) * p2[1] + (t ** 3) * p3[1]
        pts.append((x, y))
    return pts


def _eval_quad(p0: tuple[float, float], p1: tuple[float, float], p2: tuple[float, float], n: int = 8) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for i in range(1, n + 1):
        t = i / n
        mt = 1.0 - t
        x = (mt ** 2) * p0[0] + 2 * mt * t * p1[0] + (t ** 2) * p2[0]
        y = (mt ** 2) * p0[1] + 2 * mt * t * p1[1] + (t ** 2) * p2[1]
        pts.append((x, y))
    return pts


def _offset_polygon(pts_in: list[Any], offset_mm: float, join: str) -> list[tuple[float, float]]:
    orig_pts = _dedupe_closed([(float(p[0]), float(p[1])) for p in pts_in])
    if len(orig_pts) < 3:
        raise SilhouetteValueError("Polygon must have at least 3 distinct vertices")

    if _is_collinear_points(orig_pts):
        raise SilhouetteValueError("Shape has zero area and cannot be offset")
    if _has_self_intersection(orig_pts, closed=True):
        raise SilhouetteValueError("Cannot offset a self-intersecting polygon")

    # Area assinada (shoelace) em Y-down: > 0 indica sentido horario visual
    area2 = _polygon_area2(orig_pts)
    if abs(area2) <= 1e-6:
        raise SilhouetteValueError("Shape has zero area and cannot be offset")

    pts = _clean_polygon(orig_pts)
    if len(pts) < 3:
        raise SilhouetteValueError("Polygon must have at least 3 non-degenerate edges")
    if _has_self_intersection(pts, closed=True):
        raise SilhouetteValueError("Cannot offset a self-intersecting polygon")

    orient = 1.0 if area2 > 0 else -1.0
    n = len(pts)

    edges: list[tuple[tuple[float, float], tuple[float, float], float]] = []
    clean_pts: list[tuple[float, float]] = []
    for i in range(n):
        p0, p1 = pts[i], pts[(i + 1) % n]
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        length = math.hypot(dx, dy)
        if length <= 1e-8:
            continue
        ux, uy = dx / length, dy / length
        nx, ny = orient * uy, -orient * ux
        edges.append(((ux, uy), (nx, ny), length))
        clean_pts.append(p0)

    m = len(edges)
    if m < 3:
        raise SilhouetteValueError("Polygon must have at least 3 non-degenerate edges")

    out: list[tuple[float, float]] = []
    miter_limit = abs(offset_mm) * 4.0

    for i in range(m):
        u_prev, n_prev, l_prev = edges[(i - 1) % m]
        u_curr, n_curr, l_curr = edges[i]
        v = clean_pts[i]

        a_prev = (v[0] + offset_mm * n_prev[0], v[1] + offset_mm * n_prev[1])
        a_curr = (v[0] + offset_mm * n_curr[0], v[1] + offset_mm * n_curr[1])

        cross = u_prev[0] * u_curr[1] - u_prev[1] * u_curr[0]
        is_outer_corner = (orient * offset_mm * cross) > 1e-6

        if abs(cross) <= 1e-6:
            out.append(a_curr)
            continue

        if is_outer_corner and join == "round":
            ang0 = math.atan2(a_prev[1] - v[1], a_prev[0] - v[0])
            ang1 = math.atan2(a_curr[1] - v[1], a_curr[0] - v[0])
            sweep = (ang1 - ang0) % (2 * math.pi)
            if sweep > math.pi:
                sweep -= 2 * math.pi
            arc_pts = _arc(v[0], v[1], abs(offset_mm), abs(offset_mm), ang0, ang0 + sweep)
            out.extend(arc_pts)
        elif is_outer_corner and join == "bevel":
            out.append(a_prev)
            out.append(a_curr)
        else:
            # Intersecao das duas retas deslocadas: a_prev + t * u_prev = a_curr + s * u_curr
            dx, dy = a_curr[0] - a_prev[0], a_curr[1] - a_prev[1]
            t = (dx * u_curr[1] - dy * u_curr[0]) / cross
            ix, iy = a_prev[0] + t * u_prev[0], a_prev[1] + t * u_prev[1]
            proj_limit = miter_limit if is_outer_corner else max(miter_limit, min(l_prev, l_curr) * 1.5)
            if math.hypot(ix - v[0], iy - v[1]) > proj_limit:
                out.append(a_prev)
                out.append(a_curr)
            else:
                out.append((ix, iy))

    result = _prune_self_intersection_loops(out, orient)
    result = _clean_polygon(result)
    err_msg = (
        "Inward offset is too large for this shape"
        if offset_mm < 0
        else "Offset creates an invalid or self-intersecting contour"
    )
    if len(result) < 3:
        raise SilhouetteValueError(err_msg)
    new_area2 = _polygon_area2(result)
    if new_area2 * area2 <= 1e-6:
        raise SilhouetteValueError(err_msg)
    xs = [p[0] for p in result]
    ys = [p[1] for p in result]
    if max(xs) - min(xs) < 0.2 or max(ys) - min(ys) < 0.2:
        raise SilhouetteValueError(err_msg)
    if _has_self_intersection(result, closed=True):
        raise SilhouetteValueError(err_msg)
    if offset_mm < 0:
        min_clearance = abs(offset_mm) - max(1e-2, abs(offset_mm) * 0.02)
        if any(
            not _point_in_polygon(p, pts, boundary_tol=1e-4)
            or _point_to_polygon_dist(p, pts) < min_clearance
            for p in result
        ):
            raise SilhouetteValueError(err_msg)
    return result

