"""Thin MCP tool adapter for Print & Cut registration marks."""

from __future__ import annotations

from ..services import geometry_service


def silhouette_add_registration_marks(
    design: str,
    inset_mm: float = 10.0,
    mark_size_mm: float = 5.0,
    arm_len_mm: float = 15.0,
    arm_thick_mm: float = 1.0,
    layer: str = "REGMARK",
) -> dict:
    """Add standard Silhouette Print & Cut 3-corner registration marks (top-left square,
    top-right L-bracket, bottom-left L-bracket) on layer 'REGMARK'."""
    return geometry_service.add_registration_marks(
        design=design,
        inset_mm=inset_mm,
        mark_size_mm=mark_size_mm,
        arm_len_mm=arm_len_mm,
        arm_thick_mm=arm_thick_mm,
        layer=layer,
    )
