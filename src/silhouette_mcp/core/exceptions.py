"""MCP SDK compatibility layer, tool annotation helper, and dual-inheritance exceptions."""

from __future__ import annotations

from typing import Any

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


class SilhouetteValueError(ValueError, ToolError):
    """Erro de validacao/dominio: compativel com callers Python (ValueError) e MCP v2 (ToolError)."""


class SilhouetteRuntimeError(RuntimeError, ToolError):
    """Erro de execucao previsto: compativel com callers Python (RuntimeError) e MCP v2 (ToolError)."""


def _ann(
    *,
    read_only: bool = False,
    destructive: bool = False,
    idempotent: bool = False,
    open_world: bool = False,
) -> Any:
    """Build optional MCP ToolAnnotations descriptor."""
    if ToolAnnotations is None:  # pragma: no cover
        return None
    return ToolAnnotations(
        read_only_hint=read_only,
        destructive_hint=destructive,
        idempotent_hint=idempotent,
        open_world_hint=open_world,
    )

