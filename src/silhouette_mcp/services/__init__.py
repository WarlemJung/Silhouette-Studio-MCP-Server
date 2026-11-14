"""Application services layer orchestrating use cases without MCP protocol coupling."""

from ..core.models import _add_line_to_doc
from .document_service import (
    clear_shapes,
    delete_design,
    describe_design,
    get_design,
    list_designs,
    list_page_presets,
    new_design,
    remove_shape,
)
from .export_service import (
    _export,
    export_design,
    make_calibration_file,
    open_in_studio,
    render_preview,
)
from .geometry_service import (
    _pen_ops_to_contours,
    _resolve_font_path,
    add_circle,
    add_ellipse,
    add_line,
    add_polygon,
    add_polyline,
    add_rectangle,
    add_registration_marks,
    add_star,
    add_text,
    duplicate_shape,
    grid_duplicates,
    offset_shape,
    transform_shape,
)
from .import_service import DefusedET, _svg_subpaths, _validate_svg_file, import_svg
from .nesting_service import nest_shapes
from .template_service import add_box_template

__all__ = [
    "DefusedET",
    "_add_line_to_doc",
    "_export",
    "_pen_ops_to_contours",
    "_resolve_font_path",
    "_svg_subpaths",
    "_validate_svg_file",
    "add_box_template",
    "add_circle",
    "add_ellipse",
    "add_line",
    "add_polygon",
    "add_polyline",
    "add_rectangle",
    "add_registration_marks",
    "add_star",
    "add_text",
    "clear_shapes",
    "delete_design",
    "describe_design",
    "duplicate_shape",
    "export_design",
    "get_design",
    "grid_duplicates",
    "import_svg",
    "list_designs",
    "list_page_presets",
    "make_calibration_file",
    "nest_shapes",
    "new_design",
    "offset_shape",
    "open_in_studio",
    "remove_shape",
    "render_preview",
    "transform_shape",
]

