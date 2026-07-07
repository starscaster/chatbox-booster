"""
Browser engine plugin — provides a Patchright browser service for SPA fallback.

This is an optional heavy plugin. When enabled, it runs a local HTTP service
that the web_fetch plugin can call for JavaScript-rendered pages.

This plugin does NOT register MCP tools directly. It only ensures the browser
service is available. The web_fetch plugin discovers it via the port file
in data/browser_engine/.
"""
import os
from pathlib import Path


def register(ctx):
    """The browser engine plugin provides infrastructure, not MCP tools.

    It does however register an event handler so that web_fetch can
    request a browser fetch through the event bus.
    """
    app_root = ctx.get_app_root()
    data_dir = app_root / "data" / "browser_engine"
    data_dir.mkdir(parents=True, exist_ok=True)

    ctx.logger.info("Browser engine plugin active (no MCP tools, provides browser service)")

    # This plugin provides no MCP tools — it's infrastructure.
    # The playwright_service.py runs as a separate subprocess when web_fetch
    # needs it (via browser_fallback.py's ensure_playwright_service()).
    return []