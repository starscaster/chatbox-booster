"""
MCP server entry point.

Initializes SharedContext, discovers and loads plugins via PluginManager,
and registers all plugin-provided tools with a FastMCP instance.
"""
import json
import sys
from pathlib import Path
from typing import Callable

from .config import Config, ensure_config_exists
from .shared_services import SharedContext
from .plugin_manager import PluginManager


def _check_restart_marker(ctx: SharedContext):
    """Check for .needs_restart marker from management UI and log a warning."""
    marker = ctx.get_app_root() / "data" / "manager" / ".needs_restart"
    if marker.exists():
        try:
            info = json.loads(marker.read_text(encoding="utf-8"))
            ctx.logger.warning(
                f"Plugin configuration changed since last start: "
                f"'{info.get("plugin", "unknown")}' was {info.get("action", "changed")} "
                f"at {info.get("timestamp", "?")}. Changes are now in effect."
            )
            marker.unlink()
        except Exception as e:
            ctx.logger.warning(f"Found restart marker but failed to read it: {e}")
            try:
                marker.unlink()
            except Exception:
                pass


def build_mcp_server():
    """Build and return a configured FastMCP instance with all plugin tools.

    This is the single entry point used by server.py (the stdio MCP server).
    """
    from fastmcp import FastMCP

    ensure_config_exists()
    config = Config()
    ctx = SharedContext(config)
    ctx.logger.info("Starting Chatbox Booster v2 ...")

    _check_restart_marker(ctx)

    pm = PluginManager(ctx)
    pm.discover()
    ctx.logger.info(f"Discovered {len(pm.plugins)} plugin(s): {list(pm.plugins.keys())}")

    loaded = pm.load_all()
    total_tools = sum(len(tools) for tools in loaded.values())
    ctx.logger.info(f"Loaded {len(loaded)} plugin(s) with {total_tools} tool(s) total")

    mcp = FastMCP("ChatboxBooster")

    # Register built-in tools (always available)
    _register_builtin_tools(mcp, ctx)

    # Register plugin tools
    for plugin_name, tools in loaded.items():
        for tool in tools:
            _register_tool(mcp, tool)
            ctx.logger.debug(f"Registered tool '{tool.__name__}' from plugin '{plugin_name}'")

    return mcp, ctx, pm


def _register_tool(mcp, tool: Callable):
    """Register a single tool function with FastMCP."""
    if hasattr(tool, "_mcp_tool_info"):
        mcp.add_tool(tool)
    else:
        mcp.tool(name=tool.__name__, output_schema=None)(tool)


def _register_builtin_tools(mcp, ctx):
    """Register tools that are always available (not part of any plugin)."""
    from datetime import datetime

    @mcp.tool(output_schema=None)
    def get_date() -> str:
        """Get current system time to calibrate and avoid providing outdated info."""
        return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    @mcp.tool(output_schema=None)
    def add(a: int, b: int) -> int:
        """Add two numbers. Demo/test tool to verify MCP connectivity."""
        return a + b
