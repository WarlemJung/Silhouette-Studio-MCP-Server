#!/usr/bin/env python3
"""
silhouette-studio-mcp — servidor MCP (stdio) para preparar arquivos de corte
para o Silhouette Studio (Standard/Basic Edition v5, que abre DXF mas NAO abre SVG).

O Silhouette Studio nao tem API publica direta. Este servidor, portanto:
1. Modela geometrias vetoriais em milimetros (mm) com sistema de coordenadas Y-down.
2. Converte textos (TrueType/OpenType via fontTools) e SVGs externos em caminhos vetoriais.
3. GERA arquivos de corte profissionais (DXF R2000/R12, SVG e PNG preview) prontos para corte.
4. Permite organizar por CAMADAS (CUT, SCORE/FOLD, PERF, ENGRAVE, REGMARK) com cores ACI
   compativeis com o sistema de corte por camada/cor de linha do Silhouette Studio.
5. Inclui geradores parametricos (caixas milk, cubo, travesseiro, tags), offset de contorno,
   matriz de duplicacao e marcas de registro (Print & Cut).
6. Abre os arquivos diretamente no Silhouette Studio instalado.

Variaveis de ambiente (opcionais):
  SILHOUETTE_OUTPUT_DIR   pasta de saida (padrao: ~/Documents/SilhouetteMCP)
  SILHOUETTE_DXF_VERSION  versao do DXF  (padrao: R2000; suporta R12)
  SILHOUETTE_STUDIO_EXE   caminho do executavel do Silhouette Studio
"""

from __future__ import annotations

import copy
import json
import math
import os
import re
import subprocess
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

import ezdxf
from ezdxf import units

try:
    from mcp.server.mcpserver import MCPServer as FastMCP
    from mcp.server.mcpserver.exceptions import ToolError
    _MCP_V2 = True
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    from mcp.server.fastmcp import FastMCP  # type: ignore[no-redef]
    _MCP_V2 = False

    class ToolError(Exception):  # type: ignore[no-redef]
        """Fallback ToolError for mcp < 2.0."""

try:
    from mcp.types import ToolAnnotations
except (ImportError, ModuleNotFoundError):  # pragma: no cover
    ToolAnnotations = None  # type: ignore[assignment,misc]

OUTPUT_DIR = Path(
    os.environ.get("SILHOUETTE_OUTPUT_DIR") or Path.home() / "Documents" / "SilhouetteMCP"
).expanduser()
DXF_VERSION = (os.environ.get("SILHOUETTE_DXF_VERSION") or "R2000").upper()
STUDIO_EXE = os.environ.get("SILHOUETTE_STUDIO_EXE") or ""

CHORD_TOL_MM = 0.05   # tolerancia ao transformar curvas em segmentos
MIN_FEATURE_MM = 2.0  # abaixo disso, avisa que o corte fino pode rasgar papel/vinil
MAX_SHAPES = 5000

_LOCK = threading.RLock()


class SilhouetteValueError(ValueError, ToolError):
    """Erro de validacao/dominio: compativel com callers Python (ValueError) e MCP v2 (ToolError)."""


class SilhouetteRuntimeError(RuntimeError, ToolError):
    """Erro de execucao previsto: compativel com callers Python (RuntimeError) e MCP v2 (ToolError)."""


# Cores ACI (AutoCAD Color Index) para DXF e hex para SVG/PNG
LAYER_COLORS = {
    "CUT": 1,      # Vermelho (linha de corte total)
    "SCORE": 5,    # Azul (vincos/dobras)
    "FOLD": 5,     # Azul
    "PERF": 3,     # Verde (pontilhado/perfuracao)
    "ENGRAVE": 4,  # Ciano (gravacao/rascunho)
    "REGMARK": 7,  # Preto/Branco (marcas de registro Print & Cut)
    "DEFAULT": 7,  # Branco/Preto
}

SVG_LAYER_COLORS = {
    "CUT": "#e60000",
    "SCORE": "#0066cc",
    "FOLD": "#0066cc",
    "PERF": "#009900",
    "ENGRAVE": "#00cccc",
    "REGMARK": "#000000",
    "DEFAULT": "#000000",
}

_NON_CUT_LAYERS = frozenset({"SCORE", "PERF", "FOLD", "ENGRAVE", "REGMARK"})
_DASHED_PREVIEW_LAYERS = frozenset({"SCORE", "PERF", "FOLD"})

# (largura, altura) em mm. Sao tamanhos de base/pagina, NAO a area exata de corte.
PRESETS = {
    "mat-12x12": (304.8, 304.8),
    "mat-12x24": (304.8, 609.6),
    "mat-pixscan-portrait": (190.5, 292.1),
    "mat-pixscan-cameo": (292.1, 292.1),
    "a4": (210.0, 297.0),
    "a3": (297.0, 420.0),
    "letter": (215.9, 279.4),
}

INSTRUCTIONS = """\
Prepares vector cut files for Silhouette Studio. All values are in millimetres (mm).
Coordinate system: origin at the top-left of the page, X grows right, Y grows down,
rotations are in degrees, clockwise.
The user's edition (Standard/Basic, free) can open DXF (R2000/R12) but CANNOT open SVG natively,
so always export DXF for cutting. SVG and PNG preview can also be exported.
Layers supported: 'CUT' (red, blade cut), 'SCORE'/'FOLD' (blue, crease/fold line),
'PERF' (green, perforation), 'ENGRAVE' (cyan), 'REGMARK' (black, Print & Cut marks).
Typical workflow:
1. silhouette_new_design -> create canvas (e.g. preset 'mat-12x12' or 'a4')
2. silhouette_add_* / silhouette_add_text / silhouette_add_box_template / silhouette_import_svg
3. silhouette_offset_shape / silhouette_grid_duplicates / silhouette_add_registration_marks
4. silhouette_describe_design / silhouette_render_preview -> verify bounds, warnings and visual layout
5. silhouette_export(design, formats="dxf,svg,png") -> generate DXF for cutting
6. silhouette_open_in_studio -> open directly in Silhouette Studio
Silhouette Studio has no public live API: this server generates standard files and opens them.
"""

if _MCP_V2:
    mcp = FastMCP("silhouette-studio", instructions=INSTRUCTIONS, version="1.0.0")
else:  # pragma: no cover
    mcp = FastMCP("silhouette-studio", instructions=INSTRUCTIONS)


def _ann(
    *,
    read_only: bool = False,
    destructive: bool = False,
    idempotent: bool = False,
    open_world: bool = False,
) -> Any:
    if ToolAnnotations is None:  # pragma: no cover
        return None
    return ToolAnnotations(
        read_only_hint=read_only,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=open_world,
    )


def log(*a: Any) -> None:  # pragma: no cover
    print(*a, file=sys.stderr)  # stdout e reservado ao protocolo MCP


# --------------------------------------------------------------------------- util


def _slug(name: str) -> str:
    s = re.sub(r"[^A-Za-z0-9_-]+", "-", str(name).strip()).strip("-_")
    if not s:
        raise SilhouetteValueError("Invalid name: use letters, digits, '-' or '_'.")
    return s[:64]


def _design_path(name: str) -> Path:
    return OUTPUT_DIR / f"{_slug(name)}.design.json"


def _atomic_replace(src: Path, dst: Path, retries: int = 6, delay_s: float = 0.015) -> None:
    for attempt in range(retries):
        try:
            os.replace(src, dst)
            return
        except PermissionError:
            if attempt >= retries - 1:
                raise
            time.sleep(delay_s * (attempt + 1))


def _atomic_write_file(target_path: Path, suffix: str, writer: Any) -> None:
    target_path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="wb",
            dir=target_path.parent,
            delete=False,
            suffix=suffix,
        ) as tf:
            tmp_path = Path(tf.name)
        writer(tmp_path)
        _atomic_replace(tmp_path, target_path)
    except Exception:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:  # pragma: no cover
                pass
        raise


def _load(name: str) -> dict:
    with _LOCK:
        p = _design_path(name)
        if not p.exists():
            raise SilhouetteValueError(f"Design '{name}' does not exist. Call silhouette_new_design first.")
        return json.loads(p.read_text(encoding="utf-8"))


def _save(d: dict) -> None:
    with _LOCK:
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        target_path = _design_path(d["name"])
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=OUTPUT_DIR,
                delete=False,
                encoding="utf-8",
                suffix=".tmp",
            ) as tf:
                tmp_path = Path(tf.name)
                tf.write(json.dumps(d, indent=1))
                tf.flush()
                os.fsync(tf.fileno())
            _atomic_replace(tmp_path, target_path)
        except Exception:
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:  # pragma: no cover
                    pass
            raise


def _num(**kw: Any) -> None:
    for k, v in kw.items():
        if isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v):
            raise SilhouetteValueError(f"{k} must be a finite number")


def _pos(**kw: Any) -> None:
    _num(**kw)
    for k, v in kw.items():
        if v <= 0:
            raise SilhouetteValueError(f"{k} must be > 0")


def _int(**kw: Any) -> None:
    for k, v in kw.items():
        if isinstance(v, bool) or not isinstance(v, int):
            raise SilhouetteValueError(f"{k} must be an integer")


def _norm_layer(layer: str, default: str = "CUT") -> str:
    return str(layer).strip().upper() or default


def _fmt(v: float) -> str:
    return f"{v:.4f}".rstrip("0").rstrip(".") or "0"


def _bbox(s: dict) -> tuple[float, float, float, float]:
    if s["kind"] == "circle":
        return (s["cx"] - s["r"], s["cy"] - s["r"], s["cx"] + s["r"], s["cy"] + s["r"])
    xs = [p[0] for p in s["points"]]
    ys = [p[1] for p in s["points"]]
    return (min(xs), min(ys), max(xs), max(ys))


def _union_bbox(shapes: list[dict]) -> tuple[float, float, float, float] | None:
    if not shapes:
        return None
    bs = [_bbox(s) for s in shapes]
    return (min(b[0] for b in bs), min(b[1] for b in bs), max(b[2] for b in bs), max(b[3] for b in bs))


def _r4(b: tuple[float, float, float, float] | None) -> list[float] | None:
    return [round(v, 3) for v in b] if b else None


def _shape_warnings(d: dict, s: dict) -> list[str]:
    x0, y0, x1, y1 = _bbox(s)
    W, H, m = d["width_mm"], d["height_mm"], d["cut_margin_mm"]
    w: list[str] = []
    if x0 < 0 or y0 < 0 or x1 > W or y1 > H:
        w.append("extends outside the page")
    elif x0 < m or y0 < m or x1 > W - m or y1 > H - m:
        w.append(f"inside the {m} mm safety margin; may fall outside the real cutting area")

    # Camadas nao-corte (vincos, picotes, gravacao, marcas) podem ter tracos ou bracos finos
    if s.get("layer", "CUT") in _NON_CUT_LAYERS:
        pass
    elif s.get("kind") == "poly" and not s.get("closed", True):
        if max(x1 - x0, y1 - y0) < MIN_FEATURE_MM:
            w.append(f"smaller than {MIN_FEATURE_MM} mm; fine details may not cut cleanly")
    else:
        if min(x1 - x0, y1 - y0) < MIN_FEATURE_MM:
            w.append(f"smaller than {MIN_FEATURE_MM} mm; fine details may not cut cleanly")
    return w


def _append_shape_in_memory(d: dict, label: str, **geom: Any) -> dict:
    if len(d["shapes"]) >= MAX_SHAPES:
        raise SilhouetteValueError(f"Design has reached the limit of {MAX_SHAPES} shapes.")
    sid = d["next_id"]
    d["next_id"] += 1
    layer = _norm_layer(geom.pop("layer", "CUT"))
    s: dict[str, Any] = {"id": sid, "label": label, "layer": layer, **geom}
    if s["kind"] == "poly":
        s["points"] = [[round(float(x), 4), round(float(y), 4)] for x, y in s["points"]]
    d["shapes"].append(s)
    return s


def _add(design: str, label: str, **geom: Any) -> dict:
    with _LOCK:
        d = _load(design)
        s = _append_shape_in_memory(d, label, **geom)
        _save(d)
        return {
            "design": d["name"],
            "shape_id": s["id"],
            "layer": s["layer"],
            "bbox_mm": _r4(_bbox(s)),
            "warnings": _shape_warnings(d, s),
        }


# ------------------------------------------------------------------- geometria


def _n_segments(r: float, sweep: float) -> int:
    r = max(r, 1e-6)
    step = math.pi / 2 if r <= CHORD_TOL_MM else 2 * math.acos(1 - CHORD_TOL_MM / r)
    return max(2, math.ceil(abs(sweep) / step))


