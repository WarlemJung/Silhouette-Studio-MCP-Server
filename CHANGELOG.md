# Changelog

All notable changes to **Silhouette Studio MCP Server** are documented in this file.

## [1.1.0] - 2026-11-14

### Added
- **28th MCP Tool — `silhouette_nest_shapes`**: Deterministic MaxRects (`Best Short Side Fit + Best Area Fit`) 2D sheet nesting in millimetres with configurable piece clearance (`spacing_mm`), sheet margin (`margin_mm`), allowed discrete rotations (`allow_rotation`, `rotation_step_deg`), `dry_run` mode, automatic avoidance of non-selected `REGMARK` Print & Cut marks, and dual bounding-box + exact true-area utilization metrics.
- **Cross-Process File Locking (`_InterProcessLock`)**: Pairs in-process re-entrant `threading.RLock` with OS-level exclusive locking on `.silhouette.lock` (`msvcrt.locking` on Windows / `fcntl.flock` on POSIX) and configurable `LOCK_TIMEOUT_S = 10.0` wait timeout.
- **Automatic Crash Recovery (`.design.json.bak` & `revision`)**: Every atomic save writes a verified mirror backup and monotonically increments the design `revision` counter. Corrupt or truncated primary files are automatically validated via `_validate_design_dict` and recovered seamlessly from `.design.json.bak` (`silhouette_delete_design` cleans `.bak` mirrors too).
- **Dynamic STDIO-Safe Operational Logging**: Added `logging.Logger("silhouette_mcp")` with `_DynamicStderrHandler` routed strictly to `sys.stderr` (controlled by `SILHOUETTE_LOG_LEVEL`, default `WARNING`) to prevent JSON-RPC `stdout` contamination.
- **Comprehensive Documentation**: Added [`docs/architecture.md`](docs/architecture.md), [`docs/geometry.md`](docs/geometry.md), [`docs/nesting.md`](docs/nesting.md), [`docs/security.md`](docs/security.md), [`docs/testing.md`](docs/testing.md), and this `CHANGELOG.md`.
- **Layered Architecture (`services/` & `core/nesting/`)**: Extracted use-case orchestration into `src/silhouette_mcp/services/` (`document_service`, `geometry_service`, `nesting_service`, `export_service`, `import_service`, `template_service`), extracted the pure 2D nesting domain into `src/silhouette_mcp/core/nesting/` (`models`, `collision`, `maxrects`, `metrics`), and reduced `tools/` modules to thin MCP input adapters with automated AST unidirectional dependency checks.
- **Hardening, Layered Unit, Integration & Benchmark Tests**: Organized `tests/` into `unit/{core,services,tools,exporters,persistence}`, `integration/{mcp,persistence,studio}`, `regression/`, `performance/`, and `fixtures/` (`94` automated tests / `96%` coverage across `2224` statements), including an unmocked real STDIO JSON-RPC client-server test.
- **Modular `src/silhouette_mcp/` Package Refactor**: Decomposed the monolithic server into domain modules under `src/silhouette_mcp/` (`config`, `core`, `services`, `persistence`, `exporters`, `integrations`, `tools`, and self-bootstrapping `server.py`), standardized dependency/test configuration in `pyproject.toml` (`silhouette-studio-mcp = "silhouette_mcp.server:main"`), and removed legacy root `server.py`, root `__init__.py`, and `requirements.txt`.

### Fixed & Hardened
- **Atomic `MAX_SHAPES = 5000` Capacity Validation (`_check_shape_capacity`)**: Closed bypasses across multi-shape batch operations (`silhouette_add_registration_marks`, dashed `silhouette_add_line`, `silhouette_duplicate_shape`, `silhouette_grid_duplicates`, `silhouette_add_text`, `silhouette_import_svg`, and `silhouette_add_box_template` staged via isolated deep copy before commit).
- **2D Offset & Polygon Engine (`_offset_polygon`)**: Added collinearity and fold-back spike pruning (`_clean_polygon`), AABB-indexed self-intersection detection (`_has_self_intersection`) enforced in `silhouette_add_polyline(..., closed=True)` and offsetting, self-intersection loop pruning (`_prune_self_intersection_loops`), inward point-in-polygon checks (`_point_in_polygon`), and minimum Euclidean boundary clearance checks (`_point_to_polygon_dist`) catching inverted negative-homothety triangles past their inradius.
- **SVG & Input Security (`_validate_svg_file`)**: Added strict `10 MB` (`MAX_SVG_BYTES`) limit, strict UTF-8 decoding, DTD/`<!ENTITY`/`<script`/`javascript:`/`url(http|file:...)` rejection, optional `defusedxml.ElementTree` safe XML parsing, `<svg>` root check, XML tree depth (`MAX_SVG_DEPTH = 64`), element count (`MAX_SVG_ELEMENTS = 10000`), total point limit (`MAX_SVG_TOTAL_POINTS = 100000`), external URI rejection on `href`/`xlink:href`/`src`, text length limit (`MAX_TEXT_LENGTH = 500`), explicit font extension whitelist (`.ttf`, `.otf`, `.ttc`), page bounds (`10.0..5000.0 mm`), and coordinate bounds (`abs <= 100000.0 mm`).
- **Studio Launcher Hardening (`silhouette_open_in_studio`)**: Added null-byte and invalid OS path rejection, immediate subprocess health check via `proc.poll()`, and explicit `"process_launched": True, "homologated_import": False` return fields distinguishing OS launch from physical machine cut homologation.

## [1.0.0] - 2026-11-13

### Added
- Full 27-tool production suite with TrueType/OpenType text vectorization (`fontTools` + geometric fallback font), `silhouette_offset_shape`, `silhouette_transform_shape` (`flip_x`/`flip_y`), `silhouette_grid_duplicates`, `silhouette_add_registration_marks`, parametric box templates (`milk-box-luxo`, `milk-box`, `cube-box`, `pillow-box`, `gift-tag`), PNG visual previews (`silhouette_render_preview`), dual-inheritance MCP v2 errors, and atomic disk persistence with Windows `PermissionError` retries.

## [0.2.0] - 2026-11-12

### Added
- Initial MCP STDIO server implementation (`server.py`) with core vector primitives, SVG path import, DXF R2000/R12 and SVG exporters, calibration DXF generator, and Silhouette Studio desktop launcher.

