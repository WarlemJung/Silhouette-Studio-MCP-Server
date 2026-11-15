"""Application service orchestrating parametric packaging and papercraft templates."""

from __future__ import annotations

import copy
from typing import Any

from ..core.models import _shape_warnings, _union_bbox
from ..core.templates import (
    SUPPORTED_BOX_TEMPLATES,
    BoxTemplateSpec,
    _bow_arc,
    _build_cube_box,
    _build_gift_tag,
    _build_milk_box,
    _build_pillow_box,
    _milk_arch_pts,
    generate_box_template_shapes,
)
from ..core.validators import _r4
from ..persistence.repository import load_design, save_design
from ..persistence.storage import _LOCK

__all__ = [
    "BoxTemplateSpec",
    "SUPPORTED_BOX_TEMPLATES",
    "_bow_arc",
    "_build_cube_box",
    "_build_gift_tag",
    "_build_milk_box",
    "_build_pillow_box",
    "_milk_arch_pts",
    "add_box_template",
    "generate_box_template_shapes",
]


def add_box_template(
    design: str,
    template: str = "milk-box-luxo",
    x_mm: float = 20.0,
    y_mm: float = 15.0,
    width_mm: float = 60.0,
    depth_mm: float = 60.0,
    body_height_mm: float = 90.0,
    dashed_score: bool = True,
) -> dict[str, Any]:
    """Generate and persist a parametric packaging/papercraft dieline in CUT/SCORE layers."""
    spec = BoxTemplateSpec(
        template=template,
        x_mm=x_mm,
        y_mm=y_mm,
        width_mm=width_mm,
        depth_mm=depth_mm,
        body_height_mm=body_height_mm,
        dashed_score=bool(dashed_score),
    )

    with _LOCK:
        doc = load_design(design)
        working = copy.deepcopy(doc)
        added = generate_box_template_shapes(working, spec)

        doc["shapes"] = working["shapes"]
        doc["next_id"] = working["next_id"]
        save_design(doc)
        warnings = [
            f"shape {s['id']} ({s['label']}): {w}"
            for s in added
            for w in _shape_warnings(doc, s)
        ]
        return {
            "design": doc["name"],
            "template": spec.template,
            "shapes_added": len(added),
            "shape_ids": [s["id"] for s in added],
            "bbox_mm": _r4(_union_bbox(added)),
            "warnings": warnings,
        }
