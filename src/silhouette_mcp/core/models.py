"""Document shape models, bounding-box calculations, warnings, and cloning helpers."""

from __future__ import annotations

import copy
import math
from typing import Any

from ..config.settings import MIN_FEATURE_MM, _NON_CUT_LAYERS
from .exceptions import SilhouetteValueError
from .geometry_engine import _polygon_area2, _rotate
from .validators import _check_shape_capacity, _norm_layer, _num, _pos


def _bbox(s: dict) -> tuple[float, float, float, float]:
    if s["kind"] == "circle":
        return (s["cx"] - s["r"], s["cy"] - s["r"], s["cx"] + s["r"], s["cy"] + s["r"])
    xs = [p[0] for p in s["points"]]
    ys = [p[1] for p in s["points"]]
    return (min(xs), min(ys), max(xs), max(ys))


def _union_bbox(shapes: list[dict]) -> tuple[float, float, float, float] | None:
    if not shapes:
        return None
    bs = [_bbox(s) for s in shapes]
    return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))


def _shape_warnings(d: dict, s: dict) -> list[str]:
    x0, y0, x1, y1 = _bbox(s)
    W, H, m = d["width_mm"], d["height_mm"], d["cut_margin_mm"]
    w: list[str] = []
    if x0 < 0 or y0 < 0 or x1 > W or y1 > H:
        w.append("extends outside the page")
    elif x0 < m or y0 < m or x1 > W - m or y1 > H - m:
        w.append(f"inside the {m} mm safety margin; may fall outside the real cutting area")

    # Camadas nao-corte (vincos, picotes, gravacao, marcas) podem ter tracos ou bracos finos
    if s.get("layer", "CUT") in _NON_CUT_LAYERS:
        pass
    elif s.get("kind") == "poly" and not s.get("closed", True):
        if max(x1 - x0, y1 - y0) < MIN_FEATURE_MM:
            w.append(f"smaller than {MIN_FEATURE_MM} mm; fine details may not cut cleanly")
    else:
        if min(x1 - x0, y1 - y0) < MIN_FEATURE_MM:
            w.append(f"smaller than {MIN_FEATURE_MM} mm; fine details may not cut cleanly")
    return w


def _append_shape_in_memory(d: dict, label: str, **geom: Any) -> dict:
    _check_shape_capacity(d, 1)
    sid = d["next_id"]
    d["next_id"] += 1
    layer = _norm_layer(geom.pop("layer", "CUT"))
    s: dict[str, Any] = {"id": sid, "label": label, "layer": layer, **geom}
    if s["kind"] == "poly":
        s["points"] = [[round(float(x), 4), round(float(y), 4)] for x, y in s["points"]]
    d["shapes"].append(s)
    return s


def _clone_shifted(target: dict, new_id: int, dx: float, dy: float, suffix: str) -> dict:
    new_s = copy.deepcopy(target)
    new_s["id"] = new_id
    new_s["label"] = f"{target['label']}-{suffix}"
    if target["kind"] == "circle":
        new_s["cx"] = round(target["cx"] + dx, 4)
        new_s["cy"] = round(target["cy"] + dy, 4)
    else:
        new_s["points"] = [[round(x + dx, 4), round(y + dy, 4)] for x, y in target["points"]]
    return new_s


def _shape_area_mm2(s: dict) -> float:
    if s["kind"] == "circle":
        return math.pi * float(s["r"]) ** 2
    if s.get("closed", True) and len(s["points"]) >= 3:
        return abs(_polygon_area2([(float(p[0]), float(p[1])) for p in s["points"]])) * 0.5
    return 0.0


def _rotated_shape_preview(s: dict, deg: float) -> tuple[float, float, tuple[float, float, float, float]]:
    """Return (width, height, (x0, y0, x1, y1)) if shape `s` is rotated clockwise around its bbox center."""
    if s["kind"] == "circle" or abs(deg) <= 1e-9:
        b = _bbox(s)
        return (b[2] - b[0], b[3] - b[1], b)
    bx0, by0, bx1, by1 = _bbox(s)
    cx, cy = (bx0 + bx1) / 2.0, (by0 + by1) / 2.0
    rpts = _rotate(s["points"], cx, cy, deg)
    rx0 = min(p[0] for p in rpts)
    ry0 = min(p[1] for p in rpts)
    rx1 = max(p[0] for p in rpts)
    ry1 = max(p[1] for p in rpts)
    return (rx1 - rx0, ry1 - ry0, (rx0, ry0, rx1, ry1))


def _add_line_to_doc(
    d: dict[str, Any],
    x1_mm: float,
    y1_mm: float,
    x2_mm: float,
    y2_mm: float,
    *,
    dashed: bool = False,
    dash_len_mm: float = 3.0,
    gap_len_mm: float = 2.0,
    layer: str = "CUT",
    label: str = "",
    parent_id: int | None = None,
) -> list[dict[str, Any]]:
    """Append a continuous or dashed line directly to an in-memory design dictionary."""
    _num(x1_mm=x1_mm, y1_mm=y1_mm, x2_mm=x2_mm, y2_mm=y2_mm)
    length = math.hypot(x2_mm - x1_mm, y2_mm - y1_mm)
    if length <= 1e-4:
        raise SilhouetteValueError("Line length must be greater than zero")

    extra = {"parent_id": parent_id} if parent_id is not None else {}
    if not dashed:
        shape = _append_shape_in_memory(
            d,
            label or "line",
            kind="poly",
            closed=False,
            points=[(x1_mm, y1_mm), (x2_mm, y2_mm)],
            layer=layer,
            **extra,
        )
        return [shape]

    _pos(dash_len_mm=dash_len_mm, gap_len_mm=gap_len_mm)
    norm_layer = _norm_layer(layer)
    dx = (x2_mm - x1_mm) / length
    dy = (y2_mm - y1_mm) / length
    step = dash_len_mm + gap_len_mm
    cursor = 0.0
    seg_pairs: list[tuple[tuple[float, float], tuple[float, float]]] = []
    while cursor < length:
        cursor_end = min(cursor + dash_len_mm, length)
        if cursor_end - cursor >= 0.1:  # ignore microscopic dash fragments
            p0 = (x1_mm + dx * cursor, y1_mm + dy * cursor)
            p1 = (x1_mm + dx * cursor_end, y1_mm + dy * cursor_end)
            seg_pairs.append((p0, p1))
        cursor += step

    _check_shape_capacity(d, len(seg_pairs))

    added_shapes: list[dict[str, Any]] = []
    base_label = label or "dash-line"
    for idx, (p0, p1) in enumerate(seg_pairs, 1):
        sid = d["next_id"]
        d["next_id"] += 1
        shape = {
            "id": sid,
            "label": f"{base_label}#{idx}",
            "layer": norm_layer,
            "kind": "poly",
            "closed": False,
            "points": [[round(p0[0], 4), round(p0[1], 4)], [round(p1[0], 4), round(p1[1], 4)]],
            **extra,
        }
        d["shapes"].append(shape)
        added_shapes.append(shape)
    return added_shapes

