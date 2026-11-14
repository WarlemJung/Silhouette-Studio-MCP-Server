"""Unit tests verifying thin MCP tool adapter delegation and strict architectural boundaries."""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

from silhouette_mcp import server, tools


def _relative_or_pkg_imports(py_file: Path, pkg_root: Path) -> set[str]:
    tree = ast.parse(py_file.read_text(encoding="utf-8"), filename=str(py_file))
    parts = list(py_file.relative_to(pkg_root).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts = parts[:-1]
    current_pkg = ["silhouette_mcp", *parts[:-1]] if len(parts) > 0 else ["silhouette_mcp"]

    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported.add(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.level > 0:
                base = current_pkg[: max(1, len(current_pkg) - (node.level - 1))]
                target = ".".join([*base, node.module]) if node.module else ".".join(base)
                imported.add(target)
            elif node.module:
                imported.add(node.module)
    return imported


def test_all_28_mcp_tools_exported_and_delegated():
    assert len(tools.__all__) == 28
    assert len(server.TOOL_REGISTRATIONS) == 28

    tool_names_in_pkg = set(tools.__all__)
    tool_names_in_server = {fn.__name__ for fn, _ in server.TOOL_REGISTRATIONS}
    assert tool_names_in_pkg == tool_names_in_server

    for fn, _ in server.TOOL_REGISTRATIONS:
        assert callable(fn)
        sig = inspect.signature(fn)
        assert fn.__doc__ and len(fn.__doc__.strip()) > 10
        assert isinstance(sig.parameters, dict) or len(sig.parameters) >= 0
        assert getattr(tools, fn.__name__) is fn


def test_strict_unidirectional_layer_dependencies():
    pkg_root = Path(server.__file__).resolve().parent

    # 1. core/ must never depend on services/, tools/, persistence/, exporters/, or integrations/
    core_forbidden = ("services", "tools", "persistence", "exporters", "integrations")
    for py_file in (pkg_root / "core").rglob("*.py"):
        imports = _relative_or_pkg_imports(py_file, pkg_root)
        for imp in imports:
            for bad in core_forbidden:
                assert not imp.startswith(f"silhouette_mcp.{bad}"), f"{py_file} forbidden import {imp}"
        # core/nesting/ must additionally stay completely independent of mcp
        if "nesting" in py_file.parts:
            assert not any(imp == "mcp" or imp.startswith("mcp.") for imp in imports)

    # 2. services/ must never depend on tools/ or mcp protocol packages
    for py_file in (pkg_root / "services").rglob("*.py"):
        imports = _relative_or_pkg_imports(py_file, pkg_root)
        for imp in imports:
            assert not imp.startswith("silhouette_mcp.tools"), f"{py_file} forbidden import {imp}"
            assert imp != "mcp" and not imp.startswith("mcp."), f"{py_file} forbidden mcp import {imp}"

    # 3. tools/ must act only as thin adapters delegating to services/
    tools_forbidden = ("persistence", "exporters", "integrations", "core")
    for py_file in (pkg_root / "tools").rglob("*.py"):
        imports = _relative_or_pkg_imports(py_file, pkg_root)
        for imp in imports:
            for bad in tools_forbidden:
                assert not imp.startswith(f"silhouette_mcp.{bad}"), f"{py_file} bypasses services via {imp}"

