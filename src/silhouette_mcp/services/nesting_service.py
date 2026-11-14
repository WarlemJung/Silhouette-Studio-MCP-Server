"""2D nesting orchestration service coordinating domain packing and persistence."""

from __future__ import annotations

from typing import Any

from ..core.exceptions import SilhouetteValueError
from ..core.nesting import (
    NestingConfig,
    _maxrects_subtract,
    apply_placement_to_shape,
    build_composite_candidates,
    compute_nesting_metrics,
    compute_regmark_obstacles,
    compute_unselected_obstacles,
    extract_root_decisions,
    generate_rotation_angles,
    pack_candidates_maxrects,
)
from ..core.validators import _int, _num, _r4
from ..persistence.repository import load_design, save_design
from ..persistence.storage import _LOCK


def nest_shapes(
    design: str,
    shape_ids: list[int] | None = None,
    spacing_mm: float = 3.0,
    margin_mm: float = -1.0,
    allow_rotation: bool = True,
    rotation_step_deg: float = 90.0,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Validate nesting parameters, run MaxRects packing via core.nesting, and optionally persist updates."""
    _num(spacing_mm=spacing_mm, margin_mm=margin_mm, rotation_step_deg=rotation_step_deg)
    if spacing_mm < 0:
        raise SilhouetteValueError("spacing_mm must be >= 0")
    if rotation_step_deg < 1.0 or rotation_step_deg > 180.0:
        raise SilhouetteValueError("rotation_step_deg must be between 1.0 and 180.0")
    if shape_ids is not None:
        if not isinstance(shape_ids, list) or not shape_ids:
            raise SilhouetteValueError("shape_ids must be a non-empty list of integers when provided")
        for idx, sid in enumerate(shape_ids):
            _int(**{f"shape_ids[{idx}]": sid})
        if len(set(shape_ids)) != len(shape_ids):
            raise SilhouetteValueError("shape_ids cannot contain duplicate ids")

    with _LOCK:
        doc = load_design(design)
        width, height = float(doc["width_mm"]), float(doc["height_mm"])
        eff_margin = float(doc["cut_margin_mm"]) if margin_mm < 0 else float(margin_mm)
        if eff_margin < 0 or eff_margin * 2 >= min(width, height):
            raise SilhouetteValueError("margin_mm must be >= 0 and smaller than half of the page")

        cfg = NestingConfig(
            sheet_x0=eff_margin,
            sheet_y0=eff_margin,
            sheet_x1=width - eff_margin,
            sheet_y1=height - eff_margin,
            spacing_mm=float(spacing_mm),
            rotation_step_deg=float(rotation_step_deg),
            allow_rotation=bool(allow_rotation),
            preserve_regmarks=True,
            dry_run=bool(dry_run),
        )

        by_id = {s["id"]: s for s in doc["shapes"]}
        if shape_ids is not None:
            missing = [sid for sid in shape_ids if sid not in by_id]
            if missing:
                raise SilhouetteValueError(f"Unknown shape_id(s): {', '.join(str(m) for m in missing)}")
            targets = [by_id[sid] for sid in shape_ids]
            selected_set = set(shape_ids)
        else:
            targets = [s for s in doc["shapes"] if s.get("layer", "CUT") != "REGMARK"]
            selected_set = {s["id"] for s in targets}

        if not targets:
            raise SilhouetteValueError("No shapes selected to nest")

        free_rects: list[tuple[float, float, float, float]] = [
            (0.0, 0.0, cfg.usable_width, cfg.usable_height)
        ]
        reg_obstacles, regmarks_avoided = compute_regmark_obstacles(
            doc["shapes"],
            selected_set,
            cfg.sheet_x0,
            cfg.sheet_y0,
            cfg.spacing_mm,
        )
        unselected_obstacles, unselected_avoided = compute_unselected_obstacles(
            doc["shapes"],
            selected_set,
            cfg.sheet_x0,
            cfg.sheet_y0,
            cfg.spacing_mm,
        )
        for obs in reg_obstacles + unselected_obstacles:
            free_rects = _maxrects_subtract(free_rects, obs)

        angles = generate_rotation_angles(cfg.allow_rotation, cfg.rotation_step_deg)
        candidates = build_composite_candidates(targets)
        decisions, unplaced_ids = pack_candidates_maxrects(
            candidates,
            free_rects,
            cfg.sheet_x0,
            cfg.sheet_y0,
            cfg.spacing_mm,
            angles,
        )

        if not cfg.dry_run and decisions:
            for decision in decisions:
                apply_placement_to_shape(by_id[decision.shape_id], decision)
            save_design(doc)

        root_decisions = extract_root_decisions(decisions)
        metrics = compute_nesting_metrics(cfg.usable_width, cfg.usable_height, root_decisions)
        placed_ids = [dec.shape_id for dec in decisions]
        placements = [
            {
                "shape_id": dec.shape_id,
                "label": dec.label,
                "rotation_deg": dec.rotation_deg,
                "bbox_mm": _r4(dec.bbox_mm),
            }
            for dec in decisions
        ]

        warnings: list[str] = []
        if unplaced_ids:
            warnings.append(f"{len(unplaced_ids)} shape(s) did not fit inside the usable sheet area")
        if regmarks_avoided:
            warnings.append(f"Reserved clearance around {regmarks_avoided} REGMARK shape(s)")
        if unselected_avoided:
            warnings.append(f"Reserved clearance around {unselected_avoided} unselected shape(s)")

        return {
            "design": doc["name"],
            "placed_count": len(placed_ids),
            "unplaced_count": len(unplaced_ids),
            "placed_ids": placed_ids,
            "unplaced_ids": unplaced_ids,
            "placements": placements,
            "usable_area_bbox_mm": _r4(cfg.sheet_bounds),
            "usable_area_mm2": metrics.usable_area_mm2,
            "occupied_bbox_area_mm2": metrics.occupied_bbox_area_mm2,
            "occupied_shape_area_mm2": metrics.occupied_shape_area_mm2,
            "bounding_envelope_mm": metrics.bounding_envelope_mm,
            "utilization_pct": metrics.utilization_pct,
            "true_area_utilization_pct": metrics.true_area_utilization_pct,
            "dry_run": cfg.dry_run,
            "warnings": warnings,
        }

