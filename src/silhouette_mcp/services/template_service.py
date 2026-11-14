"""Parametric packaging and papercraft dieline builders and template service."""

from __future__ import annotations

import copy
import math
from typing import Any

from ..core.exceptions import SilhouetteValueError
from ..core.geometry_engine import _eval_cubic, _rounded_rect
from ..core.models import _add_line_to_doc, _append_shape_in_memory, _bbox, _shape_warnings, _union_bbox
from ..core.validators import _num, _pos, _r4
from ..persistence.repository import load_design, save_design
from ..persistence.storage import _LOCK


def _milk_arch_pts(x0: float, y_peak: float, y_valley: float, width: float) -> list[tuple[float, float]]:
    w = width
    dy = y_valley - y_peak
    pts: list[tuple[float, float]] = [(x0, y_valley)]
    pts += _eval_cubic(
        (x0, y_valley),
        (x0 + w * 0.08, y_valley - dy * 0.6),
        (x0 + w * 0.18, y_valley - dy * 0.6),
        (x0 + w * 0.25, y_valley - dy * 0.29),
        8,
    )
    pts += _eval_cubic(
        (x0 + w * 0.25, y_valley - dy * 0.29),
        (x0 + w * 0.33, y_peak + dy * 0.04),
        (x0 + w * 0.40, y_peak),
        (x0 + w * 0.50, y_peak),
        10,
    )
    pts += _eval_cubic(
        (x0 + w * 0.50, y_peak),
        (x0 + w * 0.60, y_peak),
        (x0 + w * 0.67, y_peak + dy * 0.04),
        (x0 + w * 0.75, y_valley - dy * 0.29),
        10,
    )
    pts += _eval_cubic(
        (x0 + w * 0.75, y_valley - dy * 0.29),
        (x0 + w * 0.82, y_valley - dy * 0.6),
        (x0 + w * 0.92, y_valley - dy * 0.6),
        (x0 + w, y_valley),
        8,
    )
    return pts


