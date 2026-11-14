"""DXF R2000/R12 writer with Y-up coordinate mapping and Silhouette layer ACI palette."""

from __future__ import annotations

from pathlib import Path

import ezdxf
from ezdxf import units

from ..config.settings import LAYER_COLORS, get_runtime_attr
from ..core.exceptions import SilhouetteValueError
from ..core.geometry_engine import _dedupe_closed
from ..persistence.storage import _atomic_write_file


def _write_dxf(d: dict, path: Path) -> None:
    dxf_version = str(get_runtime_attr("DXF_VERSION"))
    ver = dxf_version.upper()
    if ver not in ("R2000", "R12"):
        raise SilhouetteValueError(f"Unsupported DXF version '{dxf_version}'. Only 'R2000' and 'R12' are supported.")
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

