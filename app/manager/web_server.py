"""
Local web server for the management UI.

Runs an aiohttp server on 127.0.0.1 with a random port.
The port and auth token are written to a known location for the tray app to find.
"""
import json
import os
import random
import socket
from pathlib import Path

from app.core.shared_services import _DATA_ROOT
from aiohttp import web

from .api_handlers import setup_routes
from .chat_handlers import setup_chat_routes
from ..core.config import Config, ensure_config_exists
from ..core.shared_services import SharedContext
from ..core.plugin_manager import PluginManager


def _find_available_port():
    for _ in range(20):
        port = random.randint(18000, 25000)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
            s.close()
            return port
        except OSError:
            continue
    raise RuntimeError("No available port")


def _get_app_root():
    return Path(__file__).resolve().parent.parent.parent


def _get_port_file():
    return _DATA_ROOT / "data" / "manager" / ".webui_port"


def _get_token_file():
    return _DATA_ROOT / "data" / "manager" / ".webui_token"


def write_port_info(port: int, token: str):
    data_dir = _DATA_ROOT / "data" / "manager"
    data_dir.mkdir(parents=True, exist_ok=True)
    _get_port_file().write_text(str(port))
    _get_token_file().write_text(token)


def read_port_info():
    port_file = _get_port_file()
    token_file = _get_token_file()
    if not port_file.exists():
        return None, None
    port = int(port_file.read_text().strip())
    token = token_file.read_text().strip() if token_file.exists() else ""
    return port, token


def create_app(ctx: SharedContext, pm: PluginManager, mcp=None):
    """Create and configure the aiohttp web application."""
    import secrets
    static_dir = str(Path(__file__).resolve().parent / "static")
    token = secrets.token_hex(16)

    app = web.Application()
    app["ctx"] = ctx
    app["pm"] = pm
    app["mcp"] = mcp
    app["static_dir"] = static_dir
    app["token"] = token

    setup_routes(app)

    setup_chat_routes(app)

    # Simple token auth middleware
    @web.middleware
    async def auth_middleware(request, handler):
        # Allow static assets and index without token (simplified for local use)
        if request.path.startswith("/api/"):
            auth = request.headers.get("Authorization", "")
            token_param = request.query.get("token", "")
            if auth != f"Bearer {token}" and token_param != token:
                return web.json_response({"error": "unauthorized"}, status=401)
        return await handler(request)

    app.middlewares.append(auth_middleware)

    return app, token


def run_web_server(ctx: SharedContext, pm: PluginManager, mcp=None):
    """Run the web server (blocking). Returns the port."""
    app, token = create_app(ctx, pm, mcp)
    port = _find_available_port()
    write_port_info(port, token)
    ctx.logger.info(f"Web UI running on http://127.0.0.1:{port}?token={token}")
    web.run_app(app, host="127.0.0.1", port=port, print=lambda *a, **kw: None)
    return port