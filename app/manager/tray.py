"""
System tray icon for Chatbox Booster management.

Shows status, provides menu to open web UI, and exits cleanly.
Uses pystray + Pillow for the tray icon.
"""
import os
import sys
import threading
import webbrowser
from pathlib import Path


def _get_app_root():
    return Path(__file__).resolve().parent.parent.parent


def _read_port_info():
    port_file = _DATA_ROOT / "data" / "manager" / ".webui_port"
    token_file = _DATA_ROOT / "data" / "manager" / ".webui_token"
    if not port_file.exists():
        return None, None
    port = int(port_file.read_text().strip())
    token = token_file.read_text().strip() if token_file.exists() else ""
    return port, token


def _create_icon_image():
    """Create a simple colored circle icon."""
    from PIL import Image, ImageDraw
    img = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw.ellipse([8, 8, 56, 56], fill=(233, 69, 96, 255))
    draw.ellipse([20, 20, 44, 44], fill=(255, 255, 255, 200))
    return img


def run_tray(web_server_thread):
    """Run the system tray icon. Blocks until tray is exited."""
    import pystray
    from pystray import MenuItem, Menu

    def open_webui(icon, item):
        port, token = _read_port_info()
        if port:
            url = f"http://127.0.0.1:{port}?token={token}"
            webbrowser.open(url)

    def on_quit(icon, item):
        icon.stop()
        # The web server thread is daemon, will be killed when main exits
        os._exit(0)

    menu = Menu(
        MenuItem("Open Settings", open_webui, default=True),
        MenuItem("Quit", on_quit),
    )

    icon = pystray.Icon("ChatboxBooster", _create_icon_image(), "Chatbox Booster", menu)
    icon.run()