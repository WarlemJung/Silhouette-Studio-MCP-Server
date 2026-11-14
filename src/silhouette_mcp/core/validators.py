"""Validation, formatting, capacity enforcement, and schema verification helpers."""

from __future__ import annotations

import math
import re
from typing import Any

from ..config.settings import MAX_COORD_MM, get_runtime_attr
from .exceptions import SilhouetteValueError


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", str(name).strip()).strip("-_")
    if not s:
        raise SilhouetteValueError("Invalid name: use letters, digits, '-' or '_'.")
    return s[:64]


def _num(**kw: Any) -> None:
    for k, v in kw.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise SilhouetteValueError(f"{k} must be a finite number")
        if abs(v) > MAX_COORD_MM:
            raise SilhouetteValueError(f"{k} exceeds maximum coordinate magnitude ({MAX_COORD_MM} mm)")


def _pos(**kw: Any) -> None:
    _num(**kw)
    for k, v in kw.items():
        if v <= 0:
            raise SilhouetteValueError(f"{k} must be > 0")


def _int(**kw: Any) -> None:
    for k, v in kw.items():
        if isinstance(v, bool) or not isinstance(v, int):
            raise SilhouetteValueError(f"{k} must be an integer")


def _check_shape_capacity(d: dict, additional: int = 1) -> None:
    max_shapes = get_runtime_attr("MAX_SHAPES")
    if len(d["shapes"]) + additional > max_shapes:
        raise SilhouetteValueError(f"Design has reached the limit of {max_shapes} shapes.")


def _norm_layer(layer: str, default: str = "CUT") -> str:
    return str(layer).strip().upper() or default


def _fmt(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".") or "0"


def _r4(b: tuple[float, float, float, float] | None) -> list[float] | None:
    return [round(v, 3) for v in b] if b else None


def _is_finite_coord(v: Any) -> bool:
    return not isinstance(v, bool) and isinstance(v, (int, float)) and math.isfinite(v) and abs(v) <= MAX_COORD_MM


def _validate_shape_dict(idx: int, shape: Any) -> None:
    if not isinstance(shape, dict):
        raise SilhouetteValueError(f"Corrupted design: shape[{idx}] must be a JSON object")
    sid = shape.get("id")
    if isinstance(sid, bool) or not isinstance(sid, int) or sid < 1:
        raise SilhouetteValueError(f"Corrupted design: shape[{idx}] has invalid 'id'")
    kind = shape.get("kind")
    if kind == "circle":
        for attr in ("cx", "cy", "r"):
            if not _is_finite_coord(shape.get(attr)):
                raise SilhouetteValueError(f"Corrupted design: shape[{idx}] has invalid '{attr}'")
        if shape["r"] <= 0:
            raise SilhouetteValueError(f"Corrupted design: shape[{idx}] must have r > 0")
    elif kind == "poly":
        pts = shape.get("points")
        if not isinstance(pts, list) or not pts:
            raise SilhouetteValueError(f"Corrupted design: shape[{idx}] has invalid 'points'")
        for pidx, pt in enumerate(pts):
            if (
                not isinstance(pt, (list, tuple))
                or len(pt) != 2
                or not _is_finite_coord(pt[0])
                or not _is_finite_coord(pt[1])
            ):
                raise SilhouetteValueError(
                    f"Corrupted design: shape[{idx}].points[{pidx}] must be finite [x, y] within bounds"
                )
    else:
        raise SilhouetteValueError(f"Corrupted design: shape[{idx}] has unsupported kind '{kind}'")


def _validate_design_dict(raw: Any) -> dict:
    if not isinstance(raw, dict):
        raise SilhouetteValueError("Design document root must be a JSON object")
    required = ("name", "width_mm", "height_mm", "cut_margin_mm", "next_id", "shapes")
    for key in required:
        if key not in raw:
            raise SilhouetteValueError(f"Corrupted design: missing field '{key}'")
    if not isinstance(raw["name"], str) or not raw["name"].strip():
        raise SilhouetteValueError("Corrupted design: invalid 'name'")
    for key in ("width_mm", "height_mm"):
        val = raw[key]
        if not _is_finite_coord(val) or val <= 0:
            raise SilhouetteValueError(f"Corrupted design: invalid '{key}'")
    cm = raw["cut_margin_mm"]
    if not _is_finite_coord(cm) or cm < 0:
        raise SilhouetteValueError("Corrupted design: invalid 'cut_margin_mm'")
    if not isinstance(raw["shapes"], list):
        raise SilhouetteValueError("Corrupted design: 'shapes' must be a list")
    for idx, shape in enumerate(raw["shapes"]):
        _validate_shape_dict(idx, shape)
    if isinstance(raw["next_id"], bool) or not isinstance(raw["next_id"], int) or raw["next_id"] < 1:
        raise SilhouetteValueError("Corrupted design: invalid 'next_id'")
    raw.setdefault("revision", 1)
    if isinstance(raw["revision"], bool) or not isinstance(raw["revision"], int) or raw["revision"] < 0:
        raise SilhouetteValueError("Corrupted design: invalid 'revision'")
    return raw

