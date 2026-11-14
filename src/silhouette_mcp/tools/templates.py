"""Thin MCP tool adapter for parametric packaging and papercraft templates."""

from __future__ import annotations

from ..services import template_service


def silhouette_add_box_template(
    design: str,
    template: str = "milk-box-luxo",
    x_mm: float = 20.0,
    y_mm: float = 15.0,
    width_mm: float = 60.0,
    depth_mm: float = 60.0,
    body_height_mm: float = 90.0,
    dashed_score: bool = True,
) -> dict:
    """Generate a ready-to-cut parametric packaging / papercraft template with CUT and SCORE layers.
    Supported templates: 'milk-box-luxo', 'milk-box', 'cube-box', 'pillow-box', 'gift-tag'."""
    return template_service.add_box_template(
        design=design,
        template=template,
        x_mm=x_mm,
        y_mm=y_mm,
        width_mm=width_mm,
        depth_mm=depth_mm,
        body_height_mm=body_height_mm,
        dashed_score=dashed_score,
    )


__all__ = [
    "silhouette_add_box_template",
]