def _arc(cx: float, cy: float, rx: float, ry: float, a0: float, a1: float) -> list[tuple[float, float]]:
    n = _n_segments(max(rx, ry), a1 - a0)
    return [
        (cx + rx * math.cos(a0 + (a1 - a0) * i / n), cy + ry * math.sin(a0 + (a1 - a0) * i / n))
        for i in range(n + 1)
    ]


def _dedupe_closed(pts: list[Any]) -> list[Any]:
    out: list[Any] = []
    for p in pts:
        if not out or math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-6:
            out.append(p)
    if len(out) > 1 and math.hypot(out[0][0] - out[-1][0], out[0][1] - out[-1][1]) <= 1e-6:
        out.pop()
    return out


def _rotate(pts: list[Any], cx: float, cy: float, deg: float) -> list[tuple[float, float]]:
    if not deg:
        return [(float(x), float(y)) for x, y in pts]
    a = math.radians(deg)
    c, s = math.cos(a), math.sin(a)
    return [(cx + (x - cx) * c - (y - cy) * s, cy + (x - cx) * s + (y - cy) * c) for x, y in pts]


def _rounded_rect(x: float, y: float, w: float, h: float, r: float) -> list[tuple[float, float]]:
    if r <= 0:
        return [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    d = math.pi / 180
    pts: list[tuple[float, float]] = []
    pts += _arc(x + r, y + r, r, r, 180 * d, 270 * d)          # topo-esquerdo
    pts += _arc(x + w - r, y + r, r, r, 270 * d, 360 * d)      # topo-direito
    pts += _arc(x + w - r, y + h - r, r, r, 0, 90 * d)         # base-direita
    pts += _arc(x + r, y + h - r, r, r, 90 * d, 180 * d)       # base-esquerda
    return _dedupe_closed(pts)


def _eval_cubic(p0: tuple[float, float], p1: tuple[float, float], p2: tuple[float, float], p3: tuple[float, float], n: int) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for i in range(1, n + 1):
        t = i / n
        mt = 1.0 - t
        x = (mt ** 3) * p0[0] + 3 * (mt ** 2) * t * p1[0] + 3 * mt * (t ** 2) * p2[0] + (t ** 3) * p3[0]
        y = (mt ** 3) * p0[1] + 3 * (mt ** 2) * t * p1[1] + 3 * mt * (t ** 2) * p2[1] + (t ** 3) * p3[1]
        pts.append((x, y))
    return pts


def _eval_quad(p0: tuple[float, float], p1: tuple[float, float], p2: tuple[float, float], n: int = 8) -> list[tuple[float, float]]:
    pts: list[tuple[float, float]] = []
    for i in range(1, n + 1):
        t = i / n
        mt = 1.0 - t
        x = (mt ** 2) * p0[0] + 2 * mt * t * p1[0] + (t ** 2) * p2[0]
        y = (mt ** 2) * p0[1] + 2 * mt * t * p1[1] + (t ** 2) * p2[1]
        pts.append((x, y))
    return pts


def _offset_polygon(pts_in: list[Any], offset_mm: float, join: str) -> list[tuple[float, float]]:
    pts = _dedupe_closed([(float(p[0]), float(p[1])) for p in pts_in])
    n = len(pts)
    if n < 3:
        raise SilhouetteValueError("Polygon must have at least 3 distinct vertices")

    # Area assinada (shoelace) em Y-down: > 0 indica sentido horario visual
    area2 = sum(pts[i][0] * pts[(i + 1) % n][1] - pts[(i + 1) % n][0] * pts[i][1] for i in range(n))
    if abs(area2) <= 1e-6:
        raise SilhouetteValueError("Shape has zero area and cannot be offset")
    orient = 1.0 if area2 > 0 else -1.0

    edges: list[tuple[tuple[float, float], tuple[float, float]]] = []
    for i in range(n):
        p0, p1 = pts[i], pts[(i + 1) % n]
        dx, dy = p1[0] - p0[0], p1[1] - p0[1]
        length = math.hypot(dx, dy)
        if length <= 1e-8:
            continue
        ux, uy = dx / length, dy / length
        nx, ny = orient * uy, -orient * ux
        edges.append(((ux, uy), (nx, ny)))

    m = len(edges)
    if m < 3:
        raise SilhouetteValueError("Polygon must have at least 3 non-degenerate edges")

    # Reconstroi vertices correspondentes as arestas validas
    clean_pts: list[tuple[float, float]] = []
    for i in range(n):
        p0, p1 = pts[i], pts[(i + 1) % n]
        if math.hypot(p1[0] - p0[0], p1[1] - p0[1]) > 1e-8:
            clean_pts.append(p0)

    out: list[tuple[float, float]] = []
    miter_limit = abs(offset_mm) * 4.0

    for i in range(m):
        u_prev, n_prev = edges[(i - 1) % m]
        u_curr, n_curr = edges[i]
        v = clean_pts[i]

        a_prev = (v[0] + offset_mm * n_prev[0], v[1] + offset_mm * n_prev[1])
        a_curr = (v[0] + offset_mm * n_curr[0], v[1] + offset_mm * n_curr[1])

        cross = u_prev[0] * u_curr[1] - u_prev[1] * u_curr[0]
        is_outer_corner = (orient * offset_mm * cross) > 1e-6

        if abs(cross) <= 1e-6:
            out.append(a_curr)
            continue

        if is_outer_corner and join == "round":
            ang0 = math.atan2(a_prev[1] - v[1], a_prev[0] - v[0])
            ang1 = math.atan2(a_curr[1] - v[1], a_curr[0] - v[0])
            sweep = (ang1 - ang0) % (2 * math.pi)
            if sweep > math.pi:
                sweep -= 2 * math.pi
            arc_pts = _arc(v[0], v[1], abs(offset_mm), abs(offset_mm), ang0, ang0 + sweep)
            out.extend(arc_pts)
        elif is_outer_corner and join == "bevel":
            out.append(a_prev)
            out.append(a_curr)
        else:
            # Intersecao das duas retas deslocadas: a_prev + t * u_prev = a_curr + s * u_curr
            dx, dy = a_curr[0] - a_prev[0], a_curr[1] - a_prev[1]
            t = (dx * u_curr[1] - dy * u_curr[0]) / cross
            ix, iy = a_prev[0] + t * u_prev[0], a_prev[1] + t * u_prev[1]
            if math.hypot(ix - v[0], iy - v[1]) > miter_limit:
                out.append(a_prev)
                out.append(a_curr)
            else:
                out.append((ix, iy))

    result = _dedupe_closed(out)
    if len(result) < 3:
        raise SilhouetteValueError("Inward offset is too large for this shape")
    m_res = len(result)
    new_area2 = sum(
        result[i][0] * result[(i + 1) % m_res][1] - result[(i + 1) % m_res][0] * result[i][1]
        for i in range(m_res)
    )
    if new_area2 * area2 <= 1e-6:
        raise SilhouetteValueError("Inward offset is too large for this shape")
    xs = [p[0] for p in result]
    ys = [p[1] for p in result]
    if max(xs) - min(xs) < 0.2 or max(ys) - min(ys) < 0.2:
        raise SilhouetteValueError("Inward offset is too large for this shape")
    return result


# ----------------------------------------------------------------------- tools


@mcp.tool(annotations=_ann(read_only=True, idempotent=True))
def silhouette_list_page_presets() -> dict:
    """List the built-in page/mat presets (name -> width/height in mm). These are page
    sizes, not the exact cutting area of the machine; keep a safety margin."""
    return {k: {"width_mm": v[0], "height_mm": v[1]} for k, v in PRESETS.items()}


@mcp.tool(annotations=_ann(destructive=True, idempotent=True))
def silhouette_new_design(
    name: str,
    preset: str = "mat-12x12",
    width_mm: float = 0,
    height_mm: float = 0,
    cut_margin_mm: float = 5,
    overwrite: bool = False,
) -> dict:
    """Create an empty design (the working canvas). Use a preset (see
    silhouette_list_page_presets) or give custom width_mm AND height_mm (they override
    the preset). cut_margin_mm is a safety margin used only for warnings.
    Fails if the design exists unless overwrite=true."""
    if width_mm or height_mm:
        _pos(width_mm=width_mm, height_mm=height_mm)
        W, H = float(width_mm), float(height_mm)
    else:
        if preset not in PRESETS:
            raise SilhouetteValueError(f"Unknown preset '{preset}'. Options: {', '.join(PRESETS)}")
        W, H = PRESETS[preset]
    _num(cut_margin_mm=cut_margin_mm)
    if cut_margin_mm < 0 or cut_margin_mm * 2 >= min(W, H):
        raise SilhouetteValueError("cut_margin_mm must be >= 0 and smaller than half of the page")
    with _LOCK:
        if _design_path(name).exists() and not overwrite:
            raise SilhouetteValueError(f"Design '{name}' already exists. Use overwrite=true or another name.")
        d = {
            "name": _slug(name),
            "width_mm": W,
            "height_mm": H,
            "cut_margin_mm": float(cut_margin_mm),
            "next_id": 1,
            "shapes": [],
        }
        _save(d)
        return {"design": d["name"], "width_mm": W, "height_mm": H, "folder": str(OUTPUT_DIR)}


@mcp.tool(annotations=_ann(read_only=True, idempotent=True))
def silhouette_list_designs() -> dict:
    """List the designs saved in the output folder along with exported files if any."""
    with _LOCK:
        out = []
        if OUTPUT_DIR.exists():
            for p in sorted(OUTPUT_DIR.glob("*.design.json")):
                try:
                    d = json.loads(p.read_text(encoding="utf-8"))
                    name = d["name"]
                    has_dxf = (OUTPUT_DIR / f"{name}.dxf").is_file()
                    has_svg = (OUTPUT_DIR / f"{name}.svg").is_file()
                    has_png = (OUTPUT_DIR / f"{name}.png").is_file()
                    out.append({
                        "design": name,
                        "shapes": len(d["shapes"]),
                        "width_mm": d["width_mm"],
                        "height_mm": d["height_mm"],
                        "dxf_exported": has_dxf,
                        "svg_exported": has_svg,
                        "png_exported": has_png,
                    })
                except Exception as e:
                    out.append({"file": p.name, "error": str(e)})
        return {"folder": str(OUTPUT_DIR), "designs": out}


@mcp.tool(annotations=_ann(read_only=True, idempotent=True))
def silhouette_get_design(design: str) -> dict:
    """Get the full raw JSON data of a design, including all shapes and canvas properties."""
    return _load(design)


@mcp.tool(annotations=_ann(destructive=True))
def silhouette_delete_design(design: str, delete_files: bool = False) -> dict:
    """Delete a design file. If delete_files=true, also removes any exported .dxf, .svg and .png files."""
    with _LOCK:
        slug = _slug(design)
        p = _design_path(slug)
        if not p.exists():
            raise SilhouetteValueError(f"Design '{design}' does not exist.")
        p.unlink()
        deleted_files = [str(p)]
        if delete_files:
            for ext in (".dxf", ".svg", ".png"):
                ef = OUTPUT_DIR / f"{slug}{ext}"
                if ef.exists():
                    ef.unlink()
                    deleted_files.append(str(ef))
        return {"deleted_design": slug, "deleted_files": deleted_files}


@mcp.tool(annotations=_ann(destructive=True, idempotent=True))
def silhouette_clear_shapes(design: str) -> dict:
    """Remove all shapes from a design without resetting page dimensions."""
    with _LOCK:
        d = _load(design)
        removed_count = len(d["shapes"])
        d["shapes"] = []
        _save(d)
        return {"design": d["name"], "shapes_removed": removed_count, "shape_count": 0}


@mcp.tool(annotations=_ann())
def silhouette_add_rectangle(
    design: str,
    x_mm: float,
    y_mm: float,
    width_mm: float,
    height_mm: float,
    corner_radius_mm: float = 0,
    rotation_deg: float = 0,
    layer: str = "CUT",
    label: str = "",
) -> dict:
    """Add a rectangle whose top-left corner is at (x_mm, y_mm). corner_radius_mm > 0
    rounds the corners (clamped to half of the smaller side). rotation_deg rotates clockwise
    around the rectangle center. layer defaults to 'CUT' (or 'SCORE', 'PERF')."""
    _num(x_mm=x_mm, y_mm=y_mm, corner_radius_mm=corner_radius_mm, rotation_deg=rotation_deg)
    _pos(width_mm=width_mm, height_mm=height_mm)
    r = max(0.0, min(corner_radius_mm, width_mm / 2, height_mm / 2))
    pts = _rounded_rect(x_mm, y_mm, width_mm, height_mm, r)
    if rotation_deg:
        cx = x_mm + width_mm / 2
        cy = y_mm + height_mm / 2
        pts = _rotate(pts, cx, cy, rotation_deg)
    return _add(design, label or "rectangle", kind="poly", closed=True,
                points=pts, layer=layer)


@mcp.tool(annotations=_ann())
def silhouette_add_circle(
    design: str, cx_mm: float, cy_mm: float, radius_mm: float, layer: str = "CUT", label: str = ""
) -> dict:
    """Add a circle centred at (cx_mm, cy_mm). Exported as a true DXF CIRCLE."""
    _num(cx_mm=cx_mm, cy_mm=cy_mm)
    _pos(radius_mm=radius_mm)
    return _add(design, label or "circle", kind="circle", cx=cx_mm, cy=cy_mm, r=radius_mm, layer=layer)


@mcp.tool(annotations=_ann())
def silhouette_add_ellipse(
    design: str, cx_mm: float, cy_mm: float, rx_mm: float, ry_mm: float,
    rotation_deg: float = 0, layer: str = "CUT", label: str = "",
) -> dict:
    """Add an ellipse centred at (cx_mm, cy_mm) with radii rx_mm (horizontal) and ry_mm
    (vertical), rotated clockwise by rotation_deg."""
    _num(cx_mm=cx_mm, cy_mm=cy_mm, rotation_deg=rotation_deg)
    _pos(rx_mm=rx_mm, ry_mm=ry_mm)
    pts = _dedupe_closed(_arc(cx_mm, cy_mm, rx_mm, ry_mm, 0, 2 * math.pi))
    return _add(design, label or "ellipse", kind="poly", closed=True,
                points=_rotate(pts, cx_mm, cy_mm, rotation_deg), layer=layer)


@mcp.tool(annotations=_ann())
def silhouette_add_polygon(
    design: str, cx_mm: float, cy_mm: float, radius_mm: float, sides: int,
    rotation_deg: float = 0, layer: str = "CUT", label: str = "",
) -> dict:
    """Add a regular polygon (3-64 sides) inscribed in a circle of radius_mm, centred at
    (cx_mm, cy_mm). With rotation_deg=0 one vertex points up."""
    _num(cx_mm=cx_mm, cy_mm=cy_mm, rotation_deg=rotation_deg)
    _pos(radius_mm=radius_mm)
    if isinstance(sides, bool) or not isinstance(sides, int) or not 3 <= sides <= 64:
        raise SilhouetteValueError("sides must be an integer between 3 and 64")
    a0 = math.radians(rotation_deg) - math.pi / 2
    pts = [(cx_mm + radius_mm * math.cos(a0 + 2 * math.pi * k / sides),
            cy_mm + radius_mm * math.sin(a0 + 2 * math.pi * k / sides)) for k in range(sides)]
    return _add(design, label or f"polygon-{sides}", kind="poly", closed=True, points=pts, layer=layer)


@mcp.tool(annotations=_ann())
def silhouette_add_star(
    design: str, cx_mm: float, cy_mm: float, outer_radius_mm: float, inner_radius_mm: float,
    points: int = 5, rotation_deg: float = 0, layer: str = "CUT", label: str = "",
) -> dict:
    """Add a star with the given number of points (3-64). inner_radius_mm must be smaller
    than outer_radius_mm (about 40% gives a classic star). With rotation_deg=0 one tip points up."""
    _num(cx_mm=cx_mm, cy_mm=cy_mm, rotation_deg=rotation_deg)
    _pos(outer_radius_mm=outer_radius_mm, inner_radius_mm=inner_radius_mm)
    if inner_radius_mm >= outer_radius_mm:
        raise SilhouetteValueError("inner_radius_mm must be smaller than outer_radius_mm")
    if isinstance(points, bool) or not isinstance(points, int) or not 3 <= points <= 64:
        raise SilhouetteValueError("points must be an integer between 3 and 64")
    a0 = math.radians(rotation_deg) - math.pi / 2
    pts = []
    for k in range(points * 2):
        r = outer_radius_mm if k % 2 == 0 else inner_radius_mm
        a = a0 + math.pi * k / points
        pts.append((cx_mm + r * math.cos(a), cy_mm + r * math.sin(a)))
    return _add(design, label or f"star-{points}", kind="poly", closed=True, points=pts, layer=layer)


def _add_line_to_doc(
    d: dict,
    x1_mm: float,
    y1_mm: float,
    x2_mm: float,
    y2_mm: float,
    *,
    dashed: bool = False,
    dash_len_mm: float = 3.0,
    gap_len_mm: float = 2.0,
    layer: str = "CUT",
    label: str = "",
) -> list[dict]:
    _num(x1_mm=x1_mm, y1_mm=y1_mm, x2_mm=x2_mm, y2_mm=y2_mm)
    length = math.hypot(x2_mm - x1_mm, y2_mm - y1_mm)
    if length <= 1e-4:
        raise SilhouetteValueError("Line length must be greater than zero")

    if not dashed:
        s = _append_shape_in_memory(d, label or "line", kind="poly", closed=False,
                                    points=[(x1_mm, y1_mm), (x2_mm, y2_mm)], layer=layer)
        return [s]

    _pos(dash_len_mm=dash_len_mm, gap_len_mm=gap_len_mm)
    norm_layer = _norm_layer(layer)
    dx = (x2_mm - x1_mm) / length
    dy = (y2_mm - y1_mm) / length
    step = dash_len_mm + gap_len_mm
    t = 0.0
    idx = 1
    added_shapes: list[dict] = []
    base_label = label or "dash-line"

    while t < length:
        t_end = min(t + dash_len_mm, length)
        if t_end - t >= 0.1:  # ignora fragmentos microscopicos
            if len(d["shapes"]) >= MAX_SHAPES:
                raise SilhouetteValueError(f"Design has reached the limit of {MAX_SHAPES} shapes.")
            p0 = (x1_mm + dx * t, y1_mm + dy * t)
            p1 = (x1_mm + dx * t_end, y1_mm + dy * t_end)
            sid = d["next_id"]
            d["next_id"] += 1
            s = {
                "id": sid,
                "label": f"{base_label}#{idx}",
                "layer": norm_layer,
                "kind": "poly",
                "closed": False,
                "points": [[round(p0[0], 4), round(p0[1], 4)], [round(p1[0], 4), round(p1[1], 4)]],
            }
            d["shapes"].append(s)
            added_shapes.append(s)
            idx += 1
        t += step
    return added_shapes


@mcp.tool(annotations=_ann())
def silhouette_add_line(
    design: str,
    x1_mm: float,
    y1_mm: float,
    x2_mm: float,
    y2_mm: float,
    dashed: bool = False,
    dash_len_mm: float = 3.0,
    gap_len_mm: float = 2.0,
    layer: str = "CUT",
    label: str = "",
) -> dict:
    """Add a straight line between (x1_mm, y1_mm) and (x2_mm, y2_mm).
    If dashed=true, creates perforated segments ideal for folding cardstock/papercraft.
    dash_len_mm: cut segment length (default 3mm); gap_len_mm: un-cut gap length (default 2mm).
    layer: 'CUT', 'SCORE', 'PERF', etc."""
    _num(x1_mm=x1_mm, y1_mm=y1_mm, x2_mm=x2_mm, y2_mm=y2_mm)
    length = math.hypot(x2_mm - x1_mm, y2_mm - y1_mm)
    if length <= 1e-4:
        raise SilhouetteValueError("Line length must be greater than zero")

    if not dashed:
        return _add(design, label or "line", kind="poly", closed=False,
                    points=[(x1_mm, y1_mm), (x2_mm, y2_mm)], layer=layer)

    _pos(dash_len_mm=dash_len_mm, gap_len_mm=gap_len_mm)
    with _LOCK:
        d = _load(design)
        added_shapes = _add_line_to_doc(
            d, x1_mm, y1_mm, x2_mm, y2_mm,
            dashed=True, dash_len_mm=dash_len_mm, gap_len_mm=gap_len_mm,
            layer=layer, label=label,
        )
        _save(d)
        return {
            "design": d["name"],
            "segments_added": len(added_shapes),
            "shape_ids": [s["id"] for s in added_shapes],
            "layer": _norm_layer(layer),
            "bbox_mm": _r4(_union_bbox(added_shapes)),
        }


@mcp.tool(annotations=_ann())
def silhouette_add_polyline(
    design: str, points: list[list[float]], closed: bool = True, layer: str = "CUT", label: str = ""
) -> dict:
    """Add a custom path through the given [x, y] points (in mm, Y down). closed=true
    makes a closed shape (>= 3 points); closed=false makes an open line (>= 2 points)."""
    if not isinstance(points, list) or any(not isinstance(p, (list, tuple)) or len(p) != 2 for p in points):
        raise SilhouetteValueError("points must be a list of [x, y] pairs")
    for p in points:
        _num(x=p[0], y=p[1])
    need = 3 if closed else 2
    if len(points) < need:
        raise SilhouetteValueError(f"Need at least {need} points")
    if len(points) > 20000:
        raise SilhouetteValueError("Too many points (max 20000)")
    return _add(design, label or "polyline", kind="poly", closed=bool(closed),
                points=[(float(p[0]), float(p[1])) for p in points], layer=layer)


# ------------------------------------------------------------ texto vetorial


_FONT_ALIASES = {
    "arial": ["arial.ttf", "arialbd.ttf", "DejaVuSans.ttf", "LiberationSans-Regular.ttf"],
    "arial bold": ["arialbd.ttf", "DejaVuSans-Bold.ttf"],
    "times": ["times.ttf", "timesnewroman.ttf", "DejaVuSerif.ttf", "LiberationSerif-Regular.ttf"],
    "times new roman": ["times.ttf", "timesnewroman.ttf", "DejaVuSerif.ttf"],
    "georgia": ["georgia.ttf", "DejaVuSerif.ttf"],
    "impact": ["impact.ttf", "DejaVuSans-Bold.ttf"],
    "verdana": ["verdana.ttf", "DejaVuSans.ttf"],
    "trebuchet": ["trebuc.ttf", "DejaVuSans.ttf"],
    "segoe ui": ["segoeui.ttf", "DejaVuSans.ttf"],
    "courier": ["cour.ttf", "DejaVuSansMono.ttf"],
    "courier new": ["cour.ttf", "DejaVuSansMono.ttf"],
    "comic sans": ["comic.ttf"],
    "calibri": ["calibri.ttf"],
    "consolas": ["consola.ttf"],
}

_FONT_DIRS = [
    Path(r"C:\Windows\Fonts"),
    Path.home() / "AppData/Local/Microsoft/Windows/Fonts",
    Path("/System/Library/Fonts"),
    Path("/Library/Fonts"),
    Path("/usr/share/fonts"),
    Path.home() / ".local/share/fonts",
]

# Contornos geometricos simples (unidade 0..1 largura, 0..1 altura) usados como fallback sem fonte no OS
_FALLBACK_GLYPHS: dict[str, list[list[tuple[float, float]]]] = {
    "A": [[(0.0, 1.0), (0.4, 0.0), (0.6, 0.0), (1.0, 1.0), (0.8, 1.0), (0.7, 0.72), (0.3, 0.72), (0.2, 1.0)], [(0.36, 0.56), (0.64, 0.56), (0.5, 0.18)]],
    "B": [[(0.0, 0.0), (0.72, 0.0), (0.9, 0.15), (0.9, 0.38), (0.75, 0.48), (0.95, 0.6), (0.95, 0.85), (0.75, 1.0), (0.0, 1.0)]],
    "C": [[(0.95, 0.18), (0.75, 0.0), (0.25, 0.0), (0.0, 0.25), (0.0, 0.75), (0.25, 1.0), (0.75, 1.0), (0.95, 0.82), (0.8, 0.72), (0.65, 0.85), (0.32, 0.85), (0.18, 0.7), (0.18, 0.3), (0.32, 0.15), (0.65, 0.15), (0.8, 0.28)]],
    "D": [[(0.0, 0.0), (0.68, 0.0), (0.95, 0.25), (0.95, 0.75), (0.68, 1.0), (0.0, 1.0)], [(0.2, 0.18), (0.6, 0.18), (0.76, 0.32), (0.76, 0.68), (0.6, 0.82), (0.2, 0.82)]],
    "E": [[(0.0, 0.0), (0.9, 0.0), (0.9, 0.18), (0.2, 0.18), (0.2, 0.41), (0.78, 0.41), (0.78, 0.59), (0.2, 0.59), (0.2, 0.82), (0.9, 0.82), (0.9, 1.0), (0.0, 1.0)]],
    "F": [[(0.0, 0.0), (0.9, 0.0), (0.9, 0.18), (0.2, 0.18), (0.2, 0.42), (0.76, 0.42), (0.76, 0.6), (0.2, 0.6), (0.2, 1.0), (0.0, 1.0)]],
    "G": [[(0.95, 0.2), (0.72, 0.0), (0.25, 0.0), (0.0, 0.25), (0.0, 0.75), (0.25, 1.0), (0.78, 1.0), (0.96, 0.8), (0.96, 0.48), (0.5, 0.48), (0.5, 0.64), (0.78, 0.64), (0.78, 0.78), (0.65, 0.84), (0.32, 0.84), (0.18, 0.7), (0.18, 0.3), (0.32, 0.16), (0.68, 0.16), (0.8, 0.28)]],
    "H": [[(0.0, 0.0), (0.2, 0.0), (0.2, 0.41), (0.8, 0.41), (0.8, 0.0), (1.0, 0.0), (1.0, 1.0), (0.8, 1.0), (0.8, 0.59), (0.2, 0.59), (0.2, 1.0), (0.0, 1.0)]],
    "I": [[(0.15, 0.0), (0.85, 0.0), (0.85, 0.18), (0.6, 0.18), (0.6, 0.82), (0.85, 0.82), (0.85, 1.0), (0.15, 1.0), (0.15, 0.82), (0.4, 0.82), (0.4, 0.18), (0.15, 0.18)]],
    "J": [[(0.35, 0.0), (0.95, 0.0), (0.95, 0.76), (0.72, 1.0), (0.26, 1.0), (0.05, 0.8), (0.2, 0.66), (0.34, 0.82), (0.62, 0.82), (0.75, 0.7), (0.75, 0.18), (0.35, 0.18)]],
    "K": [[(0.0, 0.0), (0.2, 0.0), (0.2, 0.42), (0.72, 0.0), (0.98, 0.0), (0.45, 0.48), (1.0, 1.0), (0.73, 1.0), (0.2, 0.54), (0.2, 1.0), (0.0, 1.0)]],
    "L": [[(0.0, 0.0), (0.2, 0.0), (0.2, 0.82), (0.9, 0.82), (0.9, 1.0), (0.0, 1.0)]],
    "M": [[(0.0, 0.0), (0.22, 0.0), (0.5, 0.45), (0.78, 0.0), (1.0, 0.0), (1.0, 1.0), (0.8, 1.0), (0.8, 0.34), (0.5, 0.78), (0.2, 0.34), (0.2, 1.0), (0.0, 1.0)]],
    "N": [[(0.0, 0.0), (0.22, 0.0), (0.8, 0.68), (0.8, 0.0), (1.0, 0.0), (1.0, 1.0), (0.78, 1.0), (0.2, 0.32), (0.2, 1.0), (0.0, 1.0)]],
    "O": [[(0.25, 0.0), (0.75, 0.0), (1.0, 0.25), (1.0, 0.75), (0.75, 1.0), (0.25, 1.0), (0.0, 0.75), (0.0, 0.25)], [(0.34, 0.18), (0.66, 0.18), (0.82, 0.34), (0.82, 0.66), (0.66, 0.82), (0.34, 0.82), (0.18, 0.66), (0.18, 0.34)]],
    "P": [[(0.0, 0.0), (0.75, 0.0), (0.96, 0.18), (0.96, 0.44), (0.75, 0.6), (0.2, 0.6), (0.2, 1.0), (0.0, 1.0)], [(0.2, 0.17), (0.66, 0.17), (0.76, 0.25), (0.76, 0.36), (0.66, 0.44), (0.2, 0.44)]],
    "Q": [[(0.25, 0.0), (0.75, 0.0), (1.0, 0.25), (1.0, 0.75), (0.84, 0.9), (1.0, 1.02), (0.84, 1.12), (0.68, 0.98), (0.25, 1.0), (0.0, 0.75), (0.0, 0.25)], [(0.34, 0.18), (0.66, 0.18), (0.82, 0.34), (0.82, 0.66), (0.66, 0.82), (0.34, 0.82), (0.18, 0.66), (0.18, 0.34)]],
    "R": [[(0.0, 0.0), (0.75, 0.0), (0.96, 0.18), (0.96, 0.44), (0.72, 0.58), (0.98, 1.0), (0.74, 1.0), (0.5, 0.6), (0.2, 0.6), (0.2, 1.0), (0.0, 1.0)], [(0.2, 0.17), (0.66, 0.17), (0.76, 0.25), (0.76, 0.36), (0.66, 0.44), (0.2, 0.44)]],
    "S": [[(0.92, 0.16), (0.72, 0.0), (0.24, 0.0), (0.04, 0.18), (0.04, 0.4), (0.24, 0.54), (0.72, 0.62), (0.78, 0.72), (0.72, 0.83), (0.28, 0.83), (0.14, 0.72), (0.02, 0.85), (0.24, 1.0), (0.76, 1.0), (0.96, 0.82), (0.96, 0.58), (0.76, 0.44), (0.28, 0.36), (0.22, 0.26), (0.28, 0.17), (0.7, 0.17), (0.82, 0.26)]],
    "T": [[(0.0, 0.0), (1.0, 0.0), (1.0, 0.18), (0.6, 0.18), (0.6, 1.0), (0.4, 1.0), (0.4, 0.18), (0.0, 0.18)]],
    "U": [[(0.0, 0.0), (0.2, 0.0), (0.2, 0.72), (0.34, 0.84), (0.66, 0.84), (0.8, 0.72), (0.8, 0.0), (1.0, 0.0), (1.0, 0.78), (0.76, 1.0), (0.24, 1.0), (0.0, 0.78)]],
    "V": [[(0.0, 0.0), (0.22, 0.0), (0.5, 0.76), (0.78, 0.0), (1.0, 0.0), (0.6, 1.0), (0.4, 1.0)]],
    "W": [[(0.0, 0.0), (0.2, 0.0), (0.32, 0.68), (0.5, 0.25), (0.68, 0.68), (0.8, 0.0), (1.0, 0.0), (0.78, 1.0), (0.58, 1.0), (0.5, 0.62), (0.42, 1.0), (0.22, 1.0)]],
    "X": [[(0.0, 0.0), (0.24, 0.0), (0.5, 0.35), (0.76, 0.0), (1.0, 0.0), (0.63, 0.5), (1.0, 1.0), (0.76, 1.0), (0.5, 0.65), (0.24, 1.0), (0.0, 1.0), (0.37, 0.5)]],
    "Y": [[(0.0, 0.0), (0.24, 0.0), (0.5, 0.42), (0.76, 0.0), (1.0, 0.0), (0.6, 0.58), (0.6, 1.0), (0.4, 1.0), (0.4, 0.58)]],
    "Z": [[(0.0, 0.0), (1.0, 0.0), (1.0, 0.18), (0.28, 0.82), (1.0, 0.82), (1.0, 1.0), (0.0, 1.0), (0.0, 0.82), (0.72, 0.18), (0.0, 0.18)]],
    "0": [[(0.25, 0.0), (0.75, 0.0), (0.95, 0.22), (0.95, 0.78), (0.75, 1.0), (0.25, 1.0), (0.05, 0.78), (0.05, 0.22)], [(0.34, 0.18), (0.66, 0.18), (0.77, 0.3), (0.77, 0.7), (0.66, 0.82), (0.34, 0.82), (0.23, 0.7), (0.23, 0.3)]],
    "1": [[(0.2, 0.18), (0.45, 0.0), (0.62, 0.0), (0.62, 0.84), (0.85, 0.84), (0.85, 1.0), (0.15, 1.0), (0.15, 0.84), (0.42, 0.84), (0.42, 0.24), (0.2, 0.34)]],
    "2": [[(0.08, 0.22), (0.28, 0.0), (0.76, 0.0), (0.95, 0.22), (0.95, 0.44), (0.32, 0.83), (0.95, 0.83), (0.95, 1.0), (0.05, 1.0), (0.05, 0.82), (0.74, 0.38), (0.74, 0.24), (0.66, 0.17), (0.35, 0.17), (0.22, 0.32)]],
    "3": [[(0.1, 0.16), (0.3, 0.0), (0.74, 0.0), (0.94, 0.18), (0.94, 0.4), (0.76, 0.5), (0.96, 0.62), (0.96, 0.82), (0.74, 1.0), (0.28, 1.0), (0.08, 0.84), (0.22, 0.7), (0.36, 0.82), (0.68, 0.82), (0.78, 0.74), (0.78, 0.64), (0.64, 0.57), (0.38, 0.57), (0.38, 0.42), (0.64, 0.42), (0.75, 0.34), (0.75, 0.25), (0.66, 0.17), (0.36, 0.17), (0.22, 0.28)]],
    "4": [[(0.6, 0.0), (0.8, 0.0), (0.8, 0.6), (0.98, 0.6), (0.98, 0.77), (0.8, 0.77), (0.8, 1.0), (0.6, 1.0), (0.6, 0.77), (0.04, 0.77), (0.04, 0.6), (0.56, 0.0)], [(0.26, 0.6), (0.6, 0.6), (0.6, 0.22)]],
    "5": [[(0.12, 0.0), (0.9, 0.0), (0.9, 0.18), (0.3, 0.18), (0.28, 0.38), (0.74, 0.38), (0.95, 0.56), (0.95, 0.82), (0.74, 1.0), (0.26, 1.0), (0.06, 0.84), (0.2, 0.7), (0.34, 0.82), (0.66, 0.82), (0.76, 0.74), (0.76, 0.62), (0.64, 0.54), (0.12, 0.54)]],
    "6": [[(0.86, 0.14), (0.68, 0.0), (0.32, 0.0), (0.06, 0.24), (0.06, 0.78), (0.28, 1.0), (0.76, 1.0), (0.96, 0.8), (0.96, 0.56), (0.76, 0.38), (0.26, 0.38), (0.26, 0.28), (0.38, 0.17), (0.66, 0.17), (0.76, 0.26)], [(0.26, 0.56), (0.68, 0.56), (0.77, 0.65), (0.77, 0.76), (0.68, 0.83), (0.34, 0.83), (0.26, 0.75)]],
    "7": [[(0.06, 0.0), (0.94, 0.0), (0.94, 0.18), (0.48, 1.0), (0.26, 1.0), (0.72, 0.18), (0.06, 0.18)]],
    "8": [[(0.24, 0.0), (0.76, 0.0), (0.94, 0.18), (0.94, 0.4), (0.8, 0.5), (0.96, 0.62), (0.96, 0.84), (0.76, 1.0), (0.24, 1.0), (0.04, 0.84), (0.04, 0.62), (0.2, 0.5), (0.06, 0.4), (0.06, 0.18)], [(0.26, 0.18), (0.74, 0.18), (0.74, 0.4), (0.26, 0.4)], [(0.24, 0.58), (0.76, 0.58), (0.76, 0.82), (0.24, 0.82)]],
    "9": [[(0.14, 0.86), (0.32, 1.0), (0.68, 1.0), (0.94, 0.76), (0.94, 0.22), (0.72, 0.0), (0.24, 0.0), (0.04, 0.2), (0.04, 0.44), (0.24, 0.62), (0.74, 0.62), (0.74, 0.72), (0.62, 0.83), (0.34, 0.83), (0.24, 0.74)], [(0.23, 0.24), (0.32, 0.17), (0.66, 0.17), (0.74, 0.25), (0.74, 0.44), (0.32, 0.44), (0.23, 0.35)]],
    "-": [[(0.15, 0.42), (0.85, 0.42), (0.85, 0.58), (0.15, 0.58)]],
    ".": [[(0.38, 0.8), (0.62, 0.8), (0.62, 1.0), (0.38, 1.0)]],
    "!": [[(0.38, 0.0), (0.62, 0.0), (0.58, 0.68), (0.42, 0.68)], [(0.38, 0.8), (0.62, 0.8), (0.62, 1.0), (0.38, 1.0)]],
}


def _resolve_font_path(font: str) -> Path | None:
    raw = str(font or "").strip()
    if raw:
        p = Path(raw).expanduser()
        if p.is_file():
            return p
    key = raw.lower()
    candidates = list(_FONT_ALIASES.get(key, []))
    if raw:
        for ext in ("", ".ttf", ".otf"):
            candidates.insert(0, f"{raw}{ext}")
    for d in _FONT_DIRS:
        if not d.is_dir():
            continue
        for cand in candidates:
            fp = d / cand
            if fp.is_file():
                return fp
        # Busca parcial caso seja subdiretorio no Linux/macOS
        if key:
            for fp in d.rglob("*.ttf"):
                if key in fp.stem.lower():
                    return fp
    # Ultimo fallback: qualquer .ttf valido nas pastas de fonte
    for d in _FONT_DIRS:
        if d.is_dir():
            for fp in sorted(d.glob("*.ttf")):
                return fp
    return None


def _pen_ops_to_contours(ops: list[tuple[str, tuple[Any, ...]]]) -> list[list[tuple[float, float]]]:
    contours: list[list[tuple[float, float]]] = []
    cur: list[tuple[float, float]] = []

    def flush() -> None:
        nonlocal cur
        pts = _dedupe_closed(cur)
        if len(pts) >= 3:
            contours.append(pts)
        cur = []

    for cmd, args in ops:
        if cmd == "moveTo":
            flush()
            cur = [(float(args[0][0]), float(args[0][1]))]
        elif cmd == "lineTo":
            if not cur:
                cur = [(float(args[0][0]), float(args[0][1]))]
            else:
                cur.append((float(args[0][0]), float(args[0][1])))
        elif cmd == "qCurveTo":
            if not args:
                continue
            if args[-1] is None:
                # Contorno fechado apenas com pontos off-curve
                offs = [(float(p[0]), float(p[1])) for p in args[:-1]]
                if len(offs) >= 2:
                    start = ((offs[-1][0] + offs[0][0]) / 2, (offs[-1][1] + offs[0][1]) / 2)
                    cur = [start]
                    for i, ctrl in enumerate(offs):
                        nxt = offs[(i + 1) % len(offs)]
                        on = ((ctrl[0] + nxt[0]) / 2, (ctrl[1] + nxt[1]) / 2)
                        cur.extend(_eval_quad(cur[-1], ctrl, on, n=8))
            else:
                if not cur:
                    cur = [(float(args[0][0]), float(args[0][1]))]
                pts_q = [(float(p[0]), float(p[1])) for p in args]
                for i in range(len(pts_q) - 1):
                    ctrl = pts_q[i]
                    if i == len(pts_q) - 2:
                        on = pts_q[-1]
                    else:
                        nxt = pts_q[i + 1]
                        on = ((ctrl[0] + nxt[0]) / 2, (ctrl[1] + nxt[1]) / 2)
                    cur.extend(_eval_quad(cur[-1], ctrl, on, n=8))
        elif cmd == "curveTo":
            if not cur or len(args) < 3:
                continue
            for idx in range(0, len(args) - 2, 3):
                p1 = (float(args[idx][0]), float(args[idx][1]))
                p2 = (float(args[idx + 1][0]), float(args[idx + 1][1]))
                p3 = (float(args[idx + 2][0]), float(args[idx + 2][1]))
                cur.extend(_eval_cubic(cur[-1], p1, p2, p3, n=10))
        elif cmd in ("closePath", "endPath"):
            flush()
    flush()
    return contours


def _fallback_text_polygons(text: str, size_mm: float, letter_spacing_mm: float) -> list[list[tuple[float, float]]]:
    contours: list[list[tuple[float, float]]] = []
    line_h = size_mm * 1.35
    char_w = size_mm * 0.72
    space_w = size_mm * 0.45
    step_gap = size_mm * 0.16 + letter_spacing_mm

    for line_idx, line in enumerate(text.splitlines() or [text]):
        cx = 0.0
        cy = line_idx * line_h
        for ch in line:
            key = ch.upper()
            if ch.isspace():
                cx += space_w + letter_spacing_mm
                continue
            glyph = _FALLBACK_GLYPHS.get(key)
            if glyph is None:
                # Caixa generica para caractere desconhecido
                glyph = [[(0.1, 0.0), (0.9, 0.0), (0.9, 1.0), (0.1, 1.0)],
                         [(0.25, 0.15), (0.75, 0.15), (0.75, 0.85), (0.25, 0.85)]]
            for poly in glyph:
                contours.append([(cx + px * char_w, cy + py * size_mm) for px, py in poly])
            cx += char_w + step_gap
    return contours


def _font_text_polygons(
    text: str, font_path: Path, size_mm: float, letter_spacing_mm: float
) -> list[list[tuple[float, float]]]:
    from fontTools.pens.recordingPen import DecomposingRecordingPen
    from fontTools.ttLib import TTFont

    tt = TTFont(str(font_path), fontNumber=0)
    try:
        gs = tt.getGlyphSet()
        cmap = tt.getBestCmap() or {}
        hmtx = tt["hmtx"].metrics
        upm = float(tt["head"].unitsPerEm or 1000)
        cap = 0.0
        if "OS/2" in tt and getattr(tt["OS/2"], "sCapHeight", 0):
            cap = float(tt["OS/2"].sCapHeight)
        if cap <= 0:
            cap = upm * 0.72

        scale = size_mm / cap
        line_h = size_mm * 1.35
        space_g = cmap.get(ord(" "))
        space_adv = hmtx[space_g][0] if space_g and space_g in hmtx else upm * 0.3

        contours: list[list[tuple[float, float]]] = []
        for line_idx, line in enumerate(text.splitlines() or [text]):
            cursor_x = 0.0
            baseline_y = line_idx * line_h
            for ch in line:
                if ch.isspace():
                    cursor_x += space_adv * scale + letter_spacing_mm
                    continue
                gname = cmap.get(ord(ch)) or cmap.get(ord(ch.upper())) or ".notdef"
                if gname not in gs:
                    cursor_x += space_adv * scale + letter_spacing_mm
                    continue
                pen = DecomposingRecordingPen(gs)
                gs[gname].draw(pen)
                for poly in _pen_ops_to_contours(pen.value):
                    contours.append([(cursor_x + gx * scale, baseline_y - gy * scale) for gx, gy in poly])
                adv = hmtx[gname][0] if gname in hmtx else upm * 0.5
                cursor_x += adv * scale + letter_spacing_mm
        return contours
    finally:
        tt.close()


@mcp.tool(annotations=_ann())
def silhouette_add_text(
    design: str,
    text: str,
    x_mm: float,
    y_mm: float,
    size_mm: float = 15.0,
    font: str = "Arial",
    align: str = "left",
    letter_spacing_mm: float = 0.0,
    rotation_deg: float = 0.0,
    layer: str = "CUT",
    label: str = "",
) -> dict:
    """Convert text into vector cut/score outlines using a system/custom TTF/OTF font
    (or built-in geometric vector fallback) and add the glyph contours to the design.
    x_mm, y_mm mark the top edge anchored horizontally by align ('left', 'center', 'right')."""
    if not isinstance(text, str) or not text.strip():
        raise SilhouetteValueError("text must be a non-empty string")
    _num(x_mm=x_mm, y_mm=y_mm, letter_spacing_mm=letter_spacing_mm, rotation_deg=rotation_deg)
    _pos(size_mm=size_mm)
    align_norm = str(align).strip().lower()
    if align_norm not in ("left", "center", "right"):
        raise SilhouetteValueError("align must be one of: left, center, right")

    font_path = None if font == "__fallback__" else _resolve_font_path(font)
    used_font = str(font_path) if font_path else "builtin-vector-fallback"
    if font_path is not None:
        try:
            contours = _font_text_polygons(text, font_path, float(size_mm), float(letter_spacing_mm))
        except Exception:
            contours = _fallback_text_polygons(text, float(size_mm), float(letter_spacing_mm))
            used_font = "builtin-vector-fallback"
    else:
        contours = _fallback_text_polygons(text, float(size_mm), float(letter_spacing_mm))

    if not contours:
        raise SilhouetteValueError("Could not generate any vector contours for the given text")

    all_x = [p[0] for c in contours for p in c]
    all_y = [p[1] for c in contours for p in c]
    min_x, max_x = min(all_x), max(all_x)
    min_y, max_y = min(all_y), max(all_y)

    if align_norm == "left":
        dx = x_mm - min_x
    elif align_norm == "center":
        dx = x_mm - (min_x + max_x) / 2.0
    else:
        dx = x_mm - max_x
    dy = y_mm - min_y

    cx = (min_x + max_x) / 2.0 + dx
    cy = (min_y + max_y) / 2.0 + dy

    transformed: list[list[tuple[float, float]]] = []
    for poly in contours:
        shifted = [(px + dx, py + dy) for px, py in poly]
        if rotation_deg:
            shifted = _rotate(shifted, cx, cy, rotation_deg)
        transformed.append(shifted)

    base_label = label or f"text:{text.strip()[:20]}"
    with _LOCK:
        d = _load(design)
        if len(d["shapes"]) + len(transformed) > MAX_SHAPES:
            raise SilhouetteValueError(f"Design has reached the limit of {MAX_SHAPES} shapes.")
        added_shapes: list[dict] = []
        for idx, poly in enumerate(transformed, 1):
            s = _append_shape_in_memory(
                d, f"{base_label}#{idx}", kind="poly", closed=True, points=poly, layer=layer
            )
            added_shapes.append(s)
        _save(d)
        warnings = [
            f"shape {s['id']} ({s['label']}): {w}"
            for s in added_shapes
            for w in _shape_warnings(d, s)
        ]
        return {
            "design": d["name"],
            "contours_added": len(added_shapes),
            "shape_ids": [s["id"] for s in added_shapes],
            "font_used": used_font,
            "layer": _norm_layer(layer),
            "bbox_mm": _r4(_union_bbox(added_shapes)),
            "warnings": warnings,
        }


# ------------------------------------------------ transformacoes & organizacao


@mcp.tool(annotations=_ann())
def silhouette_transform_shape(
    design: str,
    shape_id: int,
    dx_mm: float = 0,
    dy_mm: float = 0,
    scale: float = 1.0,
    rotation_deg: float = 0,
    flip_x: bool = False,
    flip_y: bool = False,
) -> dict:
    """Move (dx_mm, dy_mm), scale, rotate, and optionally mirror (flip_x, flip_y) an
    existing shape by its id. Scaling, flipping and rotation are centred at the shape's bbox center."""
    _int(shape_id=shape_id)
    _num(dx_mm=dx_mm, dy_mm=dy_mm, scale=scale, rotation_deg=rotation_deg)
    if scale <= 0:
        raise SilhouetteValueError("scale must be > 0")

    with _LOCK:
        d = _load(design)
        target = next((s for s in d["shapes"] if s["id"] == shape_id), None)
        if not target:
            raise SilhouetteValueError(f"No shape with id {shape_id}")

        bx0, by0, bx1, by1 = _bbox(target)
        cx, cy = (bx0 + bx1) / 2, (by0 + by1) / 2

        if target["kind"] == "circle":
            target["cx"] = round(target["cx"] + dx_mm, 4)
            target["cy"] = round(target["cy"] + dy_mm, 4)
            target["r"] = round(target["r"] * scale, 4)
        else:
            pts = [(float(x), float(y)) for x, y in target["points"]]
            if flip_x:
                pts = [(2 * cx - x, y) for x, y in pts]
            if flip_y:
                pts = [(x, 2 * cy - y) for x, y in pts]
            if scale != 1.0:
                pts = [(cx + (x - cx) * scale, cy + (y - cy) * scale) for x, y in pts]
            if rotation_deg:
                pts = _rotate(pts, cx, cy, rotation_deg)
            pts_out = [[round(x + dx_mm, 4), round(y + dy_mm, 4)] for x, y in pts]
            target["points"] = pts_out

        _save(d)
        return {
            "design": d["name"],
            "shape_id": shape_id,
            "bbox_mm": _r4(_bbox(target)),
            "warnings": _shape_warnings(d, target),
        }


@mcp.tool(annotations=_ann())
def silhouette_offset_shape(
    design: str,
    shape_id: int,
    offset_mm: float,
    join: str = "round",
    layer: str = "",
    label: str = "",
) -> dict:
    """Create a new inward (< 0) or outward (> 0) offset contour from an existing circle or
    closed polygon (ideal for print-and-cut bleed borders, shaker frames and layered mats).
    join: 'round', 'miter', or 'bevel'."""
    _int(shape_id=shape_id)
    _num(offset_mm=offset_mm)
    if abs(offset_mm) <= 1e-6:
        raise SilhouetteValueError("offset_mm must be non-zero")
    join_norm = str(join).strip().lower()
    if join_norm not in ("round", "miter", "bevel"):
        raise SilhouetteValueError("join must be one of: round, miter, bevel")

    with _LOCK:
        d = _load(design)
        target = next((s for s in d["shapes"] if s["id"] == shape_id), None)
        if not target:
            raise SilhouetteValueError(f"No shape with id {shape_id}")

        out_layer = _norm_layer(layer) if str(layer).strip() else target.get("layer", "CUT")
        out_label = label or f"{target['label']}-offset"

        if target["kind"] == "circle":
            new_r = target["r"] + offset_mm
            if new_r <= 0.1:
                raise SilhouetteValueError("Inward offset is too large for this circle")
            s = _append_shape_in_memory(
                d, out_label, kind="circle", cx=target["cx"], cy=target["cy"], r=round(new_r, 4), layer=out_layer
            )
        else:
            if not target.get("closed", True):
                raise SilhouetteValueError("Offset is only supported for circles and closed polygons")
            new_pts = _offset_polygon(target["points"], float(offset_mm), join_norm)
            s = _append_shape_in_memory(
                d, out_label, kind="poly", closed=True, points=new_pts, layer=out_layer
            )

        _save(d)
        return {
            "design": d["name"],
            "source_id": shape_id,
            "shape_id": s["id"],
            "layer": s["layer"],
            "bbox_mm": _r4(_bbox(s)),
            "warnings": _shape_warnings(d, s),
        }


def _clone_shifted(target: dict, new_id: int, dx: float, dy: float, suffix: str) -> dict:
    new_s = copy.deepcopy(target)
    new_s["id"] = new_id
    new_s["label"] = f"{target['label']}-{suffix}"
    if target["kind"] == "circle":
        new_s["cx"] = round(target["cx"] + dx, 4)
        new_s["cy"] = round(target["cy"] + dy, 4)
    else:
        new_s["points"] = [[round(x + dx, 4), round(y + dy, 4)] for x, y in target["points"]]
    return new_s


@mcp.tool(annotations=_ann())
def silhouette_duplicate_shape(
    design: str,
    shape_id: int,
    dx_mm: float = 0,
    dy_mm: float = 0,
    count: int = 1,
) -> dict:
    """Duplicate an existing shape `count` times, offsetting each consecutive copy by (dx_mm, dy_mm)."""
    _int(shape_id=shape_id)
    _num(dx_mm=dx_mm, dy_mm=dy_mm)
    if isinstance(count, bool) or not isinstance(count, int) or count < 1 or count > 100:
        raise SilhouetteValueError("count must be an integer between 1 and 100")

    with _LOCK:
        d = _load(design)
        target = next((s for s in d["shapes"] if s["id"] == shape_id), None)
        if not target:
            raise SilhouetteValueError(f"No shape with id {shape_id}")

        created_ids = []
        for step in range(1, count + 1):
            if len(d["shapes"]) >= MAX_SHAPES:
                break
            new_id = d["next_id"]
            d["next_id"] += 1
            new_s = _clone_shifted(target, new_id, dx_mm * step, dy_mm * step, f"copy{step}")
            d["shapes"].append(new_s)
            created_ids.append(new_id)

        _save(d)
        return {"design": d["name"], "source_id": shape_id, "created_ids": created_ids, "count": len(created_ids)}


@mcp.tool(annotations=_ann())
def silhouette_grid_duplicates(
    design: str,
    shape_id: int,
    cols: int,
    rows: int,
    spacing_x_mm: float = 5.0,
    spacing_y_mm: float = 5.0,
) -> dict:
    """Arrange copies of an existing shape in a 2D cols x rows matrix (sheet nesting).
    The original shape occupies cell (0, 0) and (cols * rows - 1) copies fill the remaining cells."""
    _int(shape_id=shape_id, cols=cols, rows=rows)
    _num(spacing_x_mm=spacing_x_mm, spacing_y_mm=spacing_y_mm)
    if cols < 1 or rows < 1:
        raise SilhouetteValueError("cols and rows must be >= 1")
    if cols * rows < 2:
        raise SilhouetteValueError("cols * rows must be >= 2 to create duplicates")
    if cols * rows > 500:
        raise SilhouetteValueError("cols * rows cannot exceed 500")
    if spacing_x_mm < 0 or spacing_y_mm < 0:
        raise SilhouetteValueError("spacing_x_mm and spacing_y_mm must be >= 0")

    with _LOCK:
        d = _load(design)
        target = next((s for s in d["shapes"] if s["id"] == shape_id), None)
        if not target:
            raise SilhouetteValueError(f"No shape with id {shape_id}")

        needed = cols * rows - 1
        if len(d["shapes"]) + needed > MAX_SHAPES:
            raise SilhouetteValueError(f"Design has reached the limit of {MAX_SHAPES} shapes.")

        bx0, by0, bx1, by1 = _bbox(target)
        step_x = (bx1 - bx0) + spacing_x_mm
        step_y = (by1 - by0) + spacing_y_mm

        created_ids: list[int] = []
        created_shapes: list[dict] = []
        for r in range(rows):
            for c in range(cols):
                if r == 0 and c == 0:
                    continue
                new_id = d["next_id"]
                d["next_id"] += 1
                new_s = _clone_shifted(target, new_id, c * step_x, r * step_y, f"r{r+1}c{c+1}")
                d["shapes"].append(new_s)
                created_ids.append(new_id)
                created_shapes.append(new_s)

        _save(d)
        all_grid = [target] + created_shapes
        return {
            "design": d["name"],
            "source_id": shape_id,
            "cols": cols,
            "rows": rows,
            "created_ids": created_ids,
            "count": len(created_ids),
            "grid_bbox_mm": _r4(_union_bbox(all_grid)),
        }


# --------------------------------------------------- Print & Cut / Templates


@mcp.tool(annotations=_ann())
def silhouette_add_registration_marks(
    design: str,
    inset_mm: float = 10.0,
    mark_size_mm: float = 5.0,
    arm_len_mm: float = 15.0,
    arm_thick_mm: float = 1.0,
    layer: str = "REGMARK",
) -> dict:
    """Add standard Silhouette Print & Cut 3-corner registration marks (top-left square,
    top-right L-bracket, bottom-left L-bracket) on layer 'REGMARK'."""
    _pos(inset_mm=inset_mm, mark_size_mm=mark_size_mm, arm_len_mm=arm_len_mm, arm_thick_mm=arm_thick_mm)
    with _LOCK:
        d = _load(design)
        W, H = d["width_mm"], d["height_mm"]
        if inset_mm * 2 + arm_len_mm * 2 >= min(W, H):
            raise SilhouetteValueError("Page is too small for the requested registration marks")

        # 1. Quadrado superior esquerdo
        tl = [
            (inset_mm, inset_mm),
            (inset_mm + mark_size_mm, inset_mm),
            (inset_mm + mark_size_mm, inset_mm + mark_size_mm),
            (inset_mm, inset_mm + mark_size_mm),
        ]
        # 2. L superior direito
        rx = W - inset_mm
        ry = inset_mm
        tr = [
            (rx - arm_len_mm, ry),
            (rx, ry),
            (rx, ry + arm_len_mm),
            (rx - arm_thick_mm, ry + arm_len_mm),
            (rx - arm_thick_mm, ry + arm_thick_mm),
            (rx - arm_len_mm, ry + arm_thick_mm),
        ]
        # 3. L inferior esquerdo
        bx = inset_mm
        by = H - inset_mm
        bl = [
            (bx, by - arm_len_mm),
            (bx + arm_thick_mm, by - arm_len_mm),
            (bx + arm_thick_mm, by - arm_thick_mm),
            (bx + arm_len_mm, by - arm_thick_mm),
            (bx + arm_len_mm, by),
            (bx, by),
        ]
        s1 = _append_shape_in_memory(d, "regmark-top-left", kind="poly", closed=True, points=tl, layer=layer)
        s2 = _append_shape_in_memory(d, "regmark-top-right", kind="poly", closed=True, points=tr, layer=layer)
        s3 = _append_shape_in_memory(d, "regmark-bottom-left", kind="poly", closed=True, points=bl, layer=layer)
        _save(d)

        pad = inset_mm + max(mark_size_mm, arm_thick_mm) + 2.0
        return {
            "design": d["name"],
            "shape_ids": [s1["id"], s2["id"], s3["id"]],
            "layer": s1["layer"],
            "safe_print_area_mm": [round(pad, 3), round(pad, 3), round(W - pad, 3), round(H - pad, 3)],
        }


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
    d: dict,
    *,
    luxo: bool,
    x_mm: float,
    y_mm: float,
    width_mm: float,
    depth_mm: float,
    body_height_mm: float,
    dashed_score: bool,
) -> list[dict]:
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
    # Abas do fundo (direita -> esquerda)
    outline += [(x5 - 1.0, y_body_base), (x5 - 5.0, y_bot_side), (x4 + 5.0, y_bot_side), (x4 + 1.0, y_body_base)]
    outline += [(x4 - 1.0, y_body_base), (x4 - 4.0, y_bot_main), (x3 + 4.0, y_bot_main), (x3 + 1.0, y_body_base)]
    outline += [(x3 - 1.0, y_body_base), (x3 - 5.0, y_bot_side), (x2 + 5.0, y_bot_side), (x2 + 1.0, y_body_base)]
    outline += [(x2 - 1.0, y_body_base), (x2 - 4.0, y_bot_main), (x1 + 4.0, y_bot_main), (x1 + 1.0, y_body_base)]
    # Aba de colagem esquerda
    chamfer = min(10.0, g)
    outline += [(x1, y_body_base), (x_tab, y_body_base - chamfer), (x_tab, y_gusset + chamfer), (x1, y_gusset)]

    added: list[dict] = []
    added.append(_append_shape_in_memory(d, "milk-contorno", kind="poly", closed=True, points=outline, layer="CUT"))

    # Rasgos / furos para fita de cetim
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

    # Vincos (SCORE)
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
        # Fole direito (P2) e esquerdo (P4)
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
    d: dict,
    *,
    x_mm: float,
    y_mm: float,
    width_mm: float,
    depth_mm: float,
    body_height_mm: float,
    dashed_score: bool,
) -> list[dict]:
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
        # Face 1 (Frente): borda livre para receber a lingueta da tampa
        (x1, y_body_top), (x2, y_body_top),
        # Aba poeira face 2 (Lateral)
        (x2 + 1.0, y_body_top), (x2 + 4.0, y_body_top - dust_h), (x3 - 4.0, y_body_top - dust_h), (x3 - 1.0, y_body_top),
        (x3, y_body_top),
        # Tampa superior articulada na face 3 (Costas)
        (x3, y_lid_fold), (x3 + 4.0, y_top), (x4 - 4.0, y_top), (x4, y_lid_fold), (x4, y_body_top),
        # Aba poeira face 4 (Lateral)
        (x4 + 1.0, y_body_top), (x4 + 4.0, y_body_top - dust_h), (x5 - 4.0, y_body_top - dust_h), (x5 - 1.0, y_body_top),
        (x5, y_body_top), (x5, y_body_bot),
        # Abas inferiores (direita -> esquerda)
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
    d: dict,
    *,
    x_mm: float,
    y_mm: float,
    width_mm: float,
    body_height_mm: float,
    dashed_score: bool,
) -> list[dict]:
    g = max(8.0, min(14.0, width_mm * 0.2))
    curve_h = max(10.0, min(18.0, width_mm * 0.22))
    x_tab = x_mm
    x1 = x_tab + g
    x2 = x1 + width_mm
    x3 = x2 + width_mm

    y_top = y_mm
    y_body_top = y_top + curve_h
    y_body_bot = y_body_top + body_height_mm
    y_bot = y_body_bot + curve_h

    def bow_arc(xa: float, xb: float, y_base: float, dy: float, n: int = 16) -> list[tuple[float, float]]:
        return [
            (xa + (xb - xa) * i / n, y_base + dy * math.sin(math.pi * i / n))
            for i in range(n + 1)
        ]

    # Contorno externo: abas convexas no topo e na base
    outline: list[tuple[float, float]] = []
    outline += bow_arc(x1, x2, y_body_top, -curve_h)
    outline += bow_arc(x2, x3, y_body_top, -curve_h)
    outline.append((x3, y_body_bot))
    outline += list(reversed(bow_arc(x2, x3, y_body_bot, +curve_h)))
    outline += list(reversed(bow_arc(x1, x2, y_body_bot, +curve_h)))
    outline += [(x_tab, y_body_bot - 8.0), (x_tab, y_body_top + 8.0), (x1, y_body_top)]

    added = [_append_shape_in_memory(d, "pillow-contorno", kind="poly", closed=True, points=outline, layer="CUT")]

    # Vincos verticais retos
    for x_s, lbl in ((x1, "vinco-aba-cola"), (x2, "vinco-centro")):
        added.extend(_add_line_to_doc(
            d, x_s, y_body_top, x_s, y_body_bot,
            dashed=dashed_score, dash_len_mm=3.5, gap_len_mm=2.0, layer="SCORE", label=lbl
        ))

    # 4 arcos concavos de vinco nas pontas (para fechar o travesseiro)
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
    d: dict,
    *,
    x_mm: float,
    y_mm: float,
    width_mm: float,
    body_height_mm: float,
    dashed_score: bool,
) -> list[dict]:
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


