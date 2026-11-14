"""Thin MCP tool adapters for vector primitives, transforms, offsetting, duplication, and 2D nesting."""

from __future__ import annotations

from ..services import geometry_service, nesting_service


def silhouette_add_rectangle(
    design: str,
    x_mm: float,
    y_mm: float,
    width_mm: float,
    height_mm: float,
    corner_radius_mm: float = 0,
    rotation_deg: float = 0,
    layer: str = "CUT",
    label: str = "",
) -> dict:
    """Add a rectangle whose top-left corner is at (x_mm, y_mm). corner_radius_mm > 0
    rounds the corners (clamped to half of the smaller side). rotation_deg rotates clockwise
    around the rectangle center. layer defaults to 'CUT' (or 'SCORE', 'PERF')."""
    return geometry_service.add_rectangle(
        design=design,
        x_mm=x_mm,
        y_mm=y_mm,
        width_mm=width_mm,
        height_mm=height_mm,
        corner_radius_mm=corner_radius_mm,
        rotation_deg=rotation_deg,
        layer=layer,
        label=label,
    )


def silhouette_add_circle(
    design: str, cx_mm: float, cy_mm: float, radius_mm: float, layer: str = "CUT", label: str = ""
) -> dict:
    """Add a circle centred at (cx_mm, cy_mm). Exported as a true DXF CIRCLE."""
    return geometry_service.add_circle(
        design=design, cx_mm=cx_mm, cy_mm=cy_mm, radius_mm=radius_mm, layer=layer, label=label
    )


def silhouette_add_ellipse(
    design: str, cx_mm: float, cy_mm: float, rx_mm: float, ry_mm: float,
    rotation_deg: float = 0, layer: str = "CUT", label: str = "",
) -> dict:
    """Add an ellipse centred at (cx_mm, cy_mm) with radii rx_mm (horizontal) and ry_mm
    (vertical), rotated clockwise by rotation_deg."""
    return geometry_service.add_ellipse(
        design=design,
        cx_mm=cx_mm,
        cy_mm=cy_mm,
        rx_mm=rx_mm,
        ry_mm=ry_mm,
        rotation_deg=rotation_deg,
        layer=layer,
        label=label,
    )


def silhouette_add_polygon(
    design: str, cx_mm: float, cy_mm: float, radius_mm: float, sides: int,
    rotation_deg: float = 0, layer: str = "CUT", label: str = "",
) -> dict:
    """Add a regular polygon (3-64 sides) inscribed in a circle of radius_mm, centred at
    (cx_mm, cy_mm). With rotation_deg=0 one vertex points up."""
    return geometry_service.add_polygon(
        design=design,
        cx_mm=cx_mm,
        cy_mm=cy_mm,
        radius_mm=radius_mm,
        sides=sides,
        rotation_deg=rotation_deg,
        layer=layer,
        label=label,
    )


def silhouette_add_star(
    design: str, cx_mm: float, cy_mm: float, outer_radius_mm: float, inner_radius_mm: float,
    points: int = 5, rotation_deg: float = 0, layer: str = "CUT", label: str = "",
) -> dict:
    """Add a star with the given number of points (3-64). inner_radius_mm must be smaller
    than outer_radius_mm (about 40% gives a classic star). With rotation_deg=0 one tip points up."""
    return geometry_service.add_star(
        design=design,
        cx_mm=cx_mm,
        cy_mm=cy_mm,
        outer_radius_mm=outer_radius_mm,
        inner_radius_mm=inner_radius_mm,
        points=points,
        rotation_deg=rotation_deg,
        layer=layer,
        label=label,
    )


def silhouette_add_line(
    design: str,
    x1_mm: float,
    y1_mm: float,
    x2_mm: float,
    y2_mm: float,
    dashed: bool = False,
    dash_len_mm: float = 3.0,
    gap_len_mm: float = 2.0,
    layer: str = "CUT",
    label: str = "",
) -> dict:
    """Add a straight line between (x1_mm, y1_mm) and (x2_mm, y2_mm).
    If dashed=true, creates perforated segments ideal for folding cardstock/papercraft.
    dash_len_mm: cut segment length (default 3mm); gap_len_mm: un-cut gap length (default 2mm).
    layer: 'CUT', 'SCORE', 'PERF', etc."""
    return geometry_service.add_line(
        design=design,
        x1_mm=x1_mm,
        y1_mm=y1_mm,
        x2_mm=x2_mm,
        y2_mm=y2_mm,
        dashed=dashed,
        dash_len_mm=dash_len_mm,
        gap_len_mm=gap_len_mm,
        layer=layer,
        label=label,
    )


