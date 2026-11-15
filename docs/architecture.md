# Architecture & Layered Design — Silhouette Studio MCP Server

## Overview

The **Silhouette Studio MCP Server** exposes **28 Model Context Protocol (MCP) tools** over `STDIO` transport to design, manipulate, nest, import, preview, and export precision 2D vector cut files (in millimetres) for Silhouette Studio and Silhouette cutting plotters.

The codebase follows a clean layered `src/` architecture under [`src/silhouette_mcp/`](../src/silhouette_mcp/__init__.py) with strict unidirectional dependencies:

```text
server.py  ──▶  tools/ (MCP input adapters)
                   │
                   ▼
                services/ (use-case orchestration)
                   │
         ┌─────────┼──────────┬──────────────┐
         ▼         ▼          ▼              ▼
       core/   persistence/ exporters/  integrations/
    (domain +     (locks +   (DXF/SVG/    (Studio OS
    nesting/)      repo)       PNG)        launcher)
```

---

## Directory & Module Layout

```text
silhouette_studio_mcp/
├── .github/
│   └── workflows/
│       └── tests.yml                  # Cross-platform CI matrix (Windows + Ubuntu, Python 3.11–3.13, >= 92% coverage)
├── .gitignore
├── CHANGELOG.md
├── README.md
├── pyproject.toml                     # Package discovery (src/), entrypoints, pytest & coverage config
├── docs/
│   ├── architecture.md
│   ├── geometry.md
│   ├── manual-homologation.md         # Manual GUI visual & physical cutter homologation protocol (`Não executado`)
│   ├── nesting.md
│   ├── persistence.md                 # Transactional `_save`, `_InterProcessLock`, stale cleanup & `.bak` recovery
│   ├── security.md
│   └── testing.md
├── examples/
│   ├── create_sample_design.py
│   └── generate_caixa_milk.py
├── src/
│   └── silhouette_mcp/
│       ├── __init__.py                # Package metadata (`__version__ = "1.1.0"`)
│       ├── server.py                  # Self-bootstrapping `mcp` FastMCP instance, `TOOL_REGISTRATIONS`, `main()`
│       ├── config/
│       │   ├── __init__.py
│       │   └── settings.py            # Presets, palettes, limits, `_DynamicStderrHandler`, `logger`, `get_runtime_attr()`
│       ├── core/
│       │   ├── __init__.py
│       │   ├── exceptions.py          # MCP v1/v2 `FastMCP` shims, `SilhouetteValueError`, `SilhouetteRuntimeError`, `_ann()`
│       │   ├── geometry_engine.py     # 2D polygon cleanup, self-intersection detection, offsetting, curves
│       │   ├── models.py              # Shape bounding boxes, area calculation, deep cloning, cut warnings
│       │   ├── validators.py          # Strict numeric/integer/slug/layer/shape-capacity & schema validators
│       │   ├── nesting/
│       │   │   ├── __init__.py
│       │   │   ├── models.py          # `NestingConfig`, `NestingCandidate`, `PlacementDecision`, `NestingMetrics`
│       │   │   ├── collision.py       # AABB overlap, clearance, bounds validation, REGMARK obstacles, composite groups
│       │   │   ├── maxrects.py        # `_maxrects_subtract`, rotation sampling, MaxRects BSSF+BAF packer
│       │   │   └── metrics.py         # Dual bbox + true-area utilization & bounding envelope metrics
│       │   └── templates/
│       │       ├── __init__.py
│       │       ├── models.py          # `BoxTemplateSpec`, `SUPPORTED_BOX_TEMPLATES`
│       │       ├── geometry.py        # Pure curve primitives (`_milk_arch_pts`, `_bow_arc`)
│       │       └── generators.py      # Parametric dieline builders & `generate_box_template_shapes`
│       ├── exporters/
│       │   ├── __init__.py
│       │   ├── dxf.py                 # `_write_dxf` (AutoCAD R2000 `LWPOLYLINE`/mm `$INSUNITS` + R12 `POLYLINE`)
│       │   ├── png.py                 # `_write_png` (Pillow 2D raster preview with dashed score/perf strokes)
│       │   └── svg.py                 # `_write_svg` (1 unit = 1 mm vector export with sanitized layer `<g>` groups)
│       ├── integrations/
│       │   ├── __init__.py
│       │   └── silhouette_studio.py   # `_find_studio_exe`, OS-safe subprocess launch (`silhouette_open_in_studio`)
│       ├── persistence/
│       │   ├── __init__.py
│       │   ├── repository.py          # Transactional `_save`/`save_design`, `_preserve_existing_backup`, `.bak` recovery
│       │   └── storage.py             # `_InterProcessLock` (`msvcrt`/`fcntl`), `_atomic_replace`, `_cleanup_stale_temp_files`
│       ├── services/
│       │   ├── __init__.py
│       │   ├── document_service.py    # Document lifecycle, presets, inspection, shape deletion
│       │   ├── geometry_service.py    # Primitives, transforms, offsets, duplication, regmarks, typography
│       │   ├── nesting_service.py     # Orchestrates `core.nesting` + persistence locks
│       │   ├── export_service.py      # DXF/SVG/PNG export, previews, calibration file, Studio delegation
│       │   ├── import_service.py      # SVG XML hardening, `svgelements` path flattening, scale & placement
│       │   └── template_service.py    # Service orchestration delegating pure dieline construction to `core.templates`
│       └── tools/
│           ├── __init__.py
│           ├── document.py            # Thin MCP adapters -> `document_service` (8 tools)
│           ├── geometry.py            # Thin MCP adapters -> `geometry_service` / `nesting_service` (12 tools)
│           ├── import_export.py       # Thin MCP adapters -> `import_service` / `export_service` (5 tools)
│           ├── registration.py        # Thin MCP adapter -> `geometry_service.add_registration_marks` (1 tool)
│           ├── templates.py           # Thin MCP adapter -> `template_service` (1 tool)
│           └── text.py                # Thin MCP adapter -> `geometry_service.add_text` (1 tool)
└── tests/
    ├── conftest.py                    # Configures `src/` import path, `fixtures_dir`, and temp `OUTPUT_DIR` isolation
    ├── fixtures/                      # Static SVG fixtures
    ├── unit/                          # Isolated tests: `core/`, `services/`, `tools/`, `exporters/`, `persistence/`
    ├── integration/                   # Component/protocol tests: `mcp/`, `persistence/`, `studio/`
    ├── regression/                    # Multi-process locking, crash recovery, fuzz invariants, E2E STDIO, AST boundaries
    └── performance/                   # Automated latency benchmarks for nesting, export, preview & persistence
```