@mcp.tool(annotations=_ann())
def silhouette_add_box_template(
    design: str,
    template: str = "milk-box-luxo",
    x_mm: float = 20.0,
    y_mm: float = 15.0,
    width_mm: float = 60.0,
    depth_mm: float = 60.0,
    body_height_mm: float = 90.0,
    dashed_score: bool = True,
) -> dict:
    """Generate a ready-to-cut parametric packaging / papercraft template with CUT and SCORE layers.
    Supported templates: 'milk-box-luxo', 'milk-box', 'cube-box', 'pillow-box', 'gift-tag'."""
    _num(x_mm=x_mm, y_mm=y_mm)
    _pos(width_mm=width_mm, depth_mm=depth_mm, body_height_mm=body_height_mm)
    tpl = str(template).strip().lower()
    supported = ("milk-box-luxo", "milk-box", "cube-box", "pillow-box", "gift-tag")
    if tpl not in supported:
        raise SilhouetteValueError(f"Unknown template '{template}'. Options: {', '.join(supported)}")

    with _LOCK:
        d = _load(design)
        if tpl in ("milk-box-luxo", "milk-box"):
            added = _build_milk_box(
                d, luxo=(tpl == "milk-box-luxo"), x_mm=x_mm, y_mm=y_mm,
                width_mm=width_mm, depth_mm=depth_mm, body_height_mm=body_height_mm,
                dashed_score=bool(dashed_score),
            )
        elif tpl == "cube-box":
            added = _build_cube_box(
                d, x_mm=x_mm, y_mm=y_mm, width_mm=width_mm, depth_mm=depth_mm,
                body_height_mm=body_height_mm, dashed_score=bool(dashed_score),
            )
        elif tpl == "pillow-box":
            added = _build_pillow_box(
                d, x_mm=x_mm, y_mm=y_mm, width_mm=width_mm,
                body_height_mm=body_height_mm, dashed_score=bool(dashed_score),
            )
        else:
            added = _build_gift_tag(
                d, x_mm=x_mm, y_mm=y_mm, width_mm=width_mm,
                body_height_mm=body_height_mm, dashed_score=bool(dashed_score),
            )

        _save(d)
        warnings = [
            f"shape {s['id']} ({s['label']}): {w}"
            for s in added
            for w in _shape_warnings(d, s)
        ]
        return {
            "design": d["name"],
            "template": tpl,
            "shapes_added": len(added),
            "shape_ids": [s["id"] for s in added],
            "bbox_mm": _r4(_union_bbox(added)),
            "warnings": warnings,
        }


