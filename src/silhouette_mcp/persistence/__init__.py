"""Persistence package combining OS-locked atomic storage and design repository helpers."""

from .repository import _add, _load, _save, load_design, save_design
from .storage import (
    _LOCK,
    _InterProcessLock,
    _atomic_replace,
    _atomic_write_file,
    _backup_path,
    _cleanup_stale_temp_files,
    _design_path,
)

__all__ = [
    "_InterProcessLock",
    "_LOCK",
    "_add",
    "_atomic_replace",
    "_atomic_write_file",
    "_backup_path",
    "_cleanup_stale_temp_files",
    "_design_path",
    "_load",
    "_save",
    "load_design",
    "save_design",
]

