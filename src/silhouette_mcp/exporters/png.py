"""Color-coded PNG visual preview renderer with 10 mm grid and safety margin overlay."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from ..config.settings import SVG_LAYER_COLORS, _DASHED_PREVIEW_LAYERS
from ..core.geometry_engine import _dedupe_closed
from ..persistence.storage import _atomic_write_file


def _draw_dashed_segment(
    draw: Any, p0: tuple[float, float], p1: tuple[float, float], fill: str, width: int, dash_px: float = 10.0, gap_px: float = 6.0
) -> None:
    dist = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if dist <= 1e-3:
        return
    dx, dy = (p1[0] - p0[0]) / dist, (p1[1] - p0[1]) / dist
    t = 0.0
    step = dash_px + gap_px
    while t < dist:
        t1 = min(t + dash_px, dist)
        draw.line([(p0[0] + dx * t, p0[1] + dy * t), (p0[0] + dx * t1, p0[1] + dy * t1)], fill=fill, width=width)
        t += step


def _write_png(d: dict, path: Path, dpi: int = 150) -> tuple[int, int]:
    from PIL import Image as PilImage, ImageDraw

    dpi_clamped = max(36, min(600, int(dpi)))
    W, H = float(d["width_mm"]), float(d["height_mm"])
    scale = dpi_clamped / 25.4
    max_dim = max(W * scale, H * scale)
    if max_dim > 2400:
        scale *= 2400.0 / max_dim
    elif max_dim < 200:
        scale *= 200.0 / max_dim

    w_px = max(1, int(round(W * scale)))
    h_px = max(1, int(round(H * scale)))
    img = PilImage.new("RGB", (w_px, h_px), "#ffffff")
    draw = ImageDraw.Draw(img)

    # Grade de fundo 10 mm
    gx = 10.0
    while gx < W:
        px = gx * scale
        draw.line([(px, 0), (px, h_px)], fill="#f0f2f5", width=1)
        gx += 10.0
    gy = 10.0
    while gy < H:
        py = gy * scale
        draw.line([(0, py), (w_px, py)], fill="#f0f2f5", width=1)
        gy += 10.0

    # Margem de seguranca
    m = float(d.get("cut_margin_mm", 5.0))
    if m > 0:
        mx0, my0, mx1, my1 = m * scale, m * scale, (W - m) * scale, (H - m) * scale
        for a, b in (((mx0, my0), (mx1, my0)), ((mx1, my0), (mx1, my1)), ((mx1, my1), (mx0, my1)), ((mx0, my1), (mx0, my0))):
            _draw_dashed_segment(draw, a, b, "#d9b38c", 1, dash_px=8.0, gap_px=6.0)

    stroke_w = max(1, int(round(scale * 0.35)))
    for s in d["shapes"]:
        layer = s.get("layer", "CUT").upper()
        color = SVG_LAYER_COLORS.get(layer, "#000000")
        dashed = layer in _DASHED_PREVIEW_LAYERS
        if s["kind"] == "circle":
            cx, cy, r = s["cx"] * scale, s["cy"] * scale, s["r"] * scale
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=stroke_w)
        else:
            raw_pts = _dedupe_closed(s["points"]) if s["closed"] else s["points"]
            pts_px = [(x * scale, y * scale) for x, y in raw_pts]
            if len(pts_px) < 2:
                continue
            segs = list(zip(pts_px, pts_px[1:]))
            if s["closed"] and len(pts_px) >= 3:
                segs.append((pts_px[-1], pts_px[0]))
            for p0, p1 in segs:
                if dashed:
                    _draw_dashed_segment(draw, p0, p1, color, stroke_w)
                else:
                    draw.line([p0, p1], fill=color, width=stroke_w)

    _atomic_write_file(path, ".png.tmp", lambda tmp: img.save(tmp, format="PNG"))
    return w_px, h_px