# ----------------------------------------------------------- SVG import/export


def _svg_subpaths(svg_file: Path) -> tuple[list[tuple[list[tuple[float, float]], bool]], int]:
    """Le um SVG e devolve ([(pontos_em_px, fechado)], elementos_ignorados)."""
    try:
        from svgelements import (SVG, Close, Image, Line, Move, Path as SvgPath, Shape, Text)
    except ImportError as e:  # pragma: no cover
        raise SilhouetteValueError("The 'svgelements' package is not installed (pip install svgelements)") from e

    svg = SVG.parse(str(svg_file), reify=True)  # unidades de usuario = px a 96 ppi
    subpaths: list[tuple[list[tuple[float, float]], bool]] = []
    skipped = 0
    for el in svg.elements():
        if isinstance(el, (Text, Image)):
            skipped += 1
            continue
        if not isinstance(el, Shape):
            continue
        cur: list[tuple[float, float]] = []

        def flush(closed: bool = False) -> None:
            nonlocal cur
            if len(cur) >= 2:
                if not closed and math.hypot(cur[0][0] - cur[-1][0], cur[0][1] - cur[-1][1]) < 1e-6:
                    closed = True
                if closed and math.hypot(cur[0][0] - cur[-1][0], cur[0][1] - cur[-1][1]) < 1e-6:
                    cur = cur[:-1]
                if len(cur) >= (3 if closed else 2):
                    subpaths.append((cur, closed))
            cur = []

        for seg in SvgPath(el):
            if isinstance(seg, Move):
                flush()
                cur = [(seg.end.x, seg.end.y)]
            elif isinstance(seg, Close):
                flush(closed=True)
            else:
                if not cur:
                    cur = [(seg.start.x, seg.start.y)]
                if isinstance(seg, Line):
                    cur.append((seg.end.x, seg.end.y))
                else:
                    try:
                        n = max(12, min(256, math.ceil(seg.length() * 25.4 / 96 / 0.4)))
                    except Exception:
                        n = 32
                    for i in range(1, n + 1):
                        p = seg.point(i / n)
                        cur.append((p.x, p.y))
        flush()
    return subpaths, skipped


