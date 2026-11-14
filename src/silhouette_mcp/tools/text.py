"""Thin MCP tool adapter for typography vectorization."""

from __future__ import annotations

from ..services import geometry_service


def silhouette_add_text(
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
) -> dict:
    """Convert text into vector cut/score outlines using a system/custom TTF/OTF font
    (or built-in geometric vector fallback) and add the glyph contours to the design.
    x_mm, y_mm mark the top edge anchored horizontally by align ('left', 'center', 'right')."""
    return geometry_service.add_text(
        design=design,
        text=text,
        x_mm=x_mm,
        y_mm=y_mm,
        size_mm=size_mm,
        font=font,
        align=align,
        letter_spacing_mm=letter_spacing_mm,
        rotation_deg=rotation_deg,
        layer=layer,
        label=label,
    )


__all__ = [
    "silhouette_add_text",
]
