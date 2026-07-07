#!/usr/bin/env python3
"""
Chatbox Booster Manager - main entry point for the management application.

Launches:
1. The web UI server (in a background thread)
2. The system tray icon (blocking, main thread)

This is what the user launches from the Start Menu shortcut.
It is NOT the MCP server itself - that is launched by AI clients via server.py.
"""
import sys
import threading
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main():
    from app.core.config import Config, ensure_config_exists
    from app.core.shared_services import SharedContext
    from app.core.plugin_manager import PluginManager
    from app.manager.web_server import run_web_server
    from app.manager.tray import run_tray

    try:
        ensure_config_exists()
    except FileNotFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    config = Config()
    ctx = SharedContext(config)
    ctx.logger.info("Manager starting...")

    pm = PluginManager(ctx)
    pm.discover()
    ctx.logger.info(f"Discovered {len(pm.plugins)} plugin(s)")

    def _run_web():
        try:
            run_web_server(ctx, pm)
        except Exception as e:
            ctx.logger.error(f"Web server error: {e}")

    web_thread = threading.Thread(target=_run_web, daemon=True)
    web_thread.start()
    ctx.logger.info("Web UI thread started")

    try:
        run_tray(web_thread)
    except Exception as e:
        ctx.logger.error(f"Tray error: {e}")
        print(f"Tray failed: {e}. Web UI is still running. Press Ctrl+C to exit.")
        try:
            while True:
                import time
                time.sleep(1)
        except KeyboardInterrupt:
            pass


if __name__ == "__main__":
    main()