@mcp.tool(annotations=_ann())
def silhouette_import_svg(
    design: str,
    svg_path: str,
    target_width_mm: float = 0,
    target_height_mm: float = 0,
    x_mm: float = 0,
    y_mm: float = 0,
    rotation_deg: float = 0,
    layer: str = "CUT",
) -> dict:
    """Read an SVG file from disk, convert outlines (curves flattened to mm segments)
    and add them to the design for DXF export. This bridges SVG artwork into Silhouette Studio
    Standard Edition (which cannot open SVG natively).
    target_width_mm / target_height_mm > 0 scale artwork (uniformly if only one is given);
    artwork's top-left corner is placed at (x_mm, y_mm).
    Text and embedded images are skipped (convert text to outlines or use silhouette_add_text)."""
    _num(target_width_mm=target_width_mm, target_height_mm=target_height_mm,
         x_mm=x_mm, y_mm=y_mm, rotation_deg=rotation_deg)
    if target_width_mm < 0 or target_height_mm < 0:
        raise SilhouetteValueError("target_width_mm and target_height_mm must be >= 0")
    p = Path(svg_path).expanduser()
    if p.suffix.lower() != ".svg" or not p.is_file():
        raise SilhouetteValueError("svg_path must be an existing .svg file")
    if p.stat().st_size > 10 * 1024 * 1024:
        raise SilhouetteValueError("SVG is larger than 10 MB")

    subs, skipped = _svg_subpaths(p)
    if not subs:
        raise SilhouetteValueError("No outlines found in the SVG (text/images are not supported)")

    k = 25.4 / 96
    allpts = [(x * k, y * k) for pts, _ in subs for x, y in pts]
    minx, miny = min(a[0] for a in allpts), min(a[1] for a in allpts)
    width = max(a[0] for a in allpts) - minx
    height = max(a[1] for a in allpts) - miny

    if target_width_mm > 0 and target_height_mm > 0 and width > 0 and height > 0:
        sx = target_width_mm / width
        sy = target_height_mm / height
    elif target_width_mm > 0 and width > 0:
        sx = sy = target_width_mm / width
    elif target_height_mm > 0 and height > 0:
        sx = sy = target_height_mm / height
    else:
        sx = sy = 1.0

    norm_layer = _norm_layer(layer)
    cx = x_mm + (width * sx) / 2.0
    cy = y_mm + (height * sy) / 2.0

    with _LOCK:
        d = _load(design)
        if len(subs) + len(d["shapes"]) > MAX_SHAPES:
            raise SilhouetteValueError(f"SVG has too many paths ({len(subs)}); limit is {MAX_SHAPES} shapes per design")

        for i, (pts, closed) in enumerate(subs, 1):
            mm = [(x_mm + (x * k - minx) * sx, y_mm + (y * k - miny) * sy) for x, y in pts]
            if rotation_deg:
                mm = _rotate(mm, cx, cy, rotation_deg)
            d["shapes"].append({
                "id": d["next_id"],
                "label": f"svg:{p.stem}#{i}",
                "layer": norm_layer,
                "kind": "poly",
                "closed": closed,
                "points": [[round(a, 4), round(b, 4)] for a, b in mm],
            })
            d["next_id"] += 1
        _save(d)
        added = d["shapes"][-len(subs):]
        warnings = []
        if skipped:
            warnings.append(f"{skipped} text/image element(s) were skipped")
        out_of_page = [s["id"] for s in added if any(_shape_warnings(d, s))]
        if out_of_page:
            warnings.append(f"{len(out_of_page)} imported path(s) trigger placement/size warnings; "
                            "run silhouette_describe_design")
        return {"design": d["name"], "paths_added": len(subs), "scale_applied": round(sx, 4),
                "bbox_mm": _r4(_union_bbox(added)), "warnings": warnings}


