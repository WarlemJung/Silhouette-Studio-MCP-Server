# Silhouette Studio MCP Server (`v1.0.0`)

A production-ready **Model Context Protocol (MCP)** server (stdio) for programmatically creating, validating, previewing, and exporting vector cut designs in millimetres (`mm`) for **Silhouette Studio** (including Standard/Basic Edition, which opens DXF files natively but does not import SVG natively).

Because Silhouette Studio exposes no public live API, this server models designs as persistent `.design.json` scenes, converts vector geometry, external SVGs, TrueType/OpenType text, offsets, registration marks, and parametric box dielines into clean **DXF** (`R2000`/`R12`), **SVG**, and **PNG preview** files, and opens them directly in Silhouette Studio.

---

## Key Features

- **27 MCP Tools** covering canvas presets, geometric primitives, TrueType/OpenType text vectorization (`fontTools` + built-in geometric vector fallback), contour offsetting (`round` / `miter` / `bevel`), grid nesting/duplication, transforms with `flip_x` / `flip_y`, SVG path import, Print & Cut registration marks, parametric packaging templates, PNG visual proofs, DXF/SVG export, and Silhouette Studio launch.
- **Layer & Line-Color Workflow**: Built-in layer mapping (`CUT`, `SCORE`/`FOLD`, `PERF`, `ENGRAVE`, `REGMARK`) using AutoCAD Color Index (ACI) values for DXF and matching hex strokes for SVG/PNG so Silhouette Studio's *Cut by Line Color* panel separates cut lines from creases and perforations automatically.
- **Production Concurrency & Persistence**: Protected by a module-level re-entrant lock (`threading.RLock`) and atomic temp-file writes with Windows `PermissionError` backoff retries (`_atomic_replace`), preventing lost updates or lock collisions under parallel MCP tool calls.
- **MCP v2 Error Reporting & Annotations**: Dual-inheritance exceptions (`SilhouetteValueError`, `SilhouetteRuntimeError`) preserve full diagnostic messages in MCP v2 `is_error=True` tool responses while remaining standard `ValueError`/`RuntimeError` subclasses for Python callers. All 27 tools include `ToolAnnotations`.
- **Clean Silhouette-Ready DXF**: Sets `$EXTMIN`/`$EXTMAX` headers, avoids duplicate closing vertices on closed polylines (`LWPOLYLINE`), and flattens curves within a `0.05 mm` chord tolerance (`CHORD_TOL_MM`).

---

## Requirements

- **Python**: `>= 3.10`
- **Dependencies** (`requirements.txt` / `pyproject.toml`):
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

Or install runtime dependencies directly:

```bash
pip install -r requirements.txt
```

---

## MCP Client Configuration

Add the server to your MCP host configuration (stdio transport):