def _build_milk_box(
    d: dict[str, Any],
    *,
    luxo: bool,
    x_mm: float,
    y_mm: float,
    width_mm: float,
    depth_mm: float,
    body_height_mm: float,
    dashed_score: bool,
) -> list[dict[str, Any]]:
    g = max(8.0, min(15.0, width_mm * 0.2))
    h_fin = 18.0
    h_slope = max(depth_mm * 0.65, depth_mm * 0.5 + 6.0)
    h_bot = max(18.0, min(depth_mm * 0.55, 36.0))

    x_tab = x_mm
    x1 = x_tab + g
    x2 = x1 + width_mm
    x3 = x2 + depth_mm
    x4 = x3 + width_mm
    x5 = x4 + depth_mm

    y_top = y_mm
    y_fin_base = y_top + h_fin
    y_roof_base = y_fin_base + h_slope
    y_body_base = y_roof_base + body_height_mm
    y_bot_main = y_body_base + h_bot
    y_bot_side = y_body_base + max(16.0, h_bot - 4.0)

    y_valley = y_top + 4.5 if luxo else y_top
    y_gusset = y_top + 6.5 if luxo else y_top

    outline: list[tuple[float, float]] = []
    if luxo:
        outline += _milk_arch_pts(x1, y_top, y_valley, width_mm)
        outline += [(x2, y_gusset), (x3, y_gusset)]
        outline += _milk_arch_pts(x3, y_top, y_valley, width_mm)
        outline += [(x4, y_gusset), (x5 - 2.0, y_gusset), (x5, y_gusset + 2.0)]
    else:
        outline += [(x1, y_top), (x5, y_top)]

    outline.append((x5, y_body_base))
    outline += [(x5 - 1.0, y_body_base), (x5 - 5.0, y_bot_side), (x4 + 5.0, y_bot_side), (x4 + 1.0, y_body_base)]
    outline += [(x4 - 1.0, y_body_base), (x4 - 4.0, y_bot_main), (x3 + 4.0, y_bot_main), (x3 + 1.0, y_body_base)]
    outline += [(x3 - 1.0, y_body_base), (x3 - 5.0, y_bot_side), (x2 + 5.0, y_bot_side), (x2 + 1.0, y_body_base)]
    outline += [(x2 - 1.0, y_body_base), (x2 - 4.0, y_bot_main), (x1 + 4.0, y_bot_main), (x1 + 1.0, y_body_base)]
    chamfer = min(10.0, g)
    outline += [(x1, y_body_base), (x_tab, y_body_base - chamfer), (x_tab, y_gusset + chamfer), (x1, y_gusset)]

    added: list[dict[str, Any]] = []
    added.append(_append_shape_in_memory(d, "milk-contorno", kind="poly", closed=True, points=outline, layer="CUT"))

    if luxo:
        slot_w, slot_h = 3.0, min(8.0, h_fin - 8.0)
        slot_y = y_top + 6.5
        dx_slot = min(11.0, width_mm * 0.2)
        for panel_cx, pname in ((x1 + width_mm / 2, "frente"), (x3 + width_mm / 2, "costas")):
            for sx, sname in ((panel_cx - dx_slot - slot_w / 2, "esq"), (panel_cx + dx_slot - slot_w / 2, "dir")):
                pts = _rounded_rect(sx, slot_y, slot_w, slot_h, 1.2)
                added.append(_append_shape_in_memory(d, f"rasgo-fita-{pname}-{sname}", kind="poly", closed=True, points=pts, layer="CUT"))
    else:
        for panel_cx, pname in ((x1 + width_mm / 2, "frente"), (x3 + width_mm / 2, "costas")):
            added.append(_append_shape_in_memory(d, f"furo-fita-{pname}", kind="circle", cx=panel_cx, cy=y_top + h_fin / 2, r=2.25, layer="CUT"))

    vincos_spec = [
        (x1, y_gusset, x1, y_body_base, "vinco-aba-cola"),
        (x2, y_gusset, x2, y_body_base, "vinco-p1-p2"),
        (x3, y_gusset, x3, y_body_base, "vinco-p2-p3"),
        (x4, y_gusset, x4, y_body_base, "vinco-p3-p4"),
        (x1, y_fin_base, x5, y_fin_base, "vinco-topo-aba"),
        (x1, y_roof_base, x5, y_roof_base, "vinco-topo-corpo"),
        (x1 + 1.0, y_body_base, x2 - 1.0, y_body_base, "vinco-fundo-p1"),
        (x2 + 1.0, y_body_base, x3 - 1.0, y_body_base, "vinco-fundo-p2"),
        (x3 + 1.0, y_body_base, x4 - 1.0, y_body_base, "vinco-fundo-p3"),
        (x4 + 1.0, y_body_base, x5 - 1.0, y_body_base, "vinco-fundo-p4"),
        (x2 + depth_mm / 2, y_gusset, x2 + depth_mm / 2, y_roof_base, "vinco-fole-dir-centro"),
        (x2, y_roof_base, x2 + depth_mm / 2, y_fin_base, "vinco-fole-dir-diag1"),
        (x3, y_roof_base, x2 + depth_mm / 2, y_fin_base, "vinco-fole-dir-diag2"),
        (x4 + depth_mm / 2, y_gusset, x4 + depth_mm / 2, y_roof_base, "vinco-fole-esq-centro"),
        (x4, y_roof_base, x4 + depth_mm / 2, y_fin_base, "vinco-fole-esq-diag1"),
        (x5, y_roof_base, x4 + depth_mm / 2, y_fin_base, "vinco-fole-esq-diag2"),
    ]
    for x1_s, y1_s, x2_s, y2_s, lbl in vincos_spec:
        added.extend(_add_line_to_doc(
            d, x1_s, y1_s, x2_s, y2_s,
            dashed=dashed_score, dash_len_mm=3.5, gap_len_mm=2.0, layer="SCORE", label=lbl
        ))
    return added