@mcp.tool(annotations=_ann(read_only=True, idempotent=True))
def silhouette_describe_design(design: str) -> dict:
    """Summarise a design: page size, every shape with its bounding box, overall bounds
    and any warnings (outside the page, inside the safety margin, tiny details)."""
    d = _load(design)
    shapes, warns = [], []
    for s in d["shapes"]:
        shapes.append({
            "id": s["id"],
            "label": s["label"],
            "layer": s.get("layer", "CUT"),
            "kind": s["kind"],
            "bbox_mm": _r4(_bbox(s)),
            **({"closed": s["closed"]} if s["kind"] == "poly" else {}),
        })
        for w in _shape_warnings(d, s):
            warns.append(f"shape {s['id']} ({s['label']}): {w}")
    return {"design": d["name"], "width_mm": d["width_mm"], "height_mm": d["height_mm"],
            "cut_margin_mm": d["cut_margin_mm"], "shape_count": len(shapes),
            "overall_bbox_mm": _r4(_union_bbox(d["shapes"])), "shapes": shapes, "warnings": warns}


@mcp.tool(annotations=_ann(destructive=True))
def silhouette_remove_shape(design: str, shape_id: int) -> dict:
    """Remove one shape (by the id shown in silhouette_describe_design)."""
    _int(shape_id=shape_id)
    with _LOCK:
        d = _load(design)
        before = len(d["shapes"])
        d["shapes"] = [s for s in d["shapes"] if s["id"] != shape_id]
        if len(d["shapes"]) == before:
            raise SilhouetteValueError(f"No shape with id {shape_id}")
        _save(d)
        return {"design": d["name"], "removed": shape_id, "shape_count": len(d["shapes"])}


