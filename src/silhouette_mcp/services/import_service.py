"""SVG XML security validation, curve flattening, and SVG import service."""

from __future__ import annotations

import math
import re
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

try:
    from defusedxml import ElementTree as DefusedET
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    DefusedET = None  # type: ignore[assignment]

from ..config.settings import get_runtime_attr
from ..core.exceptions import SilhouetteValueError
from ..core.geometry_engine import (
    _dedupe_closed,
    _has_self_intersection,
    _is_collinear_points,
    _polygon_area2,
    _rotate,
)
from ..core.models import _shape_warnings, _union_bbox
from ..core.validators import _is_finite_coord, _norm_layer, _num, _r4
from ..persistence.repository import load_design, save_design
from ..persistence.storage import _LOCK

_SVG_FORBIDDEN_RE = re.compile(
    r"(<!ENTITY\b|<!DOCTYPE[^>]+(?:SYSTEM|PUBLIC)|<\s*script\b|javascript\s*:|url\s*\(\s*['\"]?\s*(?:https?|ftp|file):)",
    re.IGNORECASE,
)
_SVG_EXTERNAL_REF_RE = re.compile(r"^(?:https?|ftp|file)://", re.IGNORECASE)


def _validate_svg_file(svg_file: Path) -> None:
    """Enforce UTF-8, anti-XXE, depth/element budgets, and no external URL/script payloads."""
    max_depth = int(get_runtime_attr("MAX_SVG_DEPTH"))
    max_elements = int(get_runtime_attr("MAX_SVG_ELEMENTS"))
    try:
        raw_text = svg_file.read_text(encoding="utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise SilhouetteValueError(f"SVG file must be valid UTF-8 XML: {exc}") from exc

    if _SVG_FORBIDDEN_RE.search(raw_text):
        raise SilhouetteValueError("SVG contains unsupported or potentially unsafe markup (DOCTYPE/ENTITY/script)")

    parser_mod = DefusedET if DefusedET is not None else ET
    try:
        root = parser_mod.fromstring(raw_text)
    except Exception as exc:
        raise SilhouetteValueError(f"Invalid or unsafe SVG XML: {exc}") from exc

    root_tag = root.tag.split("}")[-1].lower()
    if root_tag != "svg":
        raise SilhouetteValueError("Invalid SVG file: root XML element must be <svg>")

    elem_count = 0
    stack: list[tuple[Any, int]] = [(root, 1)]
    while stack:
        elem, depth = stack.pop()
        if depth > max_depth:
            raise SilhouetteValueError(f"SVG XML nesting exceeds maximum depth ({max_depth})")
        elem_count += 1
        if elem_count > max_elements:
            raise SilhouetteValueError(f"SVG contains too many XML elements (max {max_elements})")
        tag = elem.tag.split("}")[-1].lower()
        if tag == "script":  # pragma: no cover
            raise SilhouetteValueError("SVG contains unsupported <script> element")
        for attr, val in elem.attrib.items():
            attr_name = attr.split("}")[-1].lower()
            if attr_name in ("href", "src") and _SVG_EXTERNAL_REF_RE.match(str(val).strip()):
                raise SilhouetteValueError("SVG cannot contain external URL references (http/https/ftp/file)")
        for child in elem:
            stack.append((child, depth + 1))


def _svg_subpaths(svg_file: Path) -> tuple[list[tuple[list[tuple[float, float]], bool]], int]:
    """Parse an SVG file and return `(subpaths_in_px, skipped_element_count)`."""
    _validate_svg_file(svg_file)
    max_total_points = int(get_runtime_attr("MAX_SVG_TOTAL_POINTS"))
    max_points_per_shape = int(get_runtime_attr("MAX_POINTS_PER_SHAPE"))
    try:
        from svgelements import SVG, Close, Image, Line, Move, Path as SvgPath, Shape, Text
    except ImportError as exc:  # pragma: no cover
        raise SilhouetteValueError("The 'svgelements' package is not installed (pip install svgelements)") from exc

    svg = SVG.parse(str(svg_file), reify=True)  # user units = px at 96 ppi
    subpaths: list[tuple[list[tuple[float, float]], bool]] = []
    skipped = 0
    total_points = 0
    for el in svg.elements():
        if isinstance(el, (Text, Image)):
            skipped += 1
            continue
        if not isinstance(el, Shape):
            continue
        cur: list[tuple[float, float]] = []

        def append_pt(x: float, y: float) -> None:
            px, py = float(x), float(y)
            if not (math.isfinite(px) and math.isfinite(py)):
                raise SilhouetteValueError("SVG contains non-finite coordinates")
            cur.append((px, py))
            if total_points + len(cur) > max_total_points + 1:
                raise SilhouetteValueError(f"SVG generates too many vertices (max {max_total_points})")
            if len(cur) > max_points_per_shape + 1:
                raise SilhouetteValueError(
                    f"SVG subpath has too many points (max {max_points_per_shape})"
                )

        def flush(closed: bool = False) -> None:
            nonlocal cur, total_points
            if len(cur) >= 2:
                if not closed and math.hypot(cur[0][0] - cur[-1][0], cur[0][1] - cur[-1][1]) < 1e-6:
                    closed = True
                if closed and math.hypot(cur[0][0] - cur[-1][0], cur[0][1] - cur[-1][1]) < 1e-6:
                    cur = cur[:-1]
                if len(cur) >= (3 if closed else 2):
                    if len(cur) > max_points_per_shape:
                        raise SilhouetteValueError(
                            f"SVG subpath has too many points (max {max_points_per_shape})"
                        )
                    total_points += len(cur)
                    if total_points > max_total_points:
                        raise SilhouetteValueError(
                            f"SVG generates too many vertices (max {max_total_points})"
                        )
                    subpaths.append((cur, closed))
            cur = []

        for seg in SvgPath(el):
            if isinstance(seg, Move):
                flush()
                append_pt(seg.end.x, seg.end.y)
            elif isinstance(seg, Close):
                flush(closed=True)
            else:
                if not cur:
                    append_pt(seg.start.x, seg.start.y)
                if isinstance(seg, Line):
                    append_pt(seg.end.x, seg.end.y)
                else:
                    try:
                        n = max(12, min(256, math.ceil(seg.length() * 25.4 / 96 / 0.4)))
                    except Exception:
                        n = 32
                    for i in range(1, n + 1):
                        pt = seg.point(i / n)
                        append_pt(pt.x, pt.y)
        flush()
    return subpaths, skipped


def import_svg(
    design: str,
    svg_path: str,
    target_width_mm: float = 0,
    target_height_mm: float = 0,
    x_mm: float = 0,
    y_mm: float = 0,
    rotation_deg: float = 0,
    layer: str = "CUT",
) -> dict[str, Any]:
    """Validate, flatten, scale, and append SVG outlines into an existing design."""
    _num(
        target_width_mm=target_width_mm,
        target_height_mm=target_height_mm,
        x_mm=x_mm,
        y_mm=y_mm,
        rotation_deg=rotation_deg,
    )
    if target_width_mm < 0 or target_height_mm < 0:
        raise SilhouetteValueError("target_width_mm and target_height_mm must be >= 0")
    if not isinstance(svg_path, str) or not svg_path.strip() or "\x00" in svg_path:
        raise SilhouetteValueError("svg_path must be an existing .svg file")
    raw_svg = svg_path.strip()
    if raw_svg.startswith("\\\\") or raw_svg.startswith("//"):
        raise SilhouetteValueError("Network/UNC paths are not allowed for svg_path")
    try:
        path = Path(raw_svg).expanduser().resolve()
    except (OSError, ValueError) as exc:
        raise SilhouetteValueError(f"Invalid svg_path '{svg_path}': {exc}") from exc
    if str(path).startswith("\\\\") or str(path).startswith("//"):
        raise SilhouetteValueError("Network/UNC paths are not allowed for svg_path")
    if path.suffix.lower() != ".svg" or not path.is_file():
        raise SilhouetteValueError("svg_path must be an existing .svg file")
    max_svg_bytes = int(get_runtime_attr("MAX_SVG_BYTES"))
    if path.stat().st_size > max_svg_bytes:
        raise SilhouetteValueError("SVG is larger than 10 MB")

    subs, skipped = _svg_subpaths(path)
    if not subs:
        raise SilhouetteValueError("No outlines found in the SVG (text/images are not supported)")

    px_to_mm = 25.4 / 96
    allpts = [(x * px_to_mm, y * px_to_mm) for pts, _ in subs for x, y in pts]
    minx, miny = min(a[0] for a in allpts), min(a[1] for a in allpts)
    width = max(a[0] for a in allpts) - minx
    height = max(a[1] for a in allpts) - miny

    if target_width_mm > 0 and target_height_mm > 0 and width > 0 and height > 0:
        sx = target_width_mm / width
        sy = target_height_mm / height
    elif target_width_mm > 0 and width > 0:
        sx = sy = target_width_mm / width
    elif target_height_mm > 0 and height > 0:
        sx = sy = target_height_mm / height
    else:
        sx = sy = 1.0

    norm_layer = _norm_layer(layer)
    cx = x_mm + (width * sx) / 2.0
    cy = y_mm + (height * sy) / 2.0
    _num(sx=sx, sy=sy, cx=cx, cy=cy)
    max_shapes = int(get_runtime_attr("MAX_SHAPES"))

    with _LOCK:
        doc = load_design(design)
        if len(subs) + len(doc["shapes"]) > max_shapes:
            raise SilhouetteValueError(
                f"SVG has too many paths ({len(subs)}); limit is {max_shapes} shapes per design"
            )

        prepared_shapes: list[dict[str, Any]] = []
        next_sid = doc["next_id"]
        for i, (pts, closed) in enumerate(subs, 1):
            mm = [(x_mm + (x * px_to_mm - minx) * sx, y_mm + (y * px_to_mm - miny) * sy) for x, y in pts]
            if rotation_deg:
                mm = _rotate(mm, cx, cy, rotation_deg)
            for ax, ay in mm:
                if not (_is_finite_coord(ax) and _is_finite_coord(ay)):
                    raise SilhouetteValueError(
                        f"Imported SVG path #{i} exceeds maximum coordinate magnitude or is non-finite"
                    )
            rounded_pts = [[round(a, 4), round(b, 4)] for a, b in mm]
            if closed:
                distinct = _dedupe_closed([(p[0], p[1]) for p in rounded_pts])
                if len(distinct) < 3 or _is_collinear_points(distinct):
                    raise SilhouetteValueError(f"Imported closed SVG path #{i} is degenerate (zero area)")
                if _has_self_intersection(distinct, closed=True):
                    raise SilhouetteValueError(f"Imported closed SVG path #{i} has self-intersecting edges")
                if abs(_polygon_area2(distinct)) <= 1e-6:
                    raise SilhouetteValueError(f"Imported closed SVG path #{i} is degenerate (zero area)")
            prepared_shapes.append({
                "id": next_sid,
                "label": f"svg:{path.stem}#{i}",
                "layer": norm_layer,
                "kind": "poly",
                "closed": closed,
                "points": rounded_pts,
            })
            next_sid += 1

        doc["shapes"].extend(prepared_shapes)
        doc["next_id"] = next_sid
        save_design(doc)
        added = doc["shapes"][-len(subs):]
        warnings = []
        if skipped:
            warnings.append(f"{skipped} text/image element(s) were skipped")
        out_of_page = [s["id"] for s in added if any(_shape_warnings(doc, s))]
        if out_of_page:
            warnings.append(
                f"{len(out_of_page)} imported path(s) trigger placement/size warnings; run silhouette_describe_design"
            )
        return {
            "design": doc["name"],
            "paths_added": len(subs),
            "scale_applied": round(sx, 4),
            "bbox_mm": _r4(_union_bbox(added)),
            "warnings": warnings,
        }

