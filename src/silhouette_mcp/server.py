#!/usr/bin/env python3
"""MCP server instance and public exports for Silhouette Studio MCP."""

from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

_SRC_DIR = str(Path(__file__).resolve().parent.parent)
if _SRC_DIR not in sys.path:
    sys.path.insert(0, _SRC_DIR)

if sys.platform.startswith("win"):
    import msvcrt

from silhouette_mcp.config.settings import (  # noqa: E402
    DXF_VERSION,
    INSTRUCTIONS,
    LOCK_TIMEOUT_S,
    MAX_SHAPES,
    MAX_SVG_BYTES,
    MAX_SVG_DEPTH,
    MAX_SVG_ELEMENTS,
    MAX_SVG_TOTAL_POINTS,
    MAX_TEXT_LENGTH,
    OUTPUT_DIR,
    STUDIO_EXE,
    _FONT_DIRS,
    logger,
)
from silhouette_mcp.core.exceptions import (  # noqa: E402
    _MCP_V2,
    FastMCP,
    SilhouetteRuntimeError,
    SilhouetteValueError,
    ToolError,
    _ann,
)
from silhouette_mcp.core.geometry_engine import (  # noqa: E402
    _arc,
    _clean_polygon,
    _has_self_intersection,
    _offset_polygon,
    _point_in_polygon,
    _point_to_polygon_dist,
    _point_to_segment_dist,
    _polygon_area2,
    _rotate,
    _rounded_rect,
    _segments_intersect,
)
from silhouette_mcp.core.models import _bbox, _union_bbox  # noqa: E402
from silhouette_mcp.core.validators import _fmt, _num, _pos, _slug, _validate_design_dict  # noqa: E402
from silhouette_mcp.integrations.silhouette_studio import _find_studio_exe  # noqa: E402
from silhouette_mcp.persistence.repository import _save  # noqa: E402
from silhouette_mcp.persistence.storage import _InterProcessLock, _atomic_replace, _atomic_write_file  # noqa: E402
from silhouette_mcp.tools.document import (  # noqa: E402
    silhouette_clear_shapes,
    silhouette_delete_design,
    silhouette_describe_design,
    silhouette_get_design,
    silhouette_list_designs,
    silhouette_list_page_presets,
    silhouette_new_design,
    silhouette_remove_shape,
)
from silhouette_mcp.tools.geometry import (  # noqa: E402
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
from silhouette_mcp.tools.import_export import (  # noqa: E402
    silhouette_export,
    silhouette_import_svg,
    silhouette_make_calibration_file,
    silhouette_open_in_studio,
    silhouette_render_preview,
)
from silhouette_mcp.services.geometry_service import _pen_ops_to_contours, _resolve_font_path  # noqa: E402
from silhouette_mcp.tools.registration import silhouette_add_registration_marks  # noqa: E402
from silhouette_mcp.tools.templates import silhouette_add_box_template  # noqa: E402
from silhouette_mcp.tools.text import silhouette_add_text  # noqa: E402

if _MCP_V2:
    mcp = FastMCP("silhouette-studio", instructions=INSTRUCTIONS, version="1.1.0")
else:  # pragma: no cover
    mcp = FastMCP("silhouette-studio", instructions=INSTRUCTIONS)

TOOL_REGISTRATIONS: list[tuple[Any, dict[str, bool]]] = [
    (silhouette_list_page_presets, {"read_only": True, "idempotent": True}),
    (silhouette_new_design, {"destructive": True, "idempotent": True}),
    (silhouette_list_designs, {"read_only": True, "idempotent": True}),
    (silhouette_get_design, {"read_only": True, "idempotent": True}),
    (silhouette_delete_design, {"destructive": True}),
    (silhouette_clear_shapes, {"destructive": True, "idempotent": True}),
    (silhouette_add_rectangle, {}),
    (silhouette_add_circle, {}),
    (silhouette_add_ellipse, {}),
    (silhouette_add_polygon, {}),
    (silhouette_add_star, {}),
    (silhouette_add_line, {}),
    (silhouette_add_polyline, {}),
    (silhouette_add_text, {}),
    (silhouette_transform_shape, {}),
    (silhouette_offset_shape, {}),
    (silhouette_duplicate_shape, {}),
    (silhouette_grid_duplicates, {}),
    (silhouette_nest_shapes, {}),
    (silhouette_add_registration_marks, {}),
    (silhouette_add_box_template, {}),
    (silhouette_import_svg, {}),
    (silhouette_describe_design, {"read_only": True, "idempotent": True}),
    (silhouette_remove_shape, {"destructive": True}),
    (silhouette_export, {"idempotent": True}),
    (silhouette_render_preview, {"idempotent": True}),
    (silhouette_make_calibration_file, {"idempotent": True}),
    (silhouette_open_in_studio, {"open_world": True}),
]


def register_tools(server_instance: Any = mcp) -> Any:
    """Register all 28 domain MCP tools onto a FastMCP / MCPServer instance."""
    for fn, ann_kwargs in TOOL_REGISTRATIONS:
        server_instance.tool(annotations=_ann(**ann_kwargs))(fn)
    return server_instance


register_tools(mcp)


def main() -> None:  # pragma: no cover
    """Run the Silhouette Studio MCP server over stdio transport."""
    mcp.run()


if __name__ == "__main__":  # pragma: no cover
    main()
