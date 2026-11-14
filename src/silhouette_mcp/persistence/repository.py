"""Document repository operations: load with backup recovery, atomic save, and add-shape helper."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

from ..config.settings import get_runtime_attr, logger
from ..core.exceptions import SilhouetteValueError
from ..core.models import _append_shape_in_memory, _bbox, _shape_warnings
from ..core.validators import _r4, _validate_design_dict
from .storage import _LOCK, _atomic_replace, _atomic_write_file, _backup_path, _design_path


def _load(name: str) -> dict:
    with _LOCK:
        p = _design_path(name)
        bak = _backup_path(name)
        if not p.exists() and not bak.exists():
            raise SilhouetteValueError(f"Design '{name}' does not exist. Call silhouette_new_design first.")

        primary_err: Exception | None = None
        if p.exists():
            try:
                return _validate_design_dict(json.loads(p.read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError, SilhouetteValueError, KeyError, TypeError, UnicodeDecodeError) as exc:
                primary_err = exc

        if bak.is_file():
            try:
                bak_text = bak.read_text(encoding="utf-8")
                recovered = _validate_design_dict(json.loads(bak_text))
                logger.warning(
                    "Recovered corrupted or missing design '%s' from backup (%s).",
                    name,
                    primary_err,
                )
                _atomic_write_file(
                    p,
                    ".rec.tmp",
                    lambda tmp: tmp.write_text(bak_text, encoding="utf-8"),
                )
                return recovered
            except Exception as bak_exc:
                raise SilhouetteValueError(
                    f"Design '{name}' is corrupted ({primary_err}) and backup recovery failed ({bak_exc})."
                ) from bak_exc

        raise SilhouetteValueError(
            f"Design '{name}' is corrupted ({primary_err}) and no backup is available."
        )


def _save(d: dict) -> None:
    with _LOCK:
        out_dir: Path = get_runtime_attr("OUTPUT_DIR")
        out_dir.mkdir(parents=True, exist_ok=True)
        d["revision"] = int(d.get("revision", 0)) + 1
        target_path = _design_path(d["name"])
        bak_path = _backup_path(d["name"])
        payload = json.dumps(d, indent=1)
        tmp_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                dir=out_dir,
                delete=False,
                encoding="utf-8",
                suffix=".tmp",
            ) as tf:
                tmp_path = Path(tf.name)
                tf.write(payload)
                tf.flush()
                os.fsync(tf.fileno())
            _atomic_replace(tmp_path, target_path)
            try:
                _atomic_write_file(
                    bak_path,
                    ".bak.tmp",
                    lambda tmp: tmp.write_text(payload, encoding="utf-8"),
                )
            except OSError as exc:  # pragma: no cover
                logger.warning("Failed to write design backup '%s': %s", bak_path, exc)
        except Exception:
            if tmp_path is not None and tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError:  # pragma: no cover
                    pass
            raise


def load_design(name: str) -> dict:
    """Load design JSON honoring any monkeypatched `_load` on `silhouette_mcp.server`."""
    mod = sys.modules.get("silhouette_mcp.server")
    fn = getattr(mod, "_load", None) if mod is not None else None
    if callable(fn) and fn is not _load:
        return fn(name)
    return _load(name)


def save_design(d: dict) -> None:
    """Save design JSON honoring any monkeypatched `_save` on `silhouette_mcp.server`."""
    mod = sys.modules.get("silhouette_mcp.server")
    fn = getattr(mod, "_save", None) if mod is not None else None
    if callable(fn) and fn is not _save:
        fn(d)
        return
    _save(d)


def _add(design: str, label: str, **geom: Any) -> dict:
    with _LOCK:
        d = load_design(design)
        s = _append_shape_in_memory(d, label, **geom)
        save_design(d)
        return {
            "design": d["name"],
            "shape_id": s["id"],
            "layer": s["layer"],
            "bbox_mm": _r4(_bbox(s)),
            "warnings": _shape_warnings(d, s),
        }

