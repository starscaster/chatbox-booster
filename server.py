#!/usr/bin/env python3
"""
Chatbox Booster v2 - MCP Server Entry Point

This file is launched by AI clients (Chatbox, Claude Desktop, etc.) via stdio.
It should NOT be run directly by the user in normal operation.
For configuration and management, launch manager_main.py instead.
"""
import sys
from pathlib import Path

# Ensure the app package is importable
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.mcp_server import build_mcp_server


def main():
    mcp, ctx, pm = build_mcp_server()
    ctx.logger.info("MCP server starting (stdio mode) ...")
    mcp.run()


if __name__ == "__main__":
    main()