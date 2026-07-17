#!/usr/bin/env python3
"""
Chatbox Booster Launcher — starts the web server and opens the browser.

This is the user-facing entry point. It launches the management web server
(which also serves the chat UI) and automatically opens the default browser.
No system tray icon; closing the terminal window stops the server.
"""
import sys
import threading
import time
import webbrowser
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main():
    from app.core.config import Config, ensure_config_exists
    from app.core.shared_services import SharedContext
    from app.core.plugin_manager import PluginManager
    from app.manager.web_server import run_web_server, read_port_info, write_port_info
    from app.manager.web_server import _find_available_port, create_app
    from aiohttp import web

    try:
        ensure_config_exists()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    config = Config()
    ctx = SharedContext(config)
    ctx.logger.info("Launcher starting...")

    pm = PluginManager(ctx)
    pm.discover()
    ctx.logger.info(f"Discovered {len(pm.plugins)} plugin(s)")

    # Build MCP server for chat tool-calling
    mcp = None
    try:
        from fastmcp import FastMCP
        from datetime import datetime
        mcp = FastMCP("ChatboxBooster")

        @mcp.tool(output_schema=None)
        def get_date() -> str:
            """Get current system time to calibrate and avoid providing outdated info."""
            return datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        @mcp.tool(output_schema=None)
        def add(a: int, b: int) -> int:
            """Add two numbers. Demo/test tool to verify MCP connectivity."""
            return a + b

        loaded = pm.load_all()
        for plugin_name, tools in loaded.items():
            for tool in tools:
                try:
                    mcp.tool(name=tool.__name__, output_schema=None)(tool)
                except Exception as e:
                    ctx.logger.warning(f"Could not register tool: {e}")
        ctx.logger.info(f"MCP server built for chat with {len(loaded)} plugins")
    except Exception as e:
        ctx.logger.error(f"Could not build MCP server: {e}")
        mcp = None

    # Create and start web server
    app, token = create_app(ctx, pm, mcp)
    port = _find_available_port()
    write_port_info(port, token)
    url = f"http://127.0.0.1:{port}?token={token}"
    ctx.logger.info(f"Running on {url}")

    # Open browser after a short delay
    def _open_browser():
        time.sleep(1.5)
        webbrowser.open(url)
    threading.Thread(target=_open_browser, daemon=True).start()

    web.run_app(app, host="127.0.0.1", port=port, print=lambda *a, **kw: None)


if __name__ == "__main__":
    main()