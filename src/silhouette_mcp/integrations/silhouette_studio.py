"""Desktop integration with Silhouette Studio on Windows and macOS."""

from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

from ..config.settings import get_runtime_attr, logger
from ..core.exceptions import SilhouetteRuntimeError, SilhouetteValueError
from ..core.validators import _slug


def _find_studio_exe() -> str:
    studio_exe = str(get_runtime_attr("STUDIO_EXE") or "").strip()
    if studio_exe:
        se_path = Path(studio_exe)
        if se_path.is_file() or (sys.platform == "darwin" and se_path.suffix.lower() == ".app" and se_path.is_dir()):
            return studio_exe
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
    elif sys.platform == "darwin":
        for bundle in (
            Path("/Applications/Silhouette Studio.app"),
            Path.home() / "Applications" / "Silhouette Studio.app",
        ):
            if bundle.is_dir():
                return str(bundle)
    return ""


def _resolve_studio_exe() -> str:
    mod = sys.modules.get("silhouette_mcp.server")
    fn = getattr(mod, "_find_studio_exe", None) if mod is not None else None
    if callable(fn) and fn is not _find_studio_exe:
        return str(fn() or "")
    return _find_studio_exe()


def silhouette_open_in_studio(path: str, reveal_in_explorer: bool = False) -> dict:
    """Open a cut file previously exported (.dxf or .svg) directly in Silhouette Studio.
    Accepts full paths, paths relative to the output folder, or just design/file names.
    Set reveal_in_explorer=true to also select the file in Windows Explorer."""
    if not isinstance(path, str) or not path.strip() or "\x00" in path:
        raise SilhouetteValueError("path must be a valid non-empty file path or design name.")
    raw_str = path.strip()
    if raw_str.startswith("\\\\") or raw_str.startswith("//"):
        raise SilhouetteValueError("Network/UNC paths are not allowed.")

    out_dir: Path = get_runtime_attr("OUTPUT_DIR")
    try:
        p = Path(raw_str).expanduser()
        if not p.is_file():
            # Tenta localizar dentro de OUTPUT_DIR (literal e normalizado via _slug)
            candidates = [
                out_dir / raw_str,
                out_dir / f"{raw_str}.dxf",
                out_dir / f"{raw_str}.svg",
            ]
            try:
                raw_p = Path(raw_str)
                ext = raw_p.suffix.lower()
                if raw_p.name.lower() in ("calibracao_100x100mm.dxf", "calibracao_100x100mm"):
                    candidates.append(out_dir / "calibration-100mm.dxf")
                if ext in (".dxf", ".svg"):
                    slug = _slug(raw_p.stem)
                    candidates.append(out_dir / f"{slug}{ext}")
                else:
                    slug = _slug(raw_str)
                    candidates.append(out_dir / f"{slug}.dxf")
                    candidates.append(out_dir / f"{slug}.svg")
            except ValueError:
                pass
            for candidate in candidates:
                cand_exp = candidate.expanduser()
                if cand_exp.is_file():
                    p = cand_exp
                    break
        p = p.resolve()
    except (OSError, ValueError) as e:
        raise SilhouetteValueError(f"Invalid path '{path}': {e}") from e

    if str(p).startswith("\\\\") or str(p).startswith("//"):
        raise SilhouetteValueError("Network/UNC paths are not allowed.")

    if p.suffix.lower() not in (".dxf", ".svg") or not p.is_file():
        raise SilhouetteValueError(f"File '{path}' not found or is not a .dxf/.svg file.")

    def _launch_process(cmd: list[str]) -> None:
        proc = subprocess.Popen(cmd)
        if proc is not None and hasattr(proc, "poll"):
            time.sleep(0.02)
            rc = proc.poll()
            if rc is not None and rc != 0:
                raise SilhouetteRuntimeError(
                    f"Application '{cmd[0]}' exited immediately with code {rc} while opening '{p}'."
                )

    if sys.platform.startswith("win"):
        exe = _resolve_studio_exe()
        if exe:
            try:
                _launch_process([exe, str(p)])
            except SilhouetteRuntimeError:
                raise
            except OSError as e:
                raise SilhouetteRuntimeError(f"Failed to open '{p}' in Silhouette Studio: {e}") from e
            if reveal_in_explorer:
                try:
                    subprocess.Popen(["explorer.exe", f"/select,{p}"])
                except OSError as exc:
                    logger.warning("Failed to reveal file in Explorer: %s", exc)
            return {
                "opened": str(p),
                "method": f"launched {exe}",
                "process_launched": True,
                "homologated_import": False,
                "note": "Processo iniciado; confirme importacao e escala manualmente no Silhouette Studio.",
            }
        try:
            os.startfile(str(p))  # type: ignore[attr-defined]
        except OSError as e:
            raise SilhouetteRuntimeError(f"Failed to open '{p}' in Silhouette Studio: {e}") from e
        return {
            "opened": str(p),
            "method": "default file association (Studio executable not found; "
                      "set SILHOUETTE_STUDIO_EXE if another app opened it)",
            "process_launched": True,
            "homologated_import": False,
        }
    if sys.platform == "darwin":
        exe = _resolve_studio_exe()
        if exe:
            if exe.lower().endswith(".app"):
                cmd = ["open", "-a", exe, str(p)]
                method = f"open -a '{exe}'"
            else:
                cmd = [exe, str(p)]
                method = f"launched {exe}"
        else:
            cmd = ["open", "-a", "Silhouette Studio", str(p)]
            method = "open -a 'Silhouette Studio'"
        try:
            _launch_process(cmd)
        except SilhouetteRuntimeError:
            raise
        except OSError as e:
            raise SilhouetteRuntimeError(f"Failed to open '{p}' in Silhouette Studio: {e}") from e
        return {
            "opened": str(p),
            "method": method,
            "process_launched": True,
            "homologated_import": False,
        }
    raise SilhouetteValueError("Opening Silhouette Studio is only supported on Windows and macOS.")

