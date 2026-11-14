"""Grouped SVG exporter preserving millimetre units and sanitized layer IDs."""

from __future__ import annotations

import re
from pathlib import Path

from ..config.settings import SVG_LAYER_COLORS, _DASHED_PREVIEW_LAYERS
from ..core.geometry_engine import _dedupe_closed
from ..core.validators import _fmt
from ..persistence.storage import _atomic_write_file


def _write_svg(d: dict, path: Path) -> None:
    W, H = d["width_mm"], d["height_mm"]
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_fmt(W)}mm" height="{_fmt(H)}mm" '
        f'viewBox="0 0 {_fmt(W)} {_fmt(H)}" fill="none" stroke-width="0.3">'
    ]
    # Agrupa por camada para organizacao visual e selecao facil
    shapes_by_layer: dict[str, list[dict]] = {}
    for s in d["shapes"]:
        layer = s.get("layer", "CUT").upper()
        shapes_by_layer.setdefault(layer, []).append(s)

    for layer, shapes in shapes_by_layer.items():
        color = SVG_LAYER_COLORS.get(layer, "#000000")
        dash = ' stroke-dasharray="3,2"' if layer in _DASHED_PREVIEW_LAYERS else ""
        safe_layer = re.sub(r"[^A-Za-z0-9_-]+", "-", layer).strip("-") or "LAYER"
        out.append(f'  <g id="{safe_layer}" stroke="{color}"{dash}>')
        for s in shapes:
            if s["kind"] == "circle":
                out.append(f'    <circle cx="{_fmt(s["cx"])}" cy="{_fmt(s["cy"])}" r="{_fmt(s["r"])}"/>')
            else:
                raw_pts = _dedupe_closed(s["points"]) if s["closed"] else s["points"]
                pts = " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in raw_pts)
                tag = "polygon" if s["closed"] else "polyline"
                out.append(f'    <{tag} points="{pts}"/>')
        out.append("  </g>")
    out.append("</svg>")
    content = "\n".join(out)
    _atomic_write_file(path, ".svg.tmp", lambda tmp: tmp.write_text(content, encoding="utf-8"))