def _build_cube_box(
    d: dict[str, Any],
    *,
    x_mm: float,
    y_mm: float,
    width_mm: float,
    depth_mm: float,
    body_height_mm: float,
    dashed_score: bool,
) -> list[dict[str, Any]]:
    g = max(8.0, min(14.0, width_mm * 0.2))
    tuck_h = max(12.0, min(16.0, depth_mm * 0.25))
    dust_h = max(16.0, min(depth_mm * 0.55, 36.0))
    bot_h = max(18.0, min(depth_mm * 0.65, 42.0))

    x_tab = x_mm
    x1 = x_tab + g
    x2 = x1 + width_mm
    x3 = x2 + depth_mm
    x4 = x3 + width_mm
    x5 = x4 + depth_mm

    y_top = y_mm
    y_lid_fold = y_top + tuck_h
    y_body_top = y_lid_fold + depth_mm
    y_body_bot = y_body_top + body_height_mm
    y_bot_end = y_body_bot + bot_h

    outline = [
        (x1, y_body_top), (x2, y_body_top),
        (x2 + 1.0, y_body_top), (x2 + 4.0, y_body_top - dust_h), (x3 - 4.0, y_body_top - dust_h), (x3 - 1.0, y_body_top),
        (x3, y_body_top),
        (x3, y_lid_fold), (x3 + 4.0, y_top), (x4 - 4.0, y_top), (x4, y_lid_fold), (x4, y_body_top),
        (x4 + 1.0, y_body_top), (x4 + 4.0, y_body_top - dust_h), (x5 - 4.0, y_body_top - dust_h), (x5 - 1.0, y_body_top),
        (x5, y_body_top), (x5, y_body_bot),
        (x5 - 1.0, y_body_bot), (x5 - 4.0, y_bot_end), (x4 + 4.0, y_bot_end), (x4 + 1.0, y_body_bot),
        (x4 - 1.0, y_body_bot), (x4 - 4.0, y_bot_end), (x3 + 4.0, y_bot_end), (x3 + 1.0, y_body_bot),
        (x3 - 1.0, y_body_bot), (x3 - 4.0, y_bot_end), (x2 + 4.0, y_bot_end), (x2 + 1.0, y_body_bot),
        (x2 - 1.0, y_body_bot), (x2 - 4.0, y_bot_end), (x1 + 4.0, y_bot_end), (x1 + 1.0, y_body_bot),
        (x1, y_body_bot),
        (x_tab, y_body_bot - 8.0), (x_tab, y_body_top + 8.0),
    ]
    added = [_append_shape_in_memory(d, "cube-contorno", kind="poly", closed=True, points=outline, layer="CUT")]

    vincos = [
        (x1, y_body_top, x1, y_body_bot, "vinco-aba-cola"),
        (x2, y_body_top, x2, y_body_bot, "vinco-p1-p2"),
        (x3, y_body_top, x3, y_body_bot, "vinco-p2-p3"),
        (x4, y_body_top, x4, y_body_bot, "vinco-p3-p4"),
        (x3, y_lid_fold, x4, y_lid_fold, "vinco-tampa-lingueta"),
        (x2 + 1.0, y_body_top, x5 - 1.0, y_body_top, "vinco-topo-corpo"),
        (x1 + 1.0, y_body_bot, x5 - 1.0, y_body_bot, "vinco-base-corpo"),
    ]
    for x1_s, y1_s, x2_s, y2_s, lbl in vincos:
        added.extend(_add_line_to_doc(
            d, x1_s, y1_s, x2_s, y2_s,
            dashed=dashed_score, dash_len_mm=3.5, gap_len_mm=2.0, layer="SCORE", label=lbl
        ))
    return added


def _build_pillow_box(
    d: dict[str, Any],
    *,
    x_mm: float,
    y_mm: float,
    width_mm: float,
    body_height_mm: float,
    dashed_score: bool,
) -> list[dict[str, Any]]:
    g = max(8.0, min(14.0, width_mm * 0.2))
    curve_h = max(10.0, min(18.0, width_mm * 0.22))
    x_tab = x_mm
    x1 = x_tab + g
    x2 = x1 + width_mm
    x3 = x2 + width_mm

    y_top = y_mm
    y_body_top = y_top + curve_h
    y_body_bot = y_body_top + body_height_mm

    def bow_arc(xa: float, xb: float, y_base: float, dy: float, n: int = 16) -> list[tuple[float, float]]:
        return [
            (xa + (xb - xa) * i / n, y_base + dy * math.sin(math.pi * i / n))
            for i in range(n + 1)
        ]

    outline: list[tuple[float, float]] = []
    outline += bow_arc(x1, x2, y_body_top, -curve_h)
    outline += bow_arc(x2, x3, y_body_top, -curve_h)
    outline.append((x3, y_body_bot))
    outline += list(reversed(bow_arc(x2, x3, y_body_bot, +curve_h)))
    outline += list(reversed(bow_arc(x1, x2, y_body_bot, +curve_h)))
    outline += [(x_tab, y_body_bot - 8.0), (x_tab, y_body_top + 8.0), (x1, y_body_top)]

    added = [_append_shape_in_memory(d, "pillow-contorno", kind="poly", closed=True, points=outline, layer="CUT")]

    for x_s, lbl in ((x1, "vinco-aba-cola"), (x2, "vinco-centro")):
        added.extend(_add_line_to_doc(
            d, x_s, y_body_top, x_s, y_body_bot,
            dashed=dashed_score, dash_len_mm=3.5, gap_len_mm=2.0, layer="SCORE", label=lbl
        ))

    arcs_spec = [
        (bow_arc(x1, x2, y_body_top, +curve_h * 0.85), "vinco-topo-p1"),
        (bow_arc(x2, x3, y_body_top, +curve_h * 0.85), "vinco-topo-p2"),
        (bow_arc(x1, x2, y_body_bot, -curve_h * 0.85), "vinco-base-p1"),
        (bow_arc(x2, x3, y_body_bot, -curve_h * 0.85), "vinco-base-p2"),
    ]
    for arc_pts, lbl in arcs_spec:
        added.append(_append_shape_in_memory(d, lbl, kind="poly", closed=False, points=arc_pts, layer="SCORE"))

    return added


