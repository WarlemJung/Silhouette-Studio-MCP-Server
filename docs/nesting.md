# 2D Nesting Engine (`core/nesting/` & `services/nesting_service.py`)

## Architectural Overview

The 2D sheet nesting domain is isolated into pure computational modules under [`src/silhouette_mcp/core/nesting/`](../src/silhouette_mcp/core/nesting/__init__.py) with **zero dependencies** on the MCP protocol, persistence, exporters, or OS integrations, while orchestration lives in [`src/silhouette_mcp/services/nesting_service.py`](../src/silhouette_mcp/services/nesting_service.py).

| Module | Responsibility |
| --- | --- |
| [`core/nesting/models.py`](../src/silhouette_mcp/core/nesting/models.py) | Typed immutable domain dataclasses: `NestingConfig`, `NestingCandidate`, `PlacementDecision`, `NestingMetrics`. |
| [`core/nesting/maxrects.py`](../src/silhouette_mcp/core/nesting/maxrects.py) | Canonical `_maxrects_subtract`, `generate_rotation_angles`, deterministic `build_candidates`, `pack_candidates_maxrects` (BSSF + BAF), and `apply_placement_to_shape`. |
| [`core/nesting/collision.py`](../src/silhouette_mcp/core/nesting/collision.py) | Bounding-box overlap detection (`boxes_overlap`), Euclidean clearance (`min_clearance_between_boxes`), sheet boundary & spacing validation (`validate_placements_in_bounds`), and Print & Cut regmark reservation (`compute_regmark_obstacles`). |
| [`core/nesting/metrics.py`](../src/silhouette_mcp/core/nesting/metrics.py) | Usable sheet area, occupied bbox area, true polygon/circle area, bounding envelope, `utilization_pct`, and `true_area_utilization_pct` (`compute_nesting_metrics`). |
| [`services/nesting_service.py`](../src/silhouette_mcp/services/nesting_service.py) | Validates MCP parameters (`spacing_mm >= 0`, `1.0 <= rotation_step_deg <= 180.0`, unique integer `shape_ids`), acquires `_LOCK`, loads design, builds regmark obstacles and candidates, runs `pack_candidates_maxrects`, persists mutations unless `dry_run=True`, and formats response payload. |

---

## Algorithm Details

### 1. Determinism & Candidate Ordering
- `build_candidates()` converts shapes into `NestingCandidate` objects sorted strictly by `(-bbox_area_mm2, -max(width_mm, height_mm), shape_id)`.
- Larger parts are placed first while identically sized parts break ties monotonically by `shape_id`, ensuring identical outputs for identical inputs.

### 2. Rotations (`generate_rotation_angles`)
- When `allow_rotation=False` or a shape's `kind == "circle"`, only `0.0°` is tested.
- When `allow_rotation=True`, discrete clockwise increments `0.0, step, 2*step, ... < 180.0°` are evaluated around each shape's bounding-box center via `_rotated_shape_preview()`.

### 3. MaxRects Best Short Side Fit (BSSF) + Best Area Fit (BAF)
For each rotated bounding box `(rw, rh)` against each maximal free rectangle `(fx0, fy0, fx1, fy1)`:
1. Compute `short_fit = min(fw - rw, fh - rh)`, `long_fit = max(fw - rw, fh - rh)`, and `area_fit = fw * fh - rw * rh`.
2. Choose the placement minimizing `(short_fit, long_fit, area_fit, fy0, fx0)` rounded to `5` decimal places.
3. Reserve `(lx - spacing_mm, ly - spacing_mm, lx + rw + spacing_mm, ly + rh + spacing_mm)` from `free_rects` via `_maxrects_subtract()`, pruning strictly contained free rectangles.

### 4. Print & Cut `REGMARK` Preservation
- Non-selected shapes on layer `REGMARK` are never moved unless explicitly listed in `shape_ids`.
- `compute_regmark_obstacles()` converts each non-selected registration mark into a padded obstacle rectangle (`reg_pad = max(1.0, spacing_mm)`) and subtracts it from `initial_free_rects` before packing any cut/score geometry.

### 5. Dual Utilization Metrics & `dry_run` Mode
- **`utilization_pct`**: `(sum(rw * rh) / usable_area_mm2) * 100`.
- **`true_area_utilization_pct`**: `(sum(_shape_area_mm2) / usable_area_mm2) * 100`, reflecting exact polygon/circle material density inside rectangular bounding boxes.
- **`dry_run=True`**: Computes all placements, warnings, `placed_ids`, `unplaced_ids`, and utilization metrics without mutating disk state or incrementing `revision`.