```json
{
  "mcpServers": {
    "silhouette-studio": {
      "command": "python",
      "args": ["/absolute/path/to/silhouette_studio_mcp/server.py"]
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
| `SILHOUETTE_OUTPUT_DIR` | `~/Documents/SilhouetteMCP` | Directory where `.design.json`, `.dxf`, `.svg`, and `.png` files are saved. |
| `SILHOUETTE_DXF_VERSION` | `R2000` | DXF export version (`R2000` or `R12`). |
| `SILHOUETTE_STUDIO_EXE` | Auto-detected | Explicit path to the Silhouette Studio executable (`Silhouette Studio.exe` on Windows or `/Applications/Silhouette Studio.app` on macOS). |

---

## Coordinate System, Layers & Presets

### Coordinate System

- **Units**: Millimetres (`mm`)
- **Origin**: Top-left `(0, 0)` of the page/mat
- **Axes**: `+X` grows right, `+Y` grows down
- **Rotation**: Degrees, clockwise
- **Safety Limits**: Warns on details smaller than `MIN_FEATURE_MM = 2.0 mm` or shapes extending outside `cut_margin_mm`; enforces `MAX_SHAPES = 5000` per design.

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

## MCP Tools Reference (27 Tools)

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
| `silhouette_add_circle` | `(design, cx_mm, cy_mm, radius_mm, layer="CUT", label="")` | Adds a circle (approximated as a smooth closed polygon in DXF/SVG). |
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

### 4. Editing, Offsetting, Duplication & SVG Import (6 tools)

| Tool | Signature | Description |
| --- | --- | --- |
| `silhouette_transform_shape` | `(design, shape_id, dx_mm=0, dy_mm=0, scale=1.0, rotation_deg=0, flip_x=False, flip_y=False)` | Mirrors (`flip_x`, `flip_y`), scales, rotates around the shape center, and translates a shape in place. |
| `silhouette_offset_shape` | `(design, shape_id, offset_mm, join="round", layer="", label="")` | Creates an outward (`offset_mm > 0`) or inward (`offset_mm < 0`) bleed/sticker/inset contour from any closed shape using `round`, `miter`, or `bevel` joins, with area-inversion detection. |
| `silhouette_duplicate_shape` | `(design, shape_id, dx_mm=0, dy_mm=0, count=1)` | Creates deep-copied stepped duplicates offset by `(dx_mm, dy_mm)` per step. |
| `silhouette_grid_duplicates` | `(design, shape_id, cols, rows, spacing_x_mm=5.0, spacing_y_mm=5.0)` | Duplicates a shape across a `cols × rows` nesting grid using bounding-box dimensions plus spacing. |
| `silhouette_remove_shape` | `(design, shape_id)` | Removes a single shape by its `shape_id`. |
| `silhouette_import_svg` | `(design, svg_path, target_width_mm=0, target_height_mm=0, x_mm=0, y_mm=0, rotation_deg=0, layer="CUT")` | Parses SVG paths/primitives via `svgelements`, flattens Bezier/arc curves, scales proportionally by `target_width_mm` and/or `target_height_mm`, rotates clockwise, and places at `(x_mm, y_mm)`. |

### 5. Inspection, Export, Calibration & Launch (5 tools)

| Tool | Signature | Description |
| --- | --- | --- |
| `silhouette_describe_design` | `(design)` | Summarizes shape counts, layer breakdown, design bounding box, and cut-margin/fine-detail warnings. |
| `silhouette_export` | `(design, formats="dxf,svg", filename="")` | Exports any combination of `dxf`, `svg`, and `png` to `SILHOUETTE_OUTPUT_DIR` with atomic writes. |
| `silhouette_render_preview` | `(design, dpi=150, filename="")` | Renders a color-coded PNG visual proof (`72–300 DPI`) showing page bounds, cut margins, dashed crease lines, and solid cut/engrave/registration contours. |
| `silhouette_make_calibration_file` | `()` | Generates `calibracao_100x100mm.dxf` (`100 × 100 mm` square) to verify DXF import scale in Silhouette Studio. |
| `silhouette_open_in_studio` | `(path, reveal_in_explorer=False)` | Resolves a file path or design slug (preferring `.dxf` over `.svg`) and launches Silhouette Studio without blocking, or reveals the file in the OS file manager when `reveal_in_explorer=True`. |

---

## Silhouette Studio DXF Calibration

1. Run `silhouette_make_calibration_file()` to generate `calibracao_100x100mm.dxf`.
2. Open the file in Silhouette Studio (`silhouette_open_in_studio("calibracao_100x100mm.dxf")`).
3. Verify the imported square measures **100.0 mm × 100.0 mm**.
4. If the dimensions differ, configure Silhouette Studio **Preferences -> Import -> DXF -> Open As Is (Centered or As-Is, 1:1 / mm units)** instead of *Fit to Page*.

---

## Examples

- [`examples/create_sample_design.py`](examples/create_sample_design.py): Builds a rounded tag with a keyhole perforation, exports DXF + SVG, and opens it in Silhouette Studio.
- [`examples/generate_caixa_milk.py`](examples/generate_caixa_milk.py): Standalone script demonstrating programmatic packaging generation with `CUT`, `SCORE`, and `ENGRAVE` layers.

---

## Testing & Verification

Run the automated test suite with coverage reporting:

```bash
python -m pytest -v -p no:cacheprovider --cov=server --cov-report=term-missing
```

All tests automatically isolate `SILHOUETTE_OUTPUT_DIR` to a temporary directory via `tests/conftest.py` and mock OS GUI launches. Current test suite status: **67 passed**, **96% line coverage** on `server.py`, covering unit geometry, SVG/DXF/PNG export, text vectorization, contour offsets, parametric templates, concurrency (`asyncio`, `trio`, and `ThreadPoolExecutor`), Windows atomic replace retries, and full MCP client-server tool calls.
