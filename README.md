# Silhouette Studio MCP Server (`v1.1.0`)

A production-hardened **Model Context Protocol (MCP)** server (stdio) for programmatically creating, validating, nesting, previewing, and exporting vector cut designs in millimetres (`mm`) for **Silhouette Studio** (including Standard/Basic Edition, which opens DXF files natively but does not import SVG natively).

Because Silhouette Studio exposes no public live API, this server models designs as persistent `.design.json` scenes, converts vector geometry, external SVGs, TrueType/OpenType text, offsets, registration marks, nested layouts, and parametric box dielines into clean **DXF** (`R2000`/`R12`), **SVG**, and **PNG preview** files, and opens them directly in Silhouette Studio.

---

## Key Features

- **28 MCP Tools** covering canvas presets, geometric primitives, TrueType/OpenType text vectorization (`fontTools` + built-in geometric vector fallback), hardened contour offsetting (`round` / `miter` / `bevel`), deterministic **2D sheet nesting** (`silhouette_nest_shapes` via MaxRects), grid duplication, transforms with `flip_x` / `flip_y`, hardened SVG path import, Print & Cut registration marks, parametric packaging templates, PNG visual proofs, DXF/SVG export, and Silhouette Studio launch.
- **Layer & Line-Color Workflow**: Built-in layer mapping (`CUT`, `SCORE`/`FOLD`, `PERF`, `ENGRAVE`, `REGMARK`) using AutoCAD Color Index (ACI) values for DXF and matching hex strokes for SVG/PNG so Silhouette Studio's *Cut by Line Color* panel separates cut lines from creases and perforations automatically.
- **Inter-Process Concurrency & Crash Recovery**: Protected by `_InterProcessLock` (combining re-entrant `threading.RLock` with OS-level locking on `.silhouette.lock` via `msvcrt.locking` on Windows and `fcntl.flock` on POSIX), `os.fsync` atomic temp-file writes, monotonically incremented `revision` tracking, and automatic recovery from `.design.json.bak` on corrupted primary files.
- **Security & Hard Limits**: Rejects `bool`-as-int coercion, `NaN`/`inf`, extreme coordinates (`abs <= 100000 mm`), oversized canvases (`10..5000 mm`), oversized text (`<= 500` chars), self-intersecting closed contours, XML DTD/`<!ENTITY`/`<script`/external URI payloads in SVG (`10 MB`, `10000` elements, depth `64`, `100000` points, `defusedxml` XML hardening), strict `allow_nan=False` JSON persistence, and atomically enforces `MAX_SHAPES = 5000` across all batch tools.
- **MCP v2 Error Reporting, Annotations & STDIO Hygiene**: Dual-inheritance exceptions (`SilhouetteValueError`, `SilhouetteRuntimeError`) preserve full diagnostic messages in MCP v2 `is_error=True` tool responses while remaining standard `ValueError`/`RuntimeError` subclasses for Python callers. Operational logs route exclusively to `sys.stderr` so JSON-RPC `stdout` is never corrupted.
- **Clean Silhouette-Ready DXF**: Sets `$INSUNITS`/`$EXTMIN`/`$EXTMAX` headers, avoids duplicate closing vertices on closed polylines (`LWPOLYLINE`), and flattens curves within a `0.05 mm` chord tolerance (`CHORD_TOL_MM`).

---

## Requirements

- **Python**: `>= 3.10`
- **Dependencies** (`pyproject.toml`):
  - `defusedxml>=0.7.1`
  - `mcp>=1.3.0`
  - `ezdxf>=1.4.0`
  - `svgelements>=1.9.0`
  - `fonttools>=4.40.0`
  - `Pillow>=10.0.0`
- **Dev Dependencies**:
  - `pytest>=8.0.0`
  - `pytest-cov>=5.0.0`

---

## Installation

```bash
git clone https://github.com/WarlemJung/Silhouette-Studio-MCP-Server.git
cd Silhouette-Studio-MCP-Server
pip install -e ".[dev]"
```

For runtime-only installation:

```bash
pip install -e .
```

---

## MCP Client Configuration

Add the server to your MCP host configuration (stdio transport):

```json
{
  "mcpServers": {
    "silhouette-studio": {
      "command": "python",
      "args": ["/absolute/path/to/silhouette_studio_mcp/src/silhouette_mcp/server.py"]
    }
  }
}
```

If installed as a package (`pip install -e .`), you can also launch the console script entry point:

