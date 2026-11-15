"""Low-level OS-locked concurrency and crash-safe atomic disk storage."""

from __future__ import annotations

import os
import sys
import tempfile
import threading
import time
from pathlib import Path
from typing import Any

if sys.platform.startswith("win"):
    import msvcrt
else:  # pragma: no cover
    import fcntl  # type: ignore[import-not-found]

from ..config.settings import get_runtime_attr, logger
from ..core.exceptions import SilhouetteRuntimeError
from ..core.validators import _slug


def _design_path(name: str) -> Path:
    return get_runtime_attr("OUTPUT_DIR") / f"{_slug(name)}.design.json"


def _backup_path(name: str) -> Path:
    return get_runtime_attr("OUTPUT_DIR") / f"{_slug(name)}.design.json.bak"


class _InterProcessLock:
    """Re-entrant thread lock paired with an OS-level lock file across processes."""

    def __init__(self) -> None:
        self._tlock = threading.RLock()
        self._local = threading.local()

    def _acquire_file_lock(self) -> int:
        out_dir: Path = get_runtime_attr("OUTPUT_DIR")
        lock_timeout_s: float = float(get_runtime_attr("LOCK_TIMEOUT_S"))
        out_dir.mkdir(parents=True, exist_ok=True)
        lock_file = out_dir / ".silhouette.lock"
        fd = os.open(str(lock_file), os.O_CREAT | os.O_RDWR, 0o666)
        deadline = time.monotonic() + lock_timeout_s
        attempt = 0
        try:
            while True:
                try:
                    if sys.platform.startswith("win"):
                        os.lseek(fd, 0, os.SEEK_SET)
                        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
                        if os.fstat(fd).st_size == 0:
                            os.lseek(fd, 0, os.SEEK_SET)
                            os.write(fd, b"0")
                    else:  # pragma: no cover
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    return fd
                except OSError:
                    if time.monotonic() >= deadline:
                        raise SilhouetteRuntimeError(
                            f"Timed out waiting for inter-process lock on {out_dir}."
                        )
                    attempt += 1
                    time.sleep(min(0.05, 0.005 * attempt))
        except BaseException:
            try:
                os.close(fd)
            except OSError:  # pragma: no cover
                pass
            raise

    def _release_file_lock(self, fd: int) -> None:
        try:
            if sys.platform.startswith("win"):
                os.lseek(fd, 0, os.SEEK_SET)
                msvcrt.locking(fd, msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover
                fcntl.flock(fd, fcntl.LOCK_UN)
        except OSError as exc:  # pragma: no cover
            logger.warning("Failed to release inter-process lock cleanly: %s", exc)
        finally:
            try:
                os.close(fd)
            except OSError:  # pragma: no cover
                pass

    def __enter__(self) -> "_InterProcessLock":
        self._tlock.acquire()
        try:
            depth = getattr(self._local, "depth", 0)
            if depth == 0:
                self._local.lock_fd = self._acquire_file_lock()
            self._local.depth = depth + 1
            return self
        except BaseException:
            self._tlock.release()
            raise

    def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        try:
            depth = getattr(self._local, "depth", 1) - 1
            self._local.depth = max(0, depth)
            if depth <= 0:
                fd = getattr(self._local, "lock_fd", None)
                self._local.lock_fd = None
                if fd is not None:
                    self._release_file_lock(fd)
        finally:
            self._tlock.release()


_LOCK = _InterProcessLock()


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
        if tmp_path.is_file():
            with open(tmp_path, "r+b") as f:
                f.flush()
                os.fsync(f.fileno())
        _atomic_replace(tmp_path, target_path)
    except Exception:
        if tmp_path is not None and tmp_path.exists():
            try:
                tmp_path.unlink()
            except OSError:  # pragma: no cover
                pass
        raise


def _cleanup_stale_temp_files(
    directory: Path,
    pattern: str = "*.tmp",
    max_age_s: float = 3600.0,
) -> int:
    """Remove abandoned atomic-write temporary files older than ``max_age_s``."""
    if not directory.is_dir():
        return 0
    cutoff = time.time() - max(0.0, float(max_age_s))
    removed = 0
    for candidate in directory.glob(pattern):
        try:
            if candidate.is_symlink() or not candidate.is_file():
                continue
            if max_age_s <= 0.0 or candidate.stat().st_mtime <= cutoff:
                candidate.unlink()
                removed += 1
        except OSError as exc:  # pragma: no cover
            logger.debug("Skipping stale temp cleanup for '%s': %s", candidate, exc)
    return removed


