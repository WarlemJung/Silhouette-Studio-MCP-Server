"""Public MCP tool adapters grouped by functional domain."""

from .document import (
    silhouette_clear_shapes,
    silhouette_delete_design,
    silhouette_describe_design,
    silhouette_get_design,
    silhouette_list_designs,
    silhouette_list_page_presets,
    silhouette_new_design,
    silhouette_remove_shape,
)
from .geometry import (
    silhouette_add_circle,
    silhouette_add_ellipse,
    silhouette_add_line,
    silhouette_add_polygon,
    silhouette_add_polyline,
    silhouette_add_rectangle,
    silhouette_add_star,
    silhouette_duplicate_shape,
    silhouette_grid_duplicates,
    silhouette_nest_shapes,
    silhouette_offset_shape,
    silhouette_transform_shape,
)
from .import_export import (
    silhouette_export,
    silhouette_import_svg,
    silhouette_make_calibration_file,
    silhouette_open_in_studio,
    silhouette_render_preview,
)
from .registration import silhouette_add_registration_marks
from .templates import silhouette_add_box_template
from .text import silhouette_add_text

__all__ = [
    "silhouette_add_box_template",
    "silhouette_add_circle",
    "silhouette_add_ellipse",
    "silhouette_add_line",
    "silhouette_add_polygon",
    "silhouette_add_polyline",
    "silhouette_add_rectangle",
    "silhouette_add_registration_marks",
    "silhouette_add_star",
    "silhouette_add_text",
    "silhouette_clear_shapes",
    "silhouette_delete_design",
    "silhouette_describe_design",
    "silhouette_duplicate_shape",
    "silhouette_export",
    "silhouette_get_design",
    "silhouette_grid_duplicates",
    "silhouette_import_svg",
    "silhouette_list_designs",
    "silhouette_list_page_presets",
    "silhouette_make_calibration_file",
    "silhouette_nest_shapes",
    "silhouette_new_design",
    "silhouette_offset_shape",
    "silhouette_open_in_studio",
    "silhouette_remove_shape",
    "silhouette_render_preview",
    "silhouette_transform_shape",
]
