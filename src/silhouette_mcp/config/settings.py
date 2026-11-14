"""Runtime configuration, operational bounds, presets, font assets, and stderr logging."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Any

OUTPUT_DIR = Path(
    os.environ.get("SILHOUETTE_OUTPUT_DIR") or Path.home() / "Documents" / "SilhouetteMCP"
).expanduser()
DXF_VERSION = (os.environ.get("SILHOUETTE_DXF_VERSION") or "R2000").upper()
STUDIO_EXE = os.environ.get("SILHOUETTE_STUDIO_EXE") or ""

CHORD_TOL_MM = 0.05   # tolerancia ao transformar curvas em segmentos
MIN_FEATURE_MM = 2.0  # abaixo disso, avisa que o corte fino pode rasgar papel/vinil
MAX_SHAPES = 5000
MIN_PAGE_MM = 10.0
MAX_PAGE_MM = 5000.0
MAX_COORD_MM = 100000.0
MAX_ARC_SEGMENTS = 512
MAX_POINTS_PER_SHAPE = 20000
MAX_TEXT_LENGTH = 500
MAX_SVG_BYTES = 10 * 1024 * 1024
MAX_SVG_ELEMENTS = 10000
MAX_SVG_DEPTH = 64
MAX_SVG_TOTAL_POINTS = 100000
LOCK_TIMEOUT_S = 10.0


class _DynamicStderrHandler(logging.StreamHandler):
    """Stream handler that resolves sys.stderr dynamically on each log emission."""

    def __init__(self) -> None:
        super().__init__(sys.stderr)

    def emit(self, record: logging.LogRecord) -> None:
        self.stream = sys.stderr
        super().emit(record)


logger = logging.getLogger("silhouette_mcp")
if not logger.handlers:
    _stderr_handler = _DynamicStderrHandler()
    _stderr_handler.setFormatter(
        logging.Formatter("%(asctime)s [%(levelname)s] silhouette_mcp: %(message)s")
    )
    logger.addHandler(_stderr_handler)
logger.propagate = False
_log_level_name = (os.environ.get("SILHOUETTE_LOG_LEVEL") or "WARNING").upper()
logger.setLevel(getattr(logging, _log_level_name, logging.WARNING))

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
3. silhouette_offset_shape / silhouette_grid_duplicates / silhouette_nest_shapes / silhouette_add_registration_marks
4. silhouette_describe_design / silhouette_render_preview -> verify bounds, warnings and visual layout
5. silhouette_export(design, formats="dxf,svg,png") -> generate DXF for cutting
6. silhouette_open_in_studio -> open directly in Silhouette Studio
Silhouette Studio has no public live API: this server generates standard files and opens them.
"""

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

_ALLOWED_FONT_EXTS = frozenset({".ttf", ".otf", ".ttc"})

_CONFIG_DEFAULTS: dict[str, Any] = {
    "OUTPUT_DIR": OUTPUT_DIR,
    "DXF_VERSION": DXF_VERSION,
    "STUDIO_EXE": STUDIO_EXE,
    "MAX_SHAPES": MAX_SHAPES,
    "LOCK_TIMEOUT_S": LOCK_TIMEOUT_S,
    "MAX_SVG_BYTES": MAX_SVG_BYTES,
    "MAX_SVG_ELEMENTS": MAX_SVG_ELEMENTS,
    "MAX_SVG_DEPTH": MAX_SVG_DEPTH,
    "MAX_SVG_TOTAL_POINTS": MAX_SVG_TOTAL_POINTS,
    "_FONT_DIRS": _FONT_DIRS,
}


def get_runtime_attr(name: str, local_default: Any = None) -> Any:
    """Resolve a live runtime attribute or setting, honoring monkeypatches on `silhouette_mcp.server` or `settings`."""
    settings_mod = sys.modules[__name__]
    base_val = globals().get(name, local_default)
    orig_val = _CONFIG_DEFAULTS.get(name, local_default)

    mod = sys.modules.get("silhouette_mcp.server")
    if mod is not None and hasattr(mod, name):
        candidate = getattr(mod, name)
        if candidate is not orig_val and candidate != orig_val:
            return candidate
        if name in _CONFIG_DEFAULTS and getattr(settings_mod, name) is not orig_val:
            return getattr(settings_mod, name)
    if name in _CONFIG_DEFAULTS:
        return getattr(settings_mod, name)
    return base_val