```json
{
  "mcpServers": {
    "silhouette-studio": {
      "command": "silhouette-studio-mcp"
    }
  }
}
```

### Optional Environment Variables

| Variable | Default | Description |
| --- | --- | --- |
| `SILHOUETTE_OUTPUT_DIR` | `~/Documents/SilhouetteMCP` | Directory where `.design.json`, `.design.json.bak`, `.silhouette.lock`, `.dxf`, `.svg`, and `.png` files are saved. |
| `SILHOUETTE_DXF_VERSION` | `R2000` | DXF export version (`R2000` or `R12`). |
| `SILHOUETTE_STUDIO_EXE` | Auto-detected | Explicit path to the Silhouette Studio executable (`Silhouette Studio.exe` on Windows or `/Applications/Silhouette Studio.app` on macOS). |
| `SILHOUETTE_LOG_LEVEL` | `WARNING` | Logger verbosity written exclusively to `sys.stderr` (`DEBUG`, `INFO`, `WARNING`, `ERROR`, `CRITICAL`). |

---

## Coordinate System, Layers & Presets

### Coordinate System & Operational Limits

- **Units**: Millimetres (`mm`)
- **Origin**: Top-left `(0, 0)` of the page/mat
- **Axes**: `+X` grows right, `+Y` grows down
- **Rotation**: Degrees, clockwise
- **Safety Limits**: Warns on details smaller than `MIN_FEATURE_MM = 2.0 mm` or shapes extending outside `cut_margin_mm`; enforces `MIN_PAGE_MM = 10.0 mm`, `MAX_PAGE_MM = 5000.0 mm`, `MAX_COORD_MM = 100000.0 mm`, `MAX_TEXT_LENGTH = 500`, `MAX_ARC_SEGMENTS = 512`, `MAX_POINTS_PER_SHAPE = 20000`, `MAX_SVG_BYTES = 10 MB`, `MAX_SVG_ELEMENTS = 10000`, `MAX_SVG_DEPTH = 64`, `MAX_SVG_TOTAL_POINTS = 100000`, and atomic pre-checked `MAX_SHAPES = 5000` per design.

### Supported Layers

| Layer | DXF ACI Color | SVG / PNG Color | Preview Style | Intended Use |
| --- | --- | --- | --- | --- |
| `CUT` | `1` (Red) | `#e60000` | Solid | Full perimeter / blade cut |
| `SCORE` | `5` (Blue) | `#0066cc` | Dashed | Fold / score creases |
| `FOLD` | `5` (Blue) | `#0066cc` | Dashed | Alias for fold creases |
| `PERF` | `3` (Green) | `#009900` | Dashed | Perforation / tear lines |
| `ENGRAVE` | `4` (Cyan) | `#00cccc` | Solid | Sketch / foil / engraving |
| `REGMARK` | `7` (Black/White) | `#000000` | Solid | Print & Cut registration marks |
| `DEFAULT` | `7` (Black/White) | `#000000` | Solid | Fallback layer |

### Page / Mat Presets

| Preset | Dimensions (`width × height` mm) |
| --- | --- |
| `mat-12x12` | `304.8 × 304.8` |
| `mat-12x24` | `304.8 × 609.6` |
| `mat-pixscan-portrait` | `190.5 × 292.1` |
| `mat-pixscan-cameo` | `292.1 × 292.1` |
| `a4` | `210.0 × 297.0` |
| `a3` | `297.0 × 420.0` |
| `letter` | `215.9 × 279.4` |

---

## MCP Tools Reference (28 Tools)

### 1. Design Lifecycle (6 tools)

| Tool | Signature | Description |
| --- | --- | --- |
| `silhouette_list_page_presets` | `()` | Returns all built-in page/mat presets and dimensions in mm. |
| `silhouette_new_design` | `(name, preset="mat-12x12", width_mm=0, height_mm=0, cut_margin_mm=5, overwrite=False)` | Creates a new design file (`<slug>.design.json`). Explicit positive `width_mm` and `height_mm` override `preset`. |
| `silhouette_list_designs` | `()` | Lists saved designs in `SILHOUETTE_OUTPUT_DIR` with dimensions and shape counts. |
| `silhouette_get_design` | `(design)` | Returns full JSON geometry and metadata for a design. |
| `silhouette_delete_design` | `(design, delete_files=False)` | Deletes the `.design.json` file and optionally removes matching `.dxf`, `.svg`, and `.png` exports. |
| `silhouette_clear_shapes` | `(design)` | Removes all shapes from an existing design while keeping page setup. |

