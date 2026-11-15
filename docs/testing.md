# Testing, Benchmarks & Verification Strategy

## Overview

The test suite exercises core 2D computational geometry, modular 2D MaxRects nesting (`core/nesting/`), the application orchestration `services/` layer, thin MCP `tools/` contract adapters, SVG/XML security hardening, inter-process lock safety, crash recovery from `.design.json.bak`, `MAX_SHAPES = 5000` atomic enforcement, TrueType/vector fallback text generation, DXF/SVG/PNG exporters, Studio launcher resolution, automated performance benchmarks, and **unmocked real STDIO subprocess MCP client-server execution**.

All tests automatically isolate file I/O using [`tests/conftest.py`](../tests/conftest.py), which redirects `silhouette_mcp.server.OUTPUT_DIR` to a temporary directory per test and exposes static fixtures from [`tests/fixtures/`](../tests/fixtures/sample_shapes.svg).

---

## Test Suite Breakdown

Executed via:

```bash
python -m pytest -v -p no:cacheprovider --cov=silhouette_mcp --cov-report=term-missing --cov-fail-under=92
```

Latest verified suite layout (**Python 3.13.7 on Windows 11**, `pytest 9.2.0`) and CI pipeline ([`.github/workflows/tests.yml`](../.github/workflows/tests.yml) targeting `windows-latest` & `ubuntu-latest` across Python `3.11`, `3.12`, `3.13` with `--cov-fail-under=92`):
- **112 tests across 16 test modules** (`52` unit + `60` integration/regression/performance), **96% (`95.85%`) line coverage** (`2624` statements across `41` Python modules in `src/silhouette_mcp/` — `109` missed lines are primarily macOS/POSIX branches when executed on Windows and defensive OS error branches).

| Test Module | Category | Scope & Real/Mocked Boundary |
| --- | --- | --- |
| [`tests/unit/core/test_geometry.py`](../tests/unit/core/test_geometry.py) | Unit (Core) | Slug sanitization, strict type checks, precision formatting, bounding boxes, arcs, rotation, rounded rects |
| [`tests/unit/core/test_nesting.py`](../tests/unit/core/test_nesting.py) | Unit (Core/Nesting) | `boxes_overlap`, `min_clearance_between_boxes`, `validate_placements_in_bounds`, `compute_regmark_obstacles`, composite groups, deterministic `build_candidates` & `pack_candidates_maxrects`, oversize/zero-area edge cases, dual metrics |
| [`tests/unit/core/test_templates.py`](../tests/unit/core/test_templates.py) | Unit (Core/Templates) | `BoxTemplateSpec` immutability & validation, pure `_milk_arch_pts` / `_bow_arc` geometry, all 5 dieline generators × solid/dashed scores, parent linking, determinism, `template_service` re-exports |
| [`tests/unit/services/test_services.py`](../tests/unit/services/test_services.py) | Unit (Services) | Direct invocation of `document_service`, `geometry_service`, `nesting_service`, `export_service`, `import_service`, `template_service` without MCP protocol overhead |
| [`tests/unit/tools/test_tools.py`](../tests/unit/tools/test_tools.py) | Unit (Tools) | Presets, lifecycle, primitives, layers, dashed lines, transform/duplicate deep-copy isolation, warnings, `MAX_SHAPES`, atomic save cleanup |
| [`tests/unit/tools/test_svg_import.py`](../tests/unit/tools/test_svg_import.py) | Unit (Tools) | Real `svgelements` path & Bezier import from `tests/fixtures/` SVGs and invalid SVG error handling |
| [`tests/unit/tools/test_mcp_adapters.py`](../tests/unit/tools/test_mcp_adapters.py) | Unit (Architecture) | Verifies all 28 MCP tool exports/signatures plus automated AST import-boundary enforcement (`core/` vs `services/` vs `tools/`) |
| [`tests/unit/exporters/test_export.py`](../tests/unit/exporters/test_export.py) | Unit (Exporters) | Real `ezdxf` R2000/R12 generation (`$INSUNITS`, `$EXTMIN`/`$EXTMAX`), empty design rejection, `100x100 mm` calibration DXF, SVG layer ID sanitization |
| [`tests/unit/persistence/test_storage_and_repo.py`](../tests/unit/persistence/test_storage_and_repo.py) | Unit (Persistence) | Atomic temp-file cleanup, strict schema & `NaN` rejection before mutation, `os.fsync`/`_atomic_replace` fault-injection rollback, pre-replace `.bak` preservation, backup failure resilience, `_cleanup_stale_temp_files`, primary corruption healing & recovery error escalation |
| [`tests/integration/mcp/test_mcp_interface.py`](../tests/integration/mcp/test_mcp_interface.py) | Integration (MCP) | In-memory MCP client session flows on `asyncio` and `trio` |
| [`tests/integration/mcp/test_production_features.py`](../tests/integration/mcp/test_production_features.py) | Integration (MCP) | MCP v2 dual-inheritance errors & annotations across all 28 tools (`asyncio`, `trio`), async/thread concurrency, Windows atomic replace retry backoff, fontTools TTF & fallback glyphs, offsets, `flip_x`/`flip_y`, grids, regmarks, box templates, PNG previews |
| [`tests/integration/persistence/test_concurrency.py`](../tests/integration/persistence/test_concurrency.py) | Integration (Persistence) | Concurrent thread-pool updates on a shared design confirming zero lost shapes and exact monotonic `revision` increments |
| [`tests/integration/studio/test_studio_integration.py`](../tests/integration/studio/test_studio_integration.py) | Integration (Studio) | Executable discovery (`SILHOUETTE_STUDIO_EXE` & OS paths), `.dxf`/`.svg` slug resolution, missing file rejection, OS `Popen` error escalation (OS GUI launch mocked) |
| [`tests/regression/test_audit_hardening_and_nesting.py`](../tests/regression/test_audit_hardening_and_nesting.py) | Regression | Real 4-process concurrent writes (`subprocess.Popen` + `_InterProcessLock`), corrupt primary recovery from `.design.json.bak`, lock timeout, concave L/U/star/self-intersecting & inradius-exceeded (`-3.5 mm`) offsets, seeded property-based geometry/nesting invariants (`40` + `12` randomized runs), atomic `MAX_SHAPES` pre-checks, SVG/XXE/script/depth/element/font/Studio path security checks, **unmocked real STDIO JSON-RPC client-server E2E session**, and layered package structure check |
| [`tests/regression/test_coverage_edge_cases.py`](../tests/regression/test_coverage_edge_cases.py) | Regression | DXF R12 export, invalid margins/line lengths/sides/stars/polylines/transforms/formats, skipped SVG elements, file deletion |
| [`tests/performance/test_benchmarks.py`](../tests/performance/test_benchmarks.py) | Performance | Automated latency sanity bounds for 40-piece nesting with rotation, 60-shape DXF/SVG/PNG batch export, 150 DPI preview rendering, and 256-shape persistence round-trips |

