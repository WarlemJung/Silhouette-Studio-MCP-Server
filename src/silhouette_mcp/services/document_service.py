"""Document lifecycle and inspection service layer."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ..config.settings import MAX_PAGE_MM, MIN_PAGE_MM, PRESETS, get_runtime_attr
from ..core.exceptions import SilhouetteValueError
from ..core.models import _bbox, _shape_warnings, _union_bbox
from ..core.validators import _int, _num, _pos, _r4, _slug
from ..persistence.repository import load_design, save_design
from ..persistence.storage import _LOCK, _backup_path, _design_path


def list_page_presets() -> dict[str, Any]:
    """Return built-in page/mat presets mapped to `{width_mm, height_mm}`."""
    return {k: {"width_mm": v[0], "height_mm": v[1]} for k, v in PRESETS.items()}


def new_design(
    name: str,
    preset: str = "mat-12x12",
    width_mm: float = 0,
    height_mm: float = 0,
    cut_margin_mm: float = 5,
    overwrite: bool = False,
) -> dict[str, Any]:
    """Create and persist an empty design canvas with validated dimensions and margins."""
    if width_mm or height_mm:
        _pos(width_mm=width_mm, height_mm=height_mm)
        width, height = float(width_mm), float(height_mm)
        if not (MIN_PAGE_MM <= width <= MAX_PAGE_MM and MIN_PAGE_MM <= height <= MAX_PAGE_MM):
            raise SilhouetteValueError(
                f"width_mm and height_mm must be between {MIN_PAGE_MM} and {MAX_PAGE_MM} mm"
            )
    else:
        if preset not in PRESETS:
            raise SilhouetteValueError(f"Unknown preset '{preset}'. Options: {', '.join(PRESETS)}")
        width, height = PRESETS[preset]

    _num(cut_margin_mm=cut_margin_mm)
    if cut_margin_mm < 0 or cut_margin_mm * 2 >= min(width, height):
        raise SilhouetteValueError("cut_margin_mm must be >= 0 and smaller than half of the page")

    out_dir: Path = get_runtime_attr("OUTPUT_DIR")
    with _LOCK:
        if _design_path(name).exists() and not overwrite:
            raise SilhouetteValueError(f"Design '{name}' already exists. Use overwrite=true or another name.")
        doc = {
            "name": _slug(name),
            "width_mm": width,
            "height_mm": height,
            "cut_margin_mm": float(cut_margin_mm),
            "next_id": 1,
            "revision": 0,
            "shapes": [],
        }
        save_design(doc)
        return {"design": doc["name"], "width_mm": width, "height_mm": height, "folder": str(out_dir)}


def list_designs() -> dict[str, Any]:
    """List saved `.design.json` files in OUTPUT_DIR and their exported sidecars."""
    out_dir: Path = get_runtime_attr("OUTPUT_DIR")
    with _LOCK:
        out: list[dict[str, Any]] = []
        if out_dir.exists():
            for path in sorted(out_dir.glob("*.design.json")):
                try:
                    doc = json.loads(path.read_text(encoding="utf-8"))
                    name = doc["name"]
                    has_dxf = (out_dir / f"{name}.dxf").is_file()
                    has_svg = (out_dir / f"{name}.svg").is_file()
                    has_png = (out_dir / f"{name}.png").is_file()
                    out.append({
                        "design": name,
                        "shapes": len(doc["shapes"]),
                        "width_mm": doc["width_mm"],
                        "height_mm": doc["height_mm"],
                        "dxf_exported": has_dxf,
                        "svg_exported": has_svg,
                        "png_exported": has_png,
                    })
                except Exception as exc:
                    out.append({"file": path.name, "error": str(exc)})
        return {"folder": str(out_dir), "designs": out}


def get_design(design: str) -> dict[str, Any]:
    """Load and return the full design JSON dictionary."""
    return load_design(design)


def delete_design(design: str, delete_files: bool = False) -> dict[str, Any]:
    """Delete a design JSON, its backup, and optionally its exported artifacts."""
    out_dir: Path = get_runtime_attr("OUTPUT_DIR")
    with _LOCK:
        slug = _slug(design)
        path = _design_path(slug)
        bak = _backup_path(slug)
        if not path.exists() and not bak.exists():
            raise SilhouetteValueError(f"Design '{design}' does not exist.")
        deleted_files: list[str] = []
        if path.exists():
            path.unlink()
            deleted_files.append(str(path))
        if bak.exists():
            bak.unlink()
            deleted_files.append(str(bak))
        if delete_files:
            for ext in (".dxf", ".svg", ".png"):
                ef = out_dir / f"{slug}{ext}"
                if ef.exists():
                    ef.unlink()
                    deleted_files.append(str(ef))
        return {"deleted_design": slug, "deleted_files": deleted_files}


def clear_shapes(design: str) -> dict[str, Any]:
    """Remove all shapes from an existing design without modifying page geometry."""
    with _LOCK:
        doc = load_design(design)
        removed_count = len(doc["shapes"])
        doc["shapes"] = []
        save_design(doc)
        return {"design": doc["name"], "shapes_removed": removed_count, "shape_count": 0}


def describe_design(design: str) -> dict[str, Any]:
    """Summarize page bounds, shapes, bounding boxes, and placement/cut warnings."""
    doc = load_design(design)
    shapes: list[dict[str, Any]] = []
    layers: dict[str, int] = {}
    warns: list[str] = []
    for s in doc["shapes"]:
        layer_name = s.get("layer", "CUT")
        layers[layer_name] = layers.get(layer_name, 0) + 1
        shapes.append({
            "id": s["id"],
            "label": s["label"],
            "layer": layer_name,
            "kind": s["kind"],
            "bbox_mm": _r4(_bbox(s)),
            **({"closed": s["closed"]} if s["kind"] == "poly" else {}),
        })
        for w in _shape_warnings(doc, s):
            warns.append(f"shape {s['id']} ({s['label']}): {w}")
    return {
        "design": doc["name"],
        "revision": doc.get("revision", 1),
        "width_mm": doc["width_mm"],
        "height_mm": doc["height_mm"],
        "cut_margin_mm": doc["cut_margin_mm"],
        "shape_count": len(shapes),
        "layers": layers,
        "overall_bbox_mm": _r4(_union_bbox(doc["shapes"])),
        "shapes": shapes,
        "warnings": warns,
    }


def remove_shape(design: str, shape_id: int) -> dict[str, Any]:
    """Remove a single shape identified by `shape_id`."""
    _int(shape_id=shape_id)
    with _LOCK:
        doc = load_design(design)
        before = len(doc["shapes"])
        doc["shapes"] = [s for s in doc["shapes"] if s["id"] != shape_id]
        if len(doc["shapes"]) == before:
            raise SilhouetteValueError(f"No shape with id {shape_id}")
        save_design(doc)
        return {"design": doc["name"], "removed": shape_id, "shape_count": len(doc["shapes"])}

