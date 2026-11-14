"""Export, PNG preview rendering, calibration file, and Silhouette Studio launch service."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ..config.settings import get_runtime_attr
from ..core.exceptions import SilhouetteValueError
from ..core.geometry_engine import _rounded_rect
from ..core.models import _shape_warnings, _union_bbox
from ..core.validators import _int, _r4, _slug
from ..exporters.dxf import _write_dxf
from ..exporters.png import _write_png
from ..exporters.svg import _write_svg
from ..integrations.silhouette_studio import silhouette_open_in_studio as _open_in_studio_impl
from ..persistence.repository import load_design, save_design
from ..persistence.storage import _LOCK


def _export(d: dict[str, Any], formats: str, filename: str = "") -> dict[str, Any]:
    """Write requested DXF/SVG/PNG formats for an in-memory design dictionary."""
    if not d["shapes"]:
        raise SilhouetteValueError("The design has no shapes to export.")
    wanted = [f.strip().lower() for f in formats.split(",") if f.strip()]
    if not wanted or any(f not in ("dxf", "svg", "png") for f in wanted):
        raise SilhouetteValueError("formats must be a comma-separated list of: dxf, svg, png")
    out_dir: Path = get_runtime_attr("OUTPUT_DIR")
    dxf_version = str(get_runtime_attr("DXF_VERSION"))
    base = _slug(filename) if filename else d["name"]
    out_dir.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for fmt in dict.fromkeys(wanted):
        path = out_dir / f"{base}.{fmt}"
        if fmt == "dxf":
            _write_dxf(d, path)
        elif fmt == "svg":
            _write_svg(d, path)
        else:
            _write_png(d, path)
        files[fmt] = str(path)
    warns = [f"shape {s['id']} ({s['label']}): {w}" for s in d["shapes"] for w in _shape_warnings(d, s)]
    notes = [
        "Open the DXF in Silhouette Studio with File > Open (works in the free Standard/Basic edition).",
        "Layers (CUT=red, SCORE=blue, PERF=green, ENGRAVE=cyan, REGMARK=black) allow setting separate blade actions in Studio's 'Send by Layer/Line' tab.",
        "Check calibration after first import: in Studio Preferences > Import Options > DXF set to 'As-is'.",
    ]
    if "svg" in files:
        notes.append("The SVG is a preview/exchange file: Studio only opens SVG in Designer Edition or higher.")
    return {
        "files": files,
        "dxf_version": dxf_version,
        "shape_count": len(d["shapes"]),
        "bbox_mm": _r4(_union_bbox(d["shapes"])),
        "warnings": warns,
        "notes": notes,
    }


def export_design(design: str, formats: str = "dxf,svg", filename: str = "") -> dict[str, Any]:
    """Load a design under lock and export it to the requested cut/preview formats."""
    with _LOCK:
        return _export(load_design(design), formats, filename)


def render_preview(design: str, dpi: int = 150, filename: str = "") -> dict[str, Any]:
    """Render a color-coded PNG preview for visual verification before cutting."""
    _int(dpi=dpi)
    if dpi < 36 or dpi > 600:
        raise SilhouetteValueError("dpi must be between 36 and 600")
    out_dir: Path = get_runtime_attr("OUTPUT_DIR")
    with _LOCK:
        doc = load_design(design)
        if not doc["shapes"]:
            raise SilhouetteValueError("The design has no shapes to export.")
        base = _slug(filename) if filename else doc["name"]
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{base}.png"
        w_px, h_px = _write_png(doc, out_path, dpi=dpi)
        warns = [f"shape {s['id']} ({s['label']}): {w}" for s in doc["shapes"] for w in _shape_warnings(doc, s)]
        return {
            "design": doc["name"],
            "png_path": str(out_path),
            "width_px": w_px,
            "height_px": h_px,
            "bbox_mm": _r4(_union_bbox(doc["shapes"])),
            "warnings": warns,
        }


def make_calibration_file() -> dict[str, Any]:
    """Generate and export the standard 100 x 100 mm DXF calibration design."""
    shapes: list[dict[str, Any]] = [
        {
            "id": 1,
            "label": "square-100mm",
            "kind": "poly",
            "closed": True,
            "layer": "CUT",
            "points": [[20, 20], [120, 20], [120, 120], [20, 120]],
        },
        {
            "id": 2,
            "label": "circle-50mm",
            "kind": "circle",
            "cx": 70,
            "cy": 70,
            "r": 25,
            "layer": "CUT",
        },
        {
            "id": 3,
            "label": "pill-40x20",
            "kind": "poly",
            "closed": True,
            "layer": "CUT",
            "points": [[round(a, 4), round(b, 4)] for a, b in _rounded_rect(20, 140, 40, 20, 5)],
        },
    ]
    cursor = 20.0
    idx = 4
    while cursor < 120.0:
        t_end = min(cursor + 4.0, 120.0)
        shapes.append({
            "id": idx,
            "label": f"score-dash#{idx - 3}",
            "kind": "poly",
            "closed": False,
            "layer": "SCORE",
            "points": [[cursor, 70], [t_end, 70]],
        })
        idx += 1
        cursor += 6.0

    doc = {
        "name": "calibration-100mm",
        "width_mm": 304.8,
        "height_mm": 304.8,
        "cut_margin_mm": 5.0,
        "next_id": idx,
        "shapes": shapes,
    }
    with _LOCK:
        save_design(doc)
        res = _export(doc, "dxf")
    res["expected"] = (
        "Square = 100 x 100 mm; circle diameter = 50 mm; pill = 40 x 20 mm; center score line = 100 mm dashed."
    )
    return res


def open_in_studio(path: str, reveal_in_explorer: bool = False) -> dict[str, Any]:
    """Open an exported cut file in Silhouette Studio via desktop integration."""
    return _open_in_studio_impl(path=path, reveal_in_explorer=reveal_in_explorer)