### 2. Vector Primitives (7 tools)

| Tool | Signature | Description |
| --- | --- | --- |
| `silhouette_add_rectangle` | `(design, x_mm, y_mm, width_mm, height_mm, corner_radius_mm=0, rotation_deg=0, layer="CUT", label="")` | Adds a sharp or rounded rectangle. |
| `silhouette_add_circle` | `(design, cx_mm, cy_mm, radius_mm, layer="CUT", label="")` | Adds a circle (exported natively as DXF `CIRCLE` and SVG `<circle>`). |
| `silhouette_add_ellipse` | `(design, cx_mm, cy_mm, rx_mm, ry_mm, rotation_deg=0, layer="CUT", label="")` | Adds an optionally rotated ellipse. |
| `silhouette_add_polygon` | `(design, cx_mm, cy_mm, radius_mm, sides, rotation_deg=0, layer="CUT", label="")` | Adds a regular polygon (`sides >= 3`). |
| `silhouette_add_star` | `(design, cx_mm, cy_mm, outer_radius_mm, inner_radius_mm, points=5, rotation_deg=0, layer="CUT", label="")` | Adds a symmetric star (`points >= 3`, `inner_radius_mm < outer_radius_mm`). |
| `silhouette_add_line` | `(design, x1_mm, y1_mm, x2_mm, y2_mm, dashed=False, dash_len_mm=3.0, gap_len_mm=2.0, layer="CUT", label="")` | Adds a solid line or batched dashed line segments (ideal for `SCORE` creases). |
| `silhouette_add_polyline` | `(design, points, closed=True, layer="CUT", label="")` | Adds an open or closed polyline from `[[x, y], ...]` vertices. |

### 3. Typography, Registration Marks & Parametric Templates (3 tools)

| Tool | Signature | Description |
| --- | --- | --- |
| `silhouette_add_text` | `(design, text, x_mm, y_mm, size_mm=15.0, font="Arial", align="left", letter_spacing_mm=0.0, rotation_deg=0.0, layer="CUT", label="")` | Converts text into cuttable vector contours using TrueType/OpenType system fonts (or an explicit font file path) via `fontTools`, with a built-in geometric vector fallback font when a font is unavailable. Supports `left`, `center`, and `right` alignment. |
| `silhouette_add_registration_marks` | `(design, inset_mm=10.0, mark_size_mm=5.0, arm_len_mm=15.0, arm_thick_mm=1.0, layer="REGMARK")` | Places standard Print & Cut marks (top-left square + top-right/bottom-left L-brackets) with `REGMARK` excluded from cut-margin warnings. |
| `silhouette_add_box_template` | `(design, template="milk-box-luxo", x_mm=20.0, y_mm=15.0, width_mm=60.0, depth_mm=60.0, body_height_mm=90.0, dashed_score=True)` | Generates a full packaging dieline with `CUT` outer contours, glue tabs, and dashed or solid `SCORE` fold lines. Supported templates: `milk-box-luxo`, `milk-box`, `cube-box`, `pillow-box`, `gift-tag`. |

### 4. Editing, Offsetting, Nesting, Duplication & SVG Import (7 tools)

| Tool | Signature | Description |
| --- | --- | --- |
| `silhouette_transform_shape` | `(design, shape_id, dx_mm=0, dy_mm=0, scale=1.0, rotation_deg=0, flip_x=False, flip_y=False)` | Mirrors (`flip_x`, `flip_y`), scales, rotates around the shape center, and translates a shape in place. |
| `silhouette_offset_shape` | `(design, shape_id, offset_mm, join="round", layer="", label="")` | Creates an outward (`offset_mm > 0`) or inward (`offset_mm < 0`) bleed/sticker/inset contour from any closed simple shape using `round`, `miter`, or `bevel` joins, with self-intersection loop pruning, containment, and minimum clearance validation. |
| `silhouette_nest_shapes` | `(design, shape_ids=None, spacing_mm=3.0, margin_mm=-1.0, allow_rotation=True, rotation_step_deg=90.0, dry_run=False)` | Deterministic MaxRects (`Best Short Side Fit`) 2D sheet nesting with rotation optimization, clearance spacing, Print & Cut `REGMARK` avoidance, `dry_run` preview, and dual utilization metrics. |
| `silhouette_duplicate_shape` | `(design, shape_id, dx_mm=0, dy_mm=0, count=1)` | Creates deep-copied stepped duplicates offset by `(dx_mm, dy_mm)` per step (with atomic `MAX_SHAPES` pre-validation). |
| `silhouette_grid_duplicates` | `(design, shape_id, cols, rows, spacing_x_mm=5.0, spacing_y_mm=5.0)` | Duplicates a shape across a `cols × rows` nesting grid using bounding-box dimensions plus spacing. |
| `silhouette_remove_shape` | `(design, shape_id)` | Removes a single shape by its `shape_id`. |
| `silhouette_import_svg` | `(design, svg_path, target_width_mm=0, target_height_mm=0, x_mm=0, y_mm=0, rotation_deg=0, layer="CUT")` | Validates SVG security bounds, parses paths/primitives via `svgelements`, flattens Bezier/arc curves, scales proportionally by `target_width_mm` and/or `target_height_mm`, rotates clockwise, and places at `(x_mm, y_mm)`. |