---

## Previously Measured Baseline Scale Benchmarks (`100` to `5,000` Shapes)

Measured prior to the service-layer split (`SILHOUETTE_OUTPUT_DIR` on temporary SSD directory, `1000 x 1000 mm` page) using rectangular shapes (`tracemalloc` peak memory tracking):

| Shapes | Create + Save (ms) | Atomic Save + `.bak` (ms) | `describe` (ms) | `transform` 1 Shape (ms) | `nest_shapes` (ms / scope / placed) | DXF Export (ms / KB) | SVG Export (ms / KB) | SVG Re-Import (ms) | `.design.json` Size (KB) | Peak Traced RAM (MB) |
| --- | ---: | ---: | ---: | ---: | --- | ---: | ---: | ---: | ---: | ---: |
| **100** | 34.68 | 13.40 | 18.41 | 16.20 | 28.53 ms (`100` / `100`) | 80.99 ms (`36.6 KB`) | 6.95 ms (`5.2 KB`) | 131.17 | 27.9 | 1.90 |
| **500** | 66.02 | 35.44 | 53.16 | 49.22 | 111.87 ms (`500` / `500`) | 282.22 ms (`115.1 KB`) | 27.78 ms (`26.7 KB`) | 307.84 | 141.2 | 3.14 |
| **1,000** | 119.26 | 61.96 | 97.23 | 87.13 | 268.93 ms (`1000` / `1000`) | 557.25 ms (`213.4 KB`) | 43.14 ms (`54.0 KB`) | 668.53 | 283.2 | 6.62 |
| **5,000** (`MAX_SHAPES`) | 479.88 | 283.26 | 512.43 | 484.53 | 231.77 ms (`500` slice / `500`) | 2637.02 ms (`1002.3 KB`) | 216.64 ms (`274.3 KB`) | 3188.79 | 1429.4 | 34.99 |

---

## Known Limitations & Hardware Boundary

1. **GUI & Physical Cutter Homologation**: Automated CI verifies subprocess exit health (`proc.poll()`), argument vectors, and file generation (`calibration-100mm.dxf`, DXF/SVG/PNG outputs), with `silhouette_open_in_studio` mocked in unit tests to avoid opening desktop GUI windows. End-to-end opening inside a live Silhouette Studio UI and physical test cuts on plotter blades remain **manual physical homologation steps** (`homologated_import: false` in tool output; protocol tracked as `Não executado` in [`docs/manual-homologation.md`](manual-homologation.md)).
2. **Connected Concave Island Offsetting**: `_offset_polygon` outputs a single simple polygon loop; inward offsets extreme enough to split one concave shape into disconnected islands raise `SilhouetteValueError`.
3. **Hypothesis Library**: Property-based invariant checks currently use deterministic seeded `random.Random` fuzzers because `hypothesis` is not required as a runtime/dev dependency; if `hypothesis` is added to CI later, the existing invariant properties map 1:1 to `@given` strategies.
