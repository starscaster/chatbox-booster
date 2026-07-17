import asyncio
import json
import os
import random
import signal
import socket
import sys
import time
from pathlib import Path
from app.core.shared_services import _DATA_ROOT

_APP_ROOT = Path(__file__).resolve().parent.parent.parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))

from app.core.dep_manager import ensure_deps

ensure_deps({
    "aiohttp": "aiohttp",
    "patchright": "patchright",
})

import aiohttp
from aiohttp import web


_SCRIPT_DIR = _DATA_ROOT / "browser_engine"

IDLE_TIMEOUT = int(os.environ.get("PW_IDLE_TIMEOUT", "600"))
MAX_CONCURRENT = int(os.environ.get("PW_MAX_CONCURRENT", "5"))
PAGE_TIMEOUT = int(os.environ.get("PW_PAGE_TIMEOUT", "30000"))
REQUEST_TIMEOUT = int(os.environ.get("PW_REQUEST_TIMEOUT", "60000"))

PORT_FILE = _SCRIPT_DIR / ".playwright_port"
PID_FILE = _SCRIPT_DIR / ".playwright_pid"

BROWSER_CHANNELS = ["msedge", "chrome", "chromium"]

BLOCK_PATTERNS = [
    "**/*.{png,jpg,jpeg,gif,svg,ico,webp,avif,bmp,tiff}",
    "**/*.{mp4,webm,ogg,mp3,wav,flac}",
    "**/*.{woff,woff2,ttf,eot}",
    "**/*.css*",
    "**/*analytics*",
    "**/*tracker*",
    "**/google-analytics.com/**",
    "**/googletagmanager.com/**",
    "**/doubleclick.net/**",
    "**/facebook.com/tr/**",
]


def _find_available_port():
    for _ in range(20):
        port = random.randint(20000, 50000)
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            s.bind(("127.0.0.1", port))
            s.close()
            return port
        except OSError:
            continue
    raise RuntimeError("No available port in range 20000-50000")


class PlaywrightService:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self._semaphore = asyncio.Semaphore(MAX_CONCURRENT)
        self._active_count = 0
        self._last_access = time.time()
        self._started_at = time.time()
        self._shutting_down = False
        self._max_hard_lifetime = 7200

    async def start(self):
        from patchright.async_api import async_playwright

        self.playwright = await async_playwright().start()

        for channel in BROWSER_CHANNELS:
            try:
                self.browser = await self.playwright.chromium.launch(
                    channel=channel,
                    headless=True,
                    args=[
                        "--disable-gpu",
                        "--disable-software-rasterizer",
                        "--disable-dev-shm-usage",
                        "--no-sandbox",
                        "--disable-extensions",
                        "--disable-background-networking",
                        "--disable-sync",
                        "--disable-translate",
                        "--disable-default-apps",
                        "--mute-audio",
                        "--hide-scrollbars",
                        "--disable-component-update",
                        "--disable-breakpad",
                        "--disable-hang-monitor",
                        "--no-first-run",
                        "--disable-features=TranslateUI,OptimizationHints",
                        "--disable-backgrounding-occluded-windows",
                        "--disable-renderer-backgrounding",
                        "--disable-ipc-flooding-protection",
                        "--force-color-profile=srgb",
                    ],
                )
                print(f"[playwright_service] browser launched: channel={channel}")
                break
            except Exception as e:
                print(f"[playwright_service] channel={channel} failed: {e}")
                continue
        else:
            raise RuntimeError("No available browser channel. Tried: " + ", ".join(BROWSER_CHANNELS))

        await self._warmup()

    async def _warmup(self):
        try:
            context = await self.browser.new_context(viewport={"width": 1280, "height": 720})
            page = await context.new_page()
            await page.goto("about:blank", wait_until="load", timeout=10000)
            await page.close()
            await context.close()
            print("[playwright_service] warmup complete")
        except Exception as e:
            print(f"[playwright_service] warmup failed (non-fatal): {e}")

    async def _ensure_browser(self):
        if self.browser is None or not self.browser.is_connected():
            print("[playwright_service] browser disconnected, re-launching...")
            await self.start()

    def _touch(self):
        self._last_access = time.time()

    async def _setup_block_routes(self, page):
        for pattern in BLOCK_PATTERNS:
            await page.route(pattern, lambda route: route.abort())

    async def fetch(self, url: str, timeout_ms: int = PAGE_TIMEOUT):
        self._touch()

        await self._ensure_browser()

        async with self._semaphore:
            self._active_count += 1
            context = None
            try:
                context = await self.browser.new_context(
                    viewport={"width": 1280, "height": 720},
                    user_agent=(
                        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                        "AppleWebKit/537.36 (KHTML, like Gecko) "
                        "Chrome/131.0.0.0 Safari/537.36"
                    ),
                )
                page = await context.new_page()
                await self._setup_block_routes(page)

                resp = await page.goto(
                    url,
                    wait_until="domcontentloaded",
                    timeout=timeout_ms,
                )

                status_code = resp.status if resp else 0

                try:
                    await page.wait_for_load_state("networkidle", timeout=8000)
                except Exception as e:
                    print(f"[playwright_service] wait_for_load_state failed: {e}")

                try:
                    await page.wait_for_selector(
                        "p, h1, h2, h3, h4, h5, h6, article, section, div, span, li",
                        timeout=3000,
                    )
                except Exception as e:
                    print(f"[playwright_service] wait_for_selector failed: {e}")

                raw_html = await page.content()
                page_title = await page.title()

                await page.close()
                await context.close()
                context = None

                return {
                    "ok": True,
                    "url": url,
                    "status_code": status_code,
                    "title": page_title,
                    "html": raw_html,
                }

            except Exception as e:
                error_type = type(e).__name__
                error_msg = str(e)
                if "net::ERR_" in error_msg or "NS_ERROR_" in error_msg:
                    return {
                        "ok": False,
                        "url": url,
                        "status_code": 0,
                        "error": f"{error_type}: {error_msg[:200]}",
                    }
                return {
                    "ok": False,
                    "url": url,
                    "status_code": 0,
                    "error": f"{error_type}: {error_msg[:200]}",
                }
            finally:
                self._active_count -= 1
                if context is not None:
                    try:
                        await context.close()
                    except Exception as e:
                        print(f"[playwright_service] context.close error: {e}")

    async def health(self):
        if self._shutting_down:
            return False
        if self.browser is None:
            return False
        try:
            return self.browser.is_connected()
        except Exception:
            return False

    async def shutdown(self):
        if self._shutting_down:
            return
        self._shutting_down = True
        print("[playwright_service] shutting down...")

        timeout_grace = 30
        waited = 0
        while self._active_count > 0 and waited < timeout_grace:
            await asyncio.sleep(1)
            waited += 1
        if self._active_count > 0:
            print(f"[playwright_service] force shutdown with {self._active_count} active requests")

        try:
            if self.browser:
                await self.browser.close()
        except Exception as e:
            print(f"[playwright_service] browser.close error: {e}")

        try:
            if self.playwright:
                await self.playwright.stop()
        except Exception as e:
            print(f"[playwright_service] playwright.stop error: {e}")

        for f in (PORT_FILE, PID_FILE):
            try:
                f.unlink(missing_ok=True)
            except Exception as e:
                print(f"[playwright_service] failed to unlink {f.name}: {e}")

        print("[playwright_service] shutdown complete")

    async def idle_watchdog(self):
        while not self._shutting_down:
            await asyncio.sleep(15)
            elapsed = time.time() - self._last_access
            hard_lifetime = time.time() - self._started_at

            if hard_lifetime > self._max_hard_lifetime:
                print("[playwright_service] hard lifetime reached, forced shutdown")
                await self.shutdown()
                return

            if elapsed > IDLE_TIMEOUT and self._active_count == 0:
                print(f"[playwright_service] idle {elapsed:.0f}s, shutting down")
                await self.shutdown()
                return