### 5. Inspection, Export, Calibration & Launch (5 tools)

| Tool | Signature | Description |
| --- | --- | --- |
| `silhouette_describe_design` | `(design)` | Summarizes shape counts, `revision`, layer breakdown, design bounding box, and cut-margin/fine-detail warnings. |
| `silhouette_export` | `(design, formats="dxf,svg", filename="")` | Exports any combination of `dxf`, `svg`, and `png` to `SILHOUETTE_OUTPUT_DIR` with atomic writes. |
| `silhouette_render_preview` | `(design, dpi=150, filename="")` | Renders a color-coded PNG visual proof (`36–600 DPI`) showing page bounds, cut margins, dashed crease lines, and solid cut/engrave/registration contours. |
| `silhouette_make_calibration_file` | `()` | Generates `calibration-100mm.dxf` (`100 × 100 mm` square, circle, rounded rectangle, and score line) to verify DXF import scale in Silhouette Studio. |
| `silhouette_open_in_studio` | `(path, reveal_in_explorer=False)` | Safely validates `.dxf`/`.svg` paths (no `shell=True`), launches Silhouette Studio without blocking (`process_launched`, `homologated_import=False`), or reveals the file in the OS file manager. |

---

## Documentation

- [`docs/architecture.md`](docs/architecture.md) — Layered `server -> tools -> services -> {core, persistence, exporters, integrations}` architecture, dependency matrix, and STDIO transport isolation.
- [`docs/geometry.md`](docs/geometry.md) — Y-down/CAD Y-up coordinate mapping, polygon validation, self-intersection detection, and hardened contour offsetting.
- [`docs/nesting.md`](docs/nesting.md) — Modular `core/nesting/` 2D MaxRects (`BSSF + BAF`) packing domain, collision/clearance validation, and `REGMARK` preservation.
- [`docs/persistence.md`](docs/persistence.md) — Transactional `_save` commit semantics, `_InterProcessLock`, stale temp cleanup, and `.design.json.bak` recovery.
- [`docs/security.md`](docs/security.md) — SVG/XXE protections, numeric/capacity bounds, atomic batch enforcement, and desktop subprocess security.
- [`docs/testing.md`](docs/testing.md) — Layered automated test suite (`unit/`, `integration/`, `regression/`, `performance/`), CI coverage gate, real STDIO E2E tests, and benchmarks.
- [`docs/manual-homologation.md`](docs/manual-homologation.md) — Visual GUI and physical cutter homologation protocol (`Status: Não executado`).
- [`CHANGELOG.md`](CHANGELOG.md) — Release history (`0.2.0` -> `1.0.0` -> `1.1.0`).

---

## Silhouette Studio DXF Calibration

1. Run `silhouette_make_calibration_file()` to generate `calibration-100mm.dxf`.
2. Open the file in Silhouette Studio (`silhouette_open_in_studio("calibration-100mm.dxf")`).
3. Verify the imported square measures **100.0 mm × 100.0 mm**.
4. If the dimensions differ, configure Silhouette Studio **Preferences -> Import -> DXF -> Open As Is (Centered or As-Is, 1:1 / mm units)** instead of *Fit to Page*.

> **Note on Homologation**: `silhouette_open_in_studio` verifies OS process launch (`process_launched: true`) and returns `homologated_import: false` because visual DXF verification inside the desktop GUI and physical blade cuts require manual inspection.

---

## Examples

- [`examples/create_sample_design.py`](examples/create_sample_design.py): Builds a rounded tag with a keyhole perforation, exports DXF + SVG, and opens it in Silhouette Studio.
- [`examples/generate_caixa_milk.py`](examples/generate_caixa_milk.py): Standalone script demonstrating programmatic packaging generation with `CUT`, `SCORE`, and `ENGRAVE` layers.

