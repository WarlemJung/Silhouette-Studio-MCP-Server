# 2D Computational Geometry Specification

## Coordinate Conventions

- **Units**: Millimetres (`mm`) throughout the document model and all 28 MCP tools.
- **2D Canvas Axes**: Origin `(0, 0)` at **top-left**; `+X` grows **right**, `+Y` grows **down**; angles in degrees increase **clockwise**.
- **DXF Export Mapping**: DXF stores geometry in standard right-handed Y-up CAD coordinates via `(x, H - y)` where `H = height_mm`, preserving exact visual orientation when opened in Silhouette Studio alongside `$INSUNITS = 4` (mm) and `$MEASUREMENT = 1` (metric).
- **Curve Flattening**: Circular arcs and Bezier curves use `CHORD_TOL_MM = 0.05 mm` and cap per-arc tessellation at `MAX_ARC_SEGMENTS = 512`.

---

## Polygon Validation & Cleaning

1. **Vertex Deduplication (`_dedupe_closed`)**: Collapses consecutive points within `1e-6 mm` and ensures closed polygons do not store duplicate start/end closing vertices.
2. **Degeneracy Pruning (`_clean_polygon`)**: Iteratively removes collinear intermediate points and 180-degree backtracking spikes where perpendicular deviation from adjacent edges is `<= 1e-6 mm`.
3. **Self-Intersection Detection (`_has_self_intersection`)**:
   - Pre-filters segment pairs with axis-aligned bounding boxes (AABB).
   - Evaluates segment intersections (`_segments_intersect`) across non-adjacent edges (including proper crossing and collinear overlap).
   - Rejects 180-degree overlapping fold-backs on adjacent edges (`cos(angle) <= -1 + 1e-7`).
   - Enforced in `silhouette_add_polyline(..., closed=True)` and before `_offset_polygon()`.
4. **Orientation Detection (`_polygon_area2`)**: Uses the exact shoelace double-area sum (`> 0` indicates clockwise orientation in Y-down coordinates). All vertices are tested for collinearity (`_is_collinear_points`) before intersection/area errors so collinear zero-area shapes report distinct error diagnostics from symmetric self-intersecting polygons (such as bowties).

---

## Contour Offset Engine (`_offset_polygon`)

`silhouette_offset_shape` supports outward (`offset_mm > 0`) and inward (`offset_mm < 0`) offsets with `round`, `miter`, or `bevel` joins for circles and simple closed polygons (convex and concave):

1. **Preconditions**: Requires `>= 3` distinct vertices, non-collinear non-zero area, and zero input self-intersections.
2. **Edge Normal Displacement**: Edge normals point strictly outward (when `offset_mm > 0`) or inward (`offset_mm < 0`) relative to `_polygon_area2` sign.
3. **Corner Joins & Reflex Clamping**:
   - Convex corners follow `round` (`_arc`), `bevel` (chamfer segment), or `miter` (clamped at `abs(offset_mm) * 4.0`).
   - Concave reflex corners clamp intersections that exceed local adjacent edge reach (`max(miter_limit, min(l_prev, l_curr) * 1.5)`), preventing long needle artifacts.
4. **Self-Intersection Loop Pruning (`_prune_self_intersection_loops`)**:
   - When offsetting across narrow concave channels (e.g., U-channels expanding outward or narrow legs collapsing inward), shifted edges can cross each other cleanly.
   - The pruner splits closed rings at edge intersections and discards inverted minor loops whose signed area orientation contradicts the original contour, retaining the primary valid simple loop.
5. **Post-Offset Integrity Checks**:
   - Re-cleaned output must contain `>= 3` vertices and dimensions `>= 0.2 mm` on both axes.
   - Resulting signed area sign must match original orientation (`new_area2 * area2 > 1e-6`).
   - Final contour must pass `not _has_self_intersection(result, closed=True)`.
   - For inward offsets (`offset_mm < 0`), every vertex of the offset polygon must lie inside (or within `1e-4 mm` boundary tolerance of) the original polygon via `_point_in_polygon`, **and** must preserve a minimum Euclidean boundary clearance (`_point_to_polygon_dist(p, pts) >= abs(offset_mm) - max(1e-2, abs(offset_mm) * 0.02)`), catching inverted negative-homothety polygons (e.g., triangles inset past their inradius, whose signed area retains the original sign because `(-s)^2 > 0`).

**Known Geometric Scope**: Extreme inward offsets that split a connected concave silhouette into multiple disconnected islands raise `SilhouetteValueError("Inward offset is too large for this shape")` rather than silently outputting multiple fragmented contours.

---

## Deterministic 2D Nesting (`core/nesting/` & `silhouette_nest_shapes`)

### Algorithm Choice: MaxRects (Best Short Side Fit + Best Area Fit)

The nesting domain lives in [`src/silhouette_mcp/core/nesting/`](../src/silhouette_mcp/core/nesting/__init__.py) and is orchestrated by [`src/silhouette_mcp/services/nesting_service.py`](../src/silhouette_mcp/services/nesting_service.py). See [`docs/nesting.md`](nesting.md) for the complete specification of `NestingConfig`, `pack_candidates_maxrects`, collision/clearance validation (`boxes_overlap`, `min_clearance_between_boxes`, `validate_placements_in_bounds`), and dual utilization metrics.

### Guarantees

- **Determinism**: Candidate shapes are sorted by `(-bbox_area, -max(w, h), shape_id)` via `build_candidates()` and ties across free rectangles `(fx0, fy0)` and allowed rotation steps (`generate_rotation_angles()`) are broken strictly lexicographically.
- **Clearance & Sheet Bounds**: Free space starts as `[eff_margin, eff_margin, width_mm - eff_margin, height_mm - eff_margin]`, subtracts bounding zones around any non-selected `REGMARK` registration marks (`compute_regmark_obstacles`, `reg_pad = max(1.0, spacing_mm)`), and reserves `[lx - spacing_mm, ly - spacing_mm, lx + rw + spacing_mm, ly + rh + spacing_mm]` on each placed piece. Edge pieces flush cleanly up to the usable border while guaranteeing `>= spacing_mm` separation between every pair of placed parts.
- **Dual Utilization Metrics**: Returns both bounding-box utilization (`utilization_pct`) and exact polygon/circle true-area utilization (`true_area_utilization_pct`) via `compute_nesting_metrics()`.