def silhouette_add_polyline(
    design: str, points: list[list[float]], closed: bool = True, layer: str = "CUT", label: str = ""
) -> dict:
    """Add a custom path through the given [x, y] points (in mm, Y down). closed=true
    makes a closed shape (>= 3 points); closed=false makes an open line (>= 2 points)."""
    return geometry_service.add_polyline(
        design=design, points=points, closed=closed, layer=layer, label=label
    )


def silhouette_transform_shape(
    design: str,
    shape_id: int,
    dx_mm: float = 0,
    dy_mm: float = 0,
    scale: float = 1.0,
    rotation_deg: float = 0,
    flip_x: bool = False,
    flip_y: bool = False,
) -> dict:
    """Move (dx_mm, dy_mm), scale, rotate, and optionally mirror (flip_x, flip_y) an
    existing shape by its id. Scaling, flipping and rotation are centred at the shape's bbox center."""
    return geometry_service.transform_shape(
        design=design,
        shape_id=shape_id,
        dx_mm=dx_mm,
        dy_mm=dy_mm,
        scale=scale,
        rotation_deg=rotation_deg,
        flip_x=flip_x,
        flip_y=flip_y,
    )


def silhouette_offset_shape(
    design: str,
    shape_id: int,
    offset_mm: float,
    join: str = "round",
    layer: str = "",
    label: str = "",
) -> dict:
    """Create a new inward (< 0) or outward (> 0) offset contour from an existing circle or
    closed polygon (ideal for print-and-cut bleed borders, shaker frames and layered mats).
    join: 'round', 'miter', or 'bevel'."""
    return geometry_service.offset_shape(
        design=design, shape_id=shape_id, offset_mm=offset_mm, join=join, layer=layer, label=label
    )


def silhouette_duplicate_shape(
    design: str,
    shape_id: int,
    dx_mm: float = 0,
    dy_mm: float = 0,
    count: int = 1,
) -> dict:
    """Duplicate an existing shape `count` times, offsetting each consecutive copy by (dx_mm, dy_mm)."""
    return geometry_service.duplicate_shape(
        design=design, shape_id=shape_id, dx_mm=dx_mm, dy_mm=dy_mm, count=count
    )


def silhouette_grid_duplicates(
    design: str,
    shape_id: int,
    cols: int,
    rows: int,
    spacing_x_mm: float = 5.0,
    spacing_y_mm: float = 5.0,
) -> dict:
    """Arrange copies of an existing shape in a 2D cols x rows matrix (sheet nesting).
    The original shape occupies cell (0, 0) and (cols * rows - 1) copies fill the remaining cells."""
    return geometry_service.grid_duplicates(
        design=design,
        shape_id=shape_id,
        cols=cols,
        rows=rows,
        spacing_x_mm=spacing_x_mm,
        spacing_y_mm=spacing_y_mm,
    )


def silhouette_nest_shapes(
    design: str,
    shape_ids: list[int] | None = None,
    spacing_mm: float = 3.0,
    margin_mm: float = -1.0,
    allow_rotation: bool = True,
    rotation_step_deg: float = 90.0,
    dry_run: bool = False,
) -> dict:
    """Optimise 2D rectangular sheet nesting (MaxRects Best Short Side Fit) to pack shapes inside the
    usable cutting area with zero overlap and guaranteed spacing_mm clearance.
    Automatically skips and avoids any REGMARK registration marks on the page.
    Set dry_run=true to compute placement metrics without modifying shape coordinates."""
    return nesting_service.nest_shapes(
        design=design,
        shape_ids=shape_ids,
        spacing_mm=spacing_mm,
        margin_mm=margin_mm,
        allow_rotation=allow_rotation,
        rotation_step_deg=rotation_step_deg,
        dry_run=dry_run,
    )


__all__ = [
    "silhouette_add_circle",
    "silhouette_add_ellipse",
    "silhouette_add_line",
    "silhouette_add_polygon",
    "silhouette_add_polyline",
    "silhouette_add_rectangle",
    "silhouette_add_star",
    "silhouette_duplicate_shape",
    "silhouette_grid_duplicates",
    "silhouette_nest_shapes",
    "silhouette_offset_shape",
    "silhouette_transform_shape",
]