---

## Package Architecture

The project follows a clean layered `src/` + categorized `tests/` layout configured in [`pyproject.toml`](pyproject.toml) (`silhouette-studio-mcp = "silhouette_mcp.server:main"`) with CI automation in [`.github/workflows/tests.yml`](.github/workflows/tests.yml), organizing responsibilities under [`src/silhouette_mcp/`](src/silhouette_mcp/__init__.py) and tests into `unit/{core,services,tools,exporters,persistence}/`, `integration/{mcp,persistence,studio}/`, `regression/`, `performance/`, and `fixtures/`:

- `src/silhouette_mcp/config/settings.py`: Presets, layer palettes, limits, `_DynamicStderrHandler`, and monkeypatch-transparent runtime resolution (`get_runtime_attr()`).
- `src/silhouette_mcp/core/`, `core/nesting/` & `core/templates/`: Exceptions & MCP v1/v2 shims (`exceptions.py`), validators (`validators.py`), shape models (`models.py`), 2D geometry/offset engine (`geometry_engine.py`), pure 2D nesting domain (`nesting/{models,collision,maxrects,metrics}.py`), and pure 2D packaging dieline builders (`templates/{models,geometry,generators}.py`).
- `src/silhouette_mcp/persistence/`: Cross-process `.silhouette.lock` (`_InterProcessLock`), stale temp cleanup (`_cleanup_stale_temp_files`) & atomic writes (`storage.py`), plus transactional `.design.json.bak` crash recovery (`repository.py`).
- `src/silhouette_mcp/exporters/` & `integrations/`: DXF, SVG, and PNG exporters plus Windows/macOS Silhouette Studio launcher (`silhouette_studio.py`).
- `src/silhouette_mcp/services/`: Use-case orchestration layer (`document_service`, `geometry_service`, `nesting_service`, `export_service`, `import_service`, `template_service`) decoupled from MCP transport.
- `src/silhouette_mcp/tools/` & `server.py`: 28 thin MCP adapter tools registered centrally via `TOOL_REGISTRATIONS` (self-bootstrapping STDIO entrypoint).

See [`docs/architecture.md`](docs/architecture.md) for the full layered diagram and dependency matrix.

---

## Testing, Benchmarks & Verification

Run the automated test suite with the minimum coverage gate (`fail_under = 92` configured in [`pyproject.toml`](pyproject.toml)):

```bash
python -m pytest -v -p no:cacheprovider --cov=silhouette_mcp --cov-report=term-missing --cov-fail-under=92
```

All tests automatically isolate `SILHOUETTE_OUTPUT_DIR` to a temporary directory via [`tests/conftest.py`](tests/conftest.py) and mock OS GUI launches. GitHub Actions CI ([`.github/workflows/tests.yml`](.github/workflows/tests.yml)) validates Windows Latest and Ubuntu Latest across Python `3.11`, `3.12`, and `3.13`. Latest local verified status: **112 passed (`52` unit + `60` integration/regression/performance), 0 failed, 0 skipped**, **96% (`95.85%`) line coverage** (`2624` statements across `41` modules in `src/silhouette_mcp/`), covering:
- Strict AST architectural dependency boundaries across `core/`, `services/`, and `tools/`
- Pure `core/nesting/` & `core/templates/` unit validation, curve geometry, and deterministic 2D packing/dieline invariants
- Direct `services/` orchestration tests, transactional fault-injected persistence rollback/backup preservation, 4-process parallel concurrency (`subprocess.Popen` + `_InterProcessLock`), and `.design.json.bak` crash recovery
- Hardened convex, concave, self-intersecting, and inradius-exceeded contour offsets + seeded property invariants
- Atomic `MAX_SHAPES = 5000` batch guards and SVG XXE/`<script>`/depth/element/URI protections
- Unmocked real MCP STDIO JSON-RPC client-server end-to-end execution (`list_tools`, `new_design`, `add_rectangle`, `add_text`, `nest_shapes`, `export dxf/svg/png`, `delete_design`)
- Automated performance sanity checks in `tests/performance/test_benchmarks.py` (with full `100` to `5,000` shape scale tables published in [`docs/testing.md`](docs/testing.md); manual GUI/plotter homologation tracked in [`docs/manual-homologation.md`](docs/manual-homologation.md))