def _write_dxf(d: dict, path: Path) -> None:
    ver = str(DXF_VERSION).upper()
    if ver not in ("R2000", "R12"):
        raise SilhouetteValueError(f"Unsupported DXF version '{DXF_VERSION}'. Only 'R2000' and 'R12' are supported.")
    doc = ezdxf.new(ver)
    try:
        doc.units = units.MM
        doc.header["$INSUNITS"] = 4    # 4 = Millimeters
        doc.header["$MEASUREMENT"] = 1  # 1 = Metric
        doc.header["$EXTMIN"] = (0.0, 0.0, 0.0)
        doc.header["$EXTMAX"] = (float(d["width_mm"]), float(d["height_mm"]), 0.0)
    except Exception:
        pass

    # Garante que as camadas padrao existam com cores ACI distintas
    for layer_name, color in LAYER_COLORS.items():
        if layer_name not in doc.layers:
            doc.layers.add(name=layer_name, color=color)

    msp = doc.modelspace()
    H = d["height_mm"]  # DXF e Y-para-cima: inverte para manter o layout visual da pagina

    for s in d["shapes"]:
        layer = s.get("layer", "CUT").upper()
        color_idx = LAYER_COLORS.get(layer, 7)
        if layer not in doc.layers:
            doc.layers.add(name=layer, color=color_idx)
        dxfattribs = {"layer": layer, "color": color_idx}

        if s["kind"] == "circle":
            msp.add_circle((s["cx"], H - s["cy"]), s["r"], dxfattribs=dxfattribs)
        else:
            raw_pts = _dedupe_closed(s["points"]) if s["closed"] else s["points"]
            pts = [(x, H - y) for x, y in raw_pts]
            if ver == "R12":
                msp.add_polyline2d(pts, close=s["closed"], dxfattribs=dxfattribs)
            else:
                msp.add_lwpolyline(pts, close=s["closed"], dxfattribs=dxfattribs)

    _atomic_write_file(path, ".dxf.tmp", lambda tmp: doc.saveas(str(tmp)))


def _write_svg(d: dict, path: Path) -> None:
    W, H = d["width_mm"], d["height_mm"]
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{_fmt(W)}mm" height="{_fmt(H)}mm" '
        f'viewBox="0 0 {_fmt(W)} {_fmt(H)}" fill="none" stroke-width="0.3">'
    ]
    # Agrupa por camada para organizacao visual e selecao facil
    shapes_by_layer: dict[str, list[dict]] = {}
    for s in d["shapes"]:
        layer = s.get("layer", "CUT").upper()
        shapes_by_layer.setdefault(layer, []).append(s)

    for layer, shapes in shapes_by_layer.items():
        color = SVG_LAYER_COLORS.get(layer, "#000000")
        dash = ' stroke-dasharray="3,2"' if layer in _DASHED_PREVIEW_LAYERS else ""
        safe_layer = re.sub(r"[^A-Za-z0-9_-]+", "-", layer).strip("-") or "LAYER"
        out.append(f'  <g id="{safe_layer}" stroke="{color}"{dash}>')
        for s in shapes:
            if s["kind"] == "circle":
                out.append(f'    <circle cx="{_fmt(s["cx"])}" cy="{_fmt(s["cy"])}" r="{_fmt(s["r"])}"/>')
            else:
                raw_pts = _dedupe_closed(s["points"]) if s["closed"] else s["points"]
                pts = " ".join(f"{_fmt(x)},{_fmt(y)}" for x, y in raw_pts)
                tag = "polygon" if s["closed"] else "polyline"
                out.append(f'    <{tag} points="{pts}"/>')
        out.append("  </g>")
    out.append("</svg>")
    content = "\n".join(out)
    _atomic_write_file(path, ".svg.tmp", lambda tmp: tmp.write_text(content, encoding="utf-8"))


