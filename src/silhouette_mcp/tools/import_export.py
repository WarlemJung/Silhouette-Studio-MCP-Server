"""Thin MCP tool adapters for SVG import, DXF/SVG/PNG export, calibration, and Studio launch."""

from __future__ import annotations

from ..services import export_service, import_service


def silhouette_import_svg(
    design: str,
    svg_path: str,
    target_width_mm: float = 0,
    target_height_mm: float = 0,
    x_mm: float = 0,
    y_mm: float = 0,
    rotation_deg: float = 0,
    layer: str = "CUT",
) -> dict:
    """Read an SVG file from disk, convert outlines (curves flattened to mm segments)
    and add them to the design for DXF export. This bridges SVG artwork into Silhouette Studio
    Standard Edition (which cannot open SVG natively).
    target_width_mm / target_height_mm > 0 scale artwork (uniformly if only one is given);
    artwork's top-left corner is placed at (x_mm, y_mm).
    Text and embedded images are skipped (convert text to outlines or use silhouette_add_text)."""
    return import_service.import_svg(
        design=design,
        svg_path=svg_path,
        target_width_mm=target_width_mm,
        target_height_mm=target_height_mm,
        x_mm=x_mm,
        y_mm=y_mm,
        rotation_deg=rotation_deg,
        layer=layer,
    )


def silhouette_export(design: str, formats: str = "dxf,svg", filename: str = "") -> dict:
    """Export the design to cut/preview files in the output folder. formats is a comma-separated
    list of 'dxf', 'svg', and/or 'png'. DXF is required for the free Standard Edition.
    filename (optional) overrides the base file name. Returns file paths, bounds and warnings."""
    return export_service.export_design(design=design, formats=formats, filename=filename)


def silhouette_render_preview(design: str, dpi: int = 150, filename: str = "") -> dict:
    """Render a colour-coded PNG preview of the design (with 10 mm grid and safety margin)
    for visual inspection before cutting. Returns the PNG path, pixel dimensions and warnings."""
    return export_service.render_preview(design=design, dpi=dpi, filename=filename)


def silhouette_make_calibration_file() -> dict:
    """Create and export a calibration DXF: a 100 x 100 mm square with a 50 mm circle,
    a 40 x 20 mm rounded rectangle, and a 100 mm perforated score line. Open it in Studio and measure it:
    if the square is not 100 mm (3.937 in), set Studio Preferences > Import Options > DXF to 'As-is'."""
    return export_service.make_calibration_file()


def silhouette_open_in_studio(path: str, reveal_in_explorer: bool = False) -> dict:
    """Open a cut file previously exported (.dxf or .svg) directly in Silhouette Studio.
    Accepts full paths, paths relative to the output folder, or just design/file names.
    Set reveal_in_explorer=true to also select the file in Windows Explorer."""
    return export_service.open_in_studio(path=path, reveal_in_explorer=reveal_in_explorer)


__all__ = [
    "silhouette_export",
    "silhouette_import_svg",
    "silhouette_make_calibration_file",
    "silhouette_open_in_studio",
    "silhouette_render_preview",
]