def _build_gift_tag(
    d: dict[str, Any],
    *,
    x_mm: float,
    y_mm: float,
    width_mm: float,
    body_height_mm: float,
    dashed_score: bool,
) -> list[dict[str, Any]]:
    chamfer = min(width_mm * 0.25, body_height_mm * 0.22, 16.0)
    pts = [
        (x_mm, y_mm + chamfer),
        (x_mm + chamfer, y_mm),
        (x_mm + width_mm - chamfer, y_mm),
        (x_mm + width_mm, y_mm + chamfer),
        (x_mm + width_mm, y_mm + body_height_mm),
        (x_mm, y_mm + body_height_mm),
    ]
    added = [_append_shape_in_memory(d, "tag-contorno", kind="poly", closed=True, points=pts, layer="CUT")]
    added.append(_append_shape_in_memory(
        d, "tag-furo", kind="circle", cx=x_mm + width_mm / 2, cy=y_mm + max(6.0, chamfer * 0.65), r=2.5, layer="CUT"
    ))
    vinco_y = y_mm + chamfer + 6.0
    if vinco_y < y_mm + body_height_mm - 5.0:
        added.extend(_add_line_to_doc(
            d, x_mm + 4.0, vinco_y, x_mm + width_mm - 4.0, vinco_y,
            dashed=dashed_score, dash_len_mm=3.0, gap_len_mm=2.0, layer="SCORE", label="tag-vinco"
        ))
    return added


def add_box_template(
    design: str,
    template: str = "milk-box-luxo",
    x_mm: float = 20.0,
    y_mm: float = 15.0,
    width_mm: float = 60.0,
    depth_mm: float = 60.0,
    body_height_mm: float = 90.0,
    dashed_score: bool = True,
) -> dict[str, Any]:
    """Generate and persist a parametric packaging/papercraft dieline in CUT/SCORE layers."""
    _num(x_mm=x_mm, y_mm=y_mm)
    _pos(width_mm=width_mm, depth_mm=depth_mm, body_height_mm=body_height_mm)
    tpl = str(template).strip().lower()
    supported = ("milk-box-luxo", "milk-box", "cube-box", "pillow-box", "gift-tag")
    if tpl not in supported:
        raise SilhouetteValueError(f"Unknown template '{template}'. Options: {', '.join(supported)}")

    with _LOCK:
        doc = load_design(design)
        working = copy.deepcopy(doc)
        if tpl in ("milk-box-luxo", "milk-box"):
            added = _build_milk_box(
                working,
                luxo=(tpl == "milk-box-luxo"),
                x_mm=x_mm,
                y_mm=y_mm,
                width_mm=width_mm,
                depth_mm=depth_mm,
                body_height_mm=body_height_mm,
                dashed_score=bool(dashed_score),
            )
        elif tpl == "cube-box":
            added = _build_cube_box(
                working,
                x_mm=x_mm,
                y_mm=y_mm,
                width_mm=width_mm,
                depth_mm=depth_mm,
                body_height_mm=body_height_mm,
                dashed_score=bool(dashed_score),
            )
        elif tpl == "pillow-box":
            added = _build_pillow_box(
                working,
                x_mm=x_mm,
                y_mm=y_mm,
                width_mm=width_mm,
                body_height_mm=body_height_mm,
                dashed_score=bool(dashed_score),
            )
        else:
            added = _build_gift_tag(
                working,
                x_mm=x_mm,
                y_mm=y_mm,
                width_mm=width_mm,
                body_height_mm=body_height_mm,
                dashed_score=bool(dashed_score),
            )

        if len(added) > 1:
            cut_cands = [s for s in added if s.get("layer", "CUT") == "CUT"] or added
            outer = max(
                cut_cands,
                key=lambda s: (lambda b: (b[2] - b[0]) * (b[3] - b[1]))(_bbox(s)),
            )
            for s in added:
                if s["id"] != outer["id"]:
                    s["parent_id"] = outer["id"]

        doc["shapes"] = working["shapes"]
        doc["next_id"] = working["next_id"]
        save_design(doc)
        warnings = [
            f"shape {s['id']} ({s['label']}): {w}"
            for s in added
            for w in _shape_warnings(doc, s)
        ]
        return {
            "design": doc["name"],
            "template": tpl,
            "shapes_added": len(added),
            "shape_ids": [s["id"] for s in added],
            "bbox_mm": _r4(_union_bbox(added)),
            "warnings": warnings,
        }