---

## Dependency Matrix & Architectural Decisions

### Dependency Boundaries (Enforced by Automated AST Tests)

| Layer | Allowed Dependencies | Forbidden Dependencies |
| --- | --- | --- |
| `core/` & `core/nesting/` | `config/`, stdlib (`math`, `dataclasses`) | `services/`, `tools/`, `persistence/`, `exporters/`, `integrations/` (and `nesting/` excludes `mcp`) |
| `persistence/`, `exporters/`, `integrations/` | `config/`, `core/` | `services/`, `tools/` |
| `services/` | `config/`, `core/`, `persistence/`, `exporters/`, `integrations/` | `tools/`, `mcp` |
| `tools/` | `services/` | `core/`, `persistence/`, `exporters/`, `integrations/` |
| `server.py` | `config/`, `core/exceptions`, `tools/`, runtime compatibility shims | Direct domain algorithms or file writes |

### Decision Against a Separate `schemas/` Package
FastMCP derives JSON Schema tool contracts automatically from Python type annotations and docstrings on the 28 public functions in `tools/`, while shape models, bounds checks, and domain dataclasses are centralized in `core/validators.py`, `core/models.py`, and `core/nesting/models.py`. Creating a parallel `schemas/` package would duplicate existing validation contracts and add boilerplate without functional or runtime benefit; therefore typed signatures + domain models remain the single source of truth.

### Key System Guarantees

1. **Zero `stdout` Contamination over STDIO**: Operational logging via `_DynamicStderrHandler` writes strictly to `sys.stderr`, leaving `sys.stdout` exclusively for MCP JSON-RPC framing.
2. **Cross-Process Concurrency & Crash Recovery**: Serialization acquires both in-process `threading.RLock` and OS-level `_InterProcessLock` on `OUTPUT_DIR/.silhouette.lock` (`msvcrt.locking` on Windows / `fcntl.flock` on POSIX, `LOCK_TIMEOUT_S = 10.0`). Atomic writes increment `revision`, `os.fsync` temp files, retry `os.replace`, and maintain `.design.json.bak`.
3. **100% Backwards Compatibility**: All 28 MCP tool names, parameter signatures, defaults, `ToolAnnotations`, docstrings, and return dictionary schemas remain untouched, and runtime monkeypatches on `silhouette_mcp.server` (`OUTPUT_DIR`, `_save`, `_find_studio_exe`, `DXF_VERSION`, `_FONT_DIRS`, etc.) resolve dynamically.
