# Security & Operational Hardening

## Threat Model Overview

`silhouette-studio-mcp` accepts tool invocations over MCP STDIO and processes local files (`.design.json`, external `.svg` artwork, `.ttf`/`.otf`/`.ttc` font files, DXF/SVG/PNG outputs, and Silhouette Studio executable launches). Key attack and failure surfaces include:

1. Malicious or malformed external SVG files (XXE, Billion Laughs entity expansion, `<script>`, external SSRF/file URI fetching, deep XML recursion, memory exhaustion via dense paths).
2. Denial-of-service / integer abuse (`NaN`, `inf`, booleans passed as ints, extreme page dimensions, unbounded arc tessellation, oversized text strings, `MAX_SHAPES` bypass).
3. Path traversal / injection / invalid characters in file paths, SVG/font inputs, layer names, or external process invocations.
4. Concurrent read/write corruption or partial disk writes on Windows (`PermissionError`) and across multiple MCP server processes.
5. Accidental contamination of the STDIO JSON-RPC transport stream.

---

## Implemented Controls

### 1. SVG Import Hardening (`services/import_service.py`: `_validate_svg_file`, `_svg_subpaths`, `import_svg`)

- Rejects null bytes, resolves paths safely, requires `.svg` extension and existing regular file, and enforces strict `10 MB` (`MAX_SVG_BYTES`) file size limit and strict UTF-8 decoding.
- Blocks `<!ENTITY`, `<!DOCTYPE ... SYSTEM/PUBLIC>`, `<script`, `javascript:`, and `url(http|https|ftp|file:...)` markup before XML parsing.
- Parses XML using `defusedxml.ElementTree` when available (preventing XML entity expansion / DTD retrieval), falling back to safe structural checks if absent.
- Validates root element tag is `<svg>` (namespace-agnostic).
- Bounds XML tree depth to `MAX_SVG_DEPTH = 64` and element count to `MAX_SVG_ELEMENTS = 10000`.
- Rejects `http://`, `https://`, `ftp://`, and `file://` external references in `href` / `xlink:href` / `src` attributes (local image filenames are skipped non-fatally and logged in warnings).
- Caps total extracted vector vertices at `MAX_SVG_TOTAL_POINTS = 100000` and checks `MAX_SHAPES` capacity atomically before mutating the design.

### 2. Strict Numeric, Type & Capacity Bounds

- **`_int`**: Explicitly rejects Python `bool` (`isinstance(v, bool)`), preventing `True`/`False` coercion to `1`/`0`.
- **`_num` / `_pos`**: Rejects `bool`, `NaN`, `+/-inf`, and values with `abs(v) > MAX_COORD_MM (100000.0 mm)`.
- **Canvas Bounds**: Enforces `10.0 <= width_mm, height_mm <= 5000.0` (`MIN_PAGE_MM`..`MAX_PAGE_MM`).
- **Tessellation & String Limits**: Caps circular segments at `MAX_ARC_SEGMENTS = 512`, custom polyline points at `MAX_POINTS_PER_SHAPE = 20000`, text strings at `MAX_TEXT_LENGTH = 500`, and only opens explicit font files ending in `.ttf`, `.otf`, or `.ttc`.
- **Atomic Batch `MAX_SHAPES` (`5000`) Enforcement**: Every multi-shape operation (`silhouette_add_registration_marks`, `silhouette_add_line(dashed=True)`, `silhouette_duplicate_shape`, `silhouette_grid_duplicates`, `silhouette_add_text`, `silhouette_import_svg`, `silhouette_add_box_template`) validates total final capacity **before** mutating or saving the design.

### 3. Safe Process Invocation (`silhouette_open_in_studio`)

- Never invokes `subprocess.Popen(..., shell=True)` or evaluates shell strings.
- Validates input against empty strings, null bytes (`"\x00"`), invalid OS path errors, and restricts target launch extensions strictly to `.dxf` and `.svg`.
- Checks immediate child exit status (`proc.poll()`) after launch and surfaces failures cleanly as `SilhouetteRuntimeError`.
- Explicitly differentiates process launch from machine homologation (`"process_launched": True, "homologated_import": False`).

### 4. Serialization, Lock & Layer Sanitization

- Cross-process exclusive OS lock (`.silhouette.lock`) + per-process re-entrant `threading.RLock`.
- Atomic write (`tempfile.NamedTemporaryFile(..., delete=False)` + `flush` + `os.fsync` + retryable `os.replace`) and `.design.json.bak` mirror recovery.
- Design names are sanitized via `_slug()`, and SVG layer `<g id="...">` attributes sanitize unsafe XML characters (`re.sub(r"[^A-Za-z0-9_-]+", "-", layer)`).
- Operational logging is strictly isolated to `sys.stderr`, preventing JSON-RPC protocol injection or corruption on `stdout`.

