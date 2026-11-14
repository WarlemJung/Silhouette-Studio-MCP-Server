"""Thin MCP tool adapters for document lifecycle and inspection."""

from __future__ import annotations

from ..services import document_service


def silhouette_list_page_presets() -> dict:
    """List the built-in page/mat presets (name -> width/height in mm). These are page
    sizes, not the exact cutting area of the machine; keep a safety margin."""
    return document_service.list_page_presets()


def silhouette_new_design(
    name: str,
    preset: str = "mat-12x12",
    width_mm: float = 0,
    height_mm: float = 0,
    cut_margin_mm: float = 5,
    overwrite: bool = False,
) -> dict:
    """Create an empty design (the working canvas). Use a preset (see
    silhouette_list_page_presets) or give custom width_mm AND height_mm (they override
    the preset). cut_margin_mm is a safety margin used only for warnings.
    Fails if the design exists unless overwrite=true."""
    return document_service.new_design(
        name=name,
        preset=preset,
        width_mm=width_mm,
        height_mm=height_mm,
        cut_margin_mm=cut_margin_mm,
        overwrite=overwrite,
    )


def silhouette_list_designs() -> dict:
    """List the designs saved in the output folder along with exported files if any."""
    return document_service.list_designs()


def silhouette_get_design(design: str) -> dict:
    """Get the full raw JSON data of a design, including all shapes and canvas properties."""
    return document_service.get_design(design=design)


def silhouette_delete_design(design: str, delete_files: bool = False) -> dict:
    """Delete a design file. If delete_files=true, also removes any exported .dxf, .svg and .png files."""
    return document_service.delete_design(design=design, delete_files=delete_files)


def silhouette_clear_shapes(design: str) -> dict:
    """Remove all shapes from a design without resetting page dimensions."""
    return document_service.clear_shapes(design=design)


def silhouette_describe_design(design: str) -> dict:
    """Summarise a design: page size, every shape with its bounding box, overall bounds
    and any warnings (outside the page, inside the safety margin, tiny details)."""
    return document_service.describe_design(design=design)


def silhouette_remove_shape(design: str, shape_id: int) -> dict:
    """Remove one shape (by the id shown in silhouette_describe_design)."""
    return document_service.remove_shape(design=design, shape_id=shape_id)