async def handle_fetch(request):
    svc = request.app["service"]

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)

    url = body.get("url", "")
    if not url or not url.startswith(("http://", "https://")):
        return web.json_response({"ok": False, "error": "invalid url"}, status=400)

    timeout_ms = min(body.get("timeout", PAGE_TIMEOUT), 60000)

    result = await svc.fetch(url, timeout_ms=timeout_ms)
    if result["ok"]:
        return web.json_response(result)
    return web.json_response(result, status=502)


async def handle_health(request):
    svc = request.app["service"]
    ok = await svc.health()
    if ok:
        return web.json_response({"status": "ok", "uptime": int(time.time() - svc._started_at)})
    return web.json_response({"status": "dead"}, status=503)


async def handle_shutdown(request):
    svc = request.app["service"]
    asyncio.ensure_future(_delayed_shutdown(svc))
    return web.json_response({"status": "shutting_down"})


async def _delayed_shutdown(svc):
    await asyncio.sleep(1)
    await svc.shutdown()
    asyncio.get_event_loop().stop()


def main():
    print(f"[playwright_service] starting (idle_timeout={IDLE_TIMEOUT}s, max_concurrent={MAX_CONCURRENT})")

    port = _find_available_port()
    PORT_FILE.write_text(str(port))
    PID_FILE.write_text(str(os.getpid()))

    service = PlaywrightService()

    app = web.Application()
    app["service"] = service
    app.router.add_post("/fetch", handle_fetch)
    app.router.add_get("/health", handle_health)
    app.router.add_post("/shutdown", handle_shutdown)

    async def on_startup(app):
        await service.start()
        asyncio.ensure_future(service.idle_watchdog())
        print(f"[playwright_service] listening on http://127.0.0.1:{port}")

    async def on_cleanup(app):
        await service.shutdown()

    app.on_startup.append(on_startup)
    app.on_cleanup.append(on_cleanup)

    web.run_app(app, host="127.0.0.1", port=port, print=lambda *a, **kw: None)


if __name__ == "__main__":
    main()