def _draw_dashed_segment(
    draw: Any, p0: tuple[float, float], p1: tuple[float, float], fill: str, width: int, dash_px: float = 10.0, gap_px: float = 6.0
) -> None:
    dist = math.hypot(p1[0] - p0[0], p1[1] - p0[1])
    if dist <= 1e-3:
        return
    dx, dy = (p1[0] - p0[0]) / dist, (p1[1] - p0[1]) / dist
    t = 0.0
    step = dash_px + gap_px
    while t < dist:
        t1 = min(t + dash_px, dist)
        draw.line([(p0[0] + dx * t, p0[1] + dy * t), (p0[0] + dx * t1, p0[1] + dy * t1)], fill=fill, width=width)
        t += step


def _write_png(d: dict, path: Path, dpi: int = 150) -> tuple[int, int]:
    from PIL import Image as PilImage, ImageDraw

    dpi_clamped = max(36, min(600, int(dpi)))
    W, H = float(d["width_mm"]), float(d["height_mm"])
    scale = dpi_clamped / 25.4
    max_dim = max(W * scale, H * scale)
    if max_dim > 2400:
        scale *= 2400.0 / max_dim
    elif max_dim < 200:
        scale *= 200.0 / max_dim

    w_px = max(1, int(round(W * scale)))
    h_px = max(1, int(round(H * scale)))
    img = PilImage.new("RGB", (w_px, h_px), "#ffffff")
    draw = ImageDraw.Draw(img)

    # Grade de fundo 10 mm
    gx = 10.0
    while gx < W:
        px = gx * scale
        draw.line([(px, 0), (px, h_px)], fill="#f0f2f5", width=1)
        gx += 10.0
    gy = 10.0
    while gy < H:
        py = gy * scale
        draw.line([(0, py), (w_px, py)], fill="#f0f2f5", width=1)
        gy += 10.0

    # Margem de seguranca
    m = float(d.get("cut_margin_mm", 5.0))
    if m > 0:
        mx0, my0, mx1, my1 = m * scale, m * scale, (W - m) * scale, (H - m) * scale
        for a, b in (((mx0, my0), (mx1, my0)), ((mx1, my0), (mx1, my1)), ((mx1, my1), (mx0, my1)), ((mx0, my1), (mx0, my0))):
            _draw_dashed_segment(draw, a, b, "#d9b38c", 1, dash_px=8.0, gap_px=6.0)

    stroke_w = max(1, int(round(scale * 0.35)))
    for s in d["shapes"]:
        layer = s.get("layer", "CUT").upper()
        color = SVG_LAYER_COLORS.get(layer, "#000000")
        dashed = layer in _DASHED_PREVIEW_LAYERS
        if s["kind"] == "circle":
            cx, cy, r = s["cx"] * scale, s["cy"] * scale, s["r"] * scale
            draw.ellipse([cx - r, cy - r, cx + r, cy + r], outline=color, width=stroke_w)
        else:
            raw_pts = _dedupe_closed(s["points"]) if s["closed"] else s["points"]
            pts_px = [(x * scale, y * scale) for x, y in raw_pts]
            if len(pts_px) < 2:
                continue
            segs = list(zip(pts_px, pts_px[1:]))
            if s["closed"] and len(pts_px) >= 3:
                segs.append((pts_px[-1], pts_px[0]))
            for p0, p1 in segs:
                if dashed:
                    _draw_dashed_segment(draw, p0, p1, color, stroke_w)
                else:
                    draw.line([p0, p1], fill=color, width=stroke_w)

    _atomic_write_file(path, ".png.tmp", lambda tmp: img.save(tmp, format="PNG"))
    return w_px, h_px


def _export(d: dict, formats: str, filename: str = "") -> dict:
    if not d["shapes"]:
        raise SilhouetteValueError("The design has no shapes to export.")
    wanted = [f.strip().lower() for f in formats.split(",") if f.strip()]
    if not wanted or any(f not in ("dxf", "svg", "png") for f in wanted):
        raise SilhouetteValueError("formats must be a comma-separated list of: dxf, svg, png")
    base = _slug(filename) if filename else d["name"]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    files: dict[str, str] = {}
    for f in dict.fromkeys(wanted):
        p = OUTPUT_DIR / f"{base}.{f}"
        if f == "dxf":
            _write_dxf(d, p)
        elif f == "svg":
            _write_svg(d, p)
        else:
            _write_png(d, p)
        files[f] = str(p)
    warns = [f"shape {s['id']} ({s['label']}): {w}" for s in d["shapes"] for w in _shape_warnings(d, s)]
    notes = [
        "Open the DXF in Silhouette Studio with File > Open (works in the free Standard/Basic edition).",
        "Layers (CUT=red, SCORE=blue, PERF=green, ENGRAVE=cyan, REGMARK=black) allow setting separate blade actions in Studio's 'Send by Layer/Line' tab.",
        "Check calibration after first import: in Studio Preferences > Import Options > DXF set to 'As-is'.",
    ]
    if "svg" in files:
        notes.append("The SVG is a preview/exchange file: Studio only opens SVG in Designer Edition or higher.")
    return {"files": files, "dxf_version": DXF_VERSION, "shape_count": len(d["shapes"]),
            "bbox_mm": _r4(_union_bbox(d["shapes"])), "warnings": warns, "notes": notes}


@mcp.tool(annotations=_ann(idempotent=True))
def silhouette_export(design: str, formats: str = "dxf,svg", filename: str = "") -> dict:
    """Export the design to cut/preview files in the output folder. formats is a comma-separated
    list of 'dxf', 'svg', and/or 'png'. DXF is required for the free Standard Edition.
    filename (optional) overrides the base file name. Returns file paths, bounds and warnings."""
    with _LOCK:
        return _export(_load(design), formats, filename)


@mcp.tool(annotations=_ann(idempotent=True))
def silhouette_render_preview(design: str, dpi: int = 150, filename: str = "") -> dict:
    """Render a colour-coded PNG preview of the design (with 10 mm grid and safety margin)
    for visual inspection before cutting. Returns the PNG path, pixel dimensions and warnings."""
    _int(dpi=dpi)
    if dpi < 36 or dpi > 600:
        raise SilhouetteValueError("dpi must be between 36 and 600")
    with _LOCK:
        d = _load(design)
        if not d["shapes"]:
            raise SilhouetteValueError("The design has no shapes to export.")
        base = _slug(filename) if filename else d["name"]
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        out_path = OUTPUT_DIR / f"{base}.png"
        w_px, h_px = _write_png(d, out_path, dpi=dpi)
        warns = [f"shape {s['id']} ({s['label']}): {w}" for s in d["shapes"] for w in _shape_warnings(d, s)]
        return {
            "design": d["name"],
            "png_path": str(out_path),
            "width_px": w_px,
            "height_px": h_px,
            "bbox_mm": _r4(_union_bbox(d["shapes"])),
            "warnings": warns,
        }


@mcp.tool(annotations=_ann(idempotent=True))
def silhouette_make_calibration_file() -> dict:
    """Create and export a calibration DXF: a 100 x 100 mm square with a 50 mm circle,
    a 40 x 20 mm rounded rectangle, and a 100 mm perforated score line. Open it in Studio and measure it:
    if the square is not 100 mm (3.937 in), set Studio Preferences > Import Options > DXF to 'As-is'."""
    shapes: list[dict] = [
        {"id": 1, "label": "square-100mm", "kind": "poly", "closed": True, "layer": "CUT",
         "points": [[20, 20], [120, 20], [120, 120], [20, 120]]},
        {"id": 2, "label": "circle-50mm", "kind": "circle", "cx": 70, "cy": 70, "r": 25, "layer": "CUT"},
        {"id": 3, "label": "pill-40x20", "kind": "poly", "closed": True, "layer": "CUT",
         "points": [[round(a, 4), round(b, 4)] for a, b in _rounded_rect(20, 140, 40, 20, 5)]},
    ]
    # Linha de vinco pontilhada para dobra (SCORE): tracos de 4mm com espaco de 2mm
    t = 20.0
    idx = 4
    while t < 120.0:
        t_end = min(t + 4.0, 120.0)
        shapes.append({
            "id": idx, "label": f"score-dash#{idx-3}", "kind": "poly", "closed": False,
            "layer": "SCORE", "points": [[t, 70], [t_end, 70]]
        })
        idx += 1
        t += 6.0

    d = {
        "name": "calibration-100mm",
        "width_mm": 304.8,
        "height_mm": 304.8,
        "cut_margin_mm": 5.0,
        "next_id": idx,
        "shapes": shapes,
    }
    with _LOCK:
        _save(d)
        r = _export(d, "dxf")
    r["expected"] = "Square = 100 x 100 mm; circle diameter = 50 mm; pill = 40 x 20 mm; center score line = 100 mm dashed."
    return r


def _find_studio_exe() -> str:
    if STUDIO_EXE and Path(STUDIO_EXE).is_file():
        return STUDIO_EXE
    if sys.platform.startswith("win"):
        # Checagem direta rapida nas pastas comuns do Windows
        direct_checks = [
            Path(r"C:\Program Files\Silhouette America\Silhouette Studio\Silhouette Studio.exe"),
            Path(r"C:\Program Files (x86)\Silhouette America\Silhouette Studio\Silhouette Studio.exe"),
        ]
        for p in direct_checks:
            if p.is_file():
                return str(p)
        for root in filter(None, (os.environ.get("ProgramFiles"), os.environ.get("ProgramFiles(x86)"))):
            base = Path(root) / "Silhouette America"
            if base.is_dir():
                for p in base.rglob("*.exe"):
                    n = p.name.lower()
                    if n.startswith("silhouette studio") and "unins" not in n:
                        return str(p)
    return ""


@mcp.tool(annotations=_ann(open_world=True))
def silhouette_open_in_studio(path: str, reveal_in_explorer: bool = False) -> dict:
    """Open a cut file previously exported (.dxf or .svg) directly in Silhouette Studio.
    Accepts full paths, paths relative to the output folder, or just design/file names.
    Set reveal_in_explorer=true to also select the file in Windows Explorer."""
    p = Path(path).expanduser()
    if not p.is_file():
        # Tenta localizar dentro de OUTPUT_DIR (literal e normalizado via _slug)
        candidates = [
            OUTPUT_DIR / path,
            OUTPUT_DIR / f"{path}.dxf",
            OUTPUT_DIR / f"{path}.svg",
        ]
        try:
            raw_p = Path(path)
            ext = raw_p.suffix.lower()
            if ext in (".dxf", ".svg"):
                slug = _slug(raw_p.stem)
                candidates.append(OUTPUT_DIR / f"{slug}{ext}")
            else:
                slug = _slug(path)
                candidates.append(OUTPUT_DIR / f"{slug}.dxf")
                candidates.append(OUTPUT_DIR / f"{slug}.svg")
        except ValueError:
            pass
        for candidate in candidates:
            cand_exp = candidate.expanduser()
            if cand_exp.is_file():
                p = cand_exp
                break
    p = p.resolve()

    if p.suffix.lower() not in (".dxf", ".svg") or not p.is_file():
        raise SilhouetteValueError(f"File '{path}' not found or is not a .dxf/.svg file.")

    if sys.platform.startswith("win"):
        exe = _find_studio_exe()
        if exe:
            try:
                subprocess.Popen([exe, str(p)])
            except OSError as e:
                raise SilhouetteRuntimeError(f"Failed to open '{p}' in Silhouette Studio: {e}") from e
            if reveal_in_explorer:
                try:
                    subprocess.Popen(["explorer.exe", f"/select,{p}"])
                except OSError:
                    pass
            return {
                "opened": str(p),
                "method": f"launched {exe}",
                "note": "Se o Silhouette Studio ja estiver aberto, pressione Ctrl+O e selecione o arquivo.",
            }
        try:
            os.startfile(str(p))  # type: ignore[attr-defined]
        except OSError as e:
            raise SilhouetteRuntimeError(f"Failed to open '{p}' in Silhouette Studio: {e}") from e
        return {"opened": str(p), "method": "default file association (Studio executable not found; "
                                             "set SILHOUETTE_STUDIO_EXE if another app opened it)"}
    if sys.platform == "darwin":
        try:
            subprocess.Popen(["open", "-a", "Silhouette Studio", str(p)])
        except OSError as e:
            raise SilhouetteRuntimeError(f"Failed to open '{p}' in Silhouette Studio: {e}") from e
        return {"opened": str(p), "method": "open -a 'Silhouette Studio'"}
    raise SilhouetteValueError("Opening Silhouette Studio is only supported on Windows and macOS.")


if __name__ == "__main__":  # pragma: no cover
    mcp.run()  # transporte stdio
