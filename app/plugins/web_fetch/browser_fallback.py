"""
Browser fallback for SPA pages and 403 anti-scraping.

Checks if browser_engine plugin is available via event bus.
If not, silently degrades to curl_cffi-only mode.
"""
import asyncio
import json
import os
import re
import subprocess
import sys
import time
from pathlib import Path


_PORT_FILE = None
_PID_FILE = None
_SERVICE_URL = None


def _get_port_files(app_root: Path):
    global _PORT_FILE, _PID_FILE
    if _PORT_FILE is None:
        _PORT_FILE = app_root / "data" / "browser_engine" / ".playwright_port"
        _PID_FILE = app_root / "data" / "browser_engine" / ".playwright_pid"
    return _PORT_FILE, _PID_FILE


SPA_PATTERNS = [
    re.compile(r'<div\s+id=["\'](__next|__nuxt|app|root)["\'][^>]*>\s*</div>', re.I),
    re.compile(r'<script\s+[^>]*src=["\'][^"\']*/(bundle|main|app|chunk)[^"\']*\.js["\']', re.I),
    re.compile(r"window\.__NEXT_DATA__"),
    re.compile(r"window\.__NUXT__"),
    re.compile(r"<noscript>[^<]*enable\s*JavaScript", re.I),
    re.compile(r"<noscript>[^<]*\u8bf7\s*\u542f\u7528\s*JavaScript", re.I),
    re.compile(r'<div\s+id=["\']app["\'][^>]*></div>', re.I),
    re.compile(r'<script\s+type=["\']module["\']', re.I),
]


def is_spa_shell(html_text: str, extracted_text: str) -> bool:
    if len(extracted_text.strip()) > 500:
        return False
    for pattern in SPA_PATTERNS:
        if pattern.search(html_text):
            return True
    if len(html_text) > 5000 and len(extracted_text.strip()) < 200:
        return True
    body_match = re.search(r"<body[^>]*>(.*?)</body>", html_text, re.DOTALL | re.I)
    if body_match:
        body_text = re.sub(r"<[^>]+>", "", body_match.group(1)).strip()
        body_text = re.sub(r"\s+", " ", body_text)
        if len(body_text) < 100:
            return True
    return False


async def _health_check(app_root: Path):
    import aiohttp
    port_file, _ = _get_port_files(app_root)
    if not port_file.exists():
        return False
    try:
        port = int(port_file.read_text().strip())
        url = f"http://127.0.0.1:{port}"
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{url}/health", timeout=aiohttp.ClientTimeout(total=3)) as resp:
                return resp.status == 200
    except Exception as e:
        print(f"[browser_fallback] health check failed for {url}: {e}")
        return False


def _start_service(app_root: Path):
    import aiohttp
    port_file, _ = _get_port_files(app_root)
    data_dir = app_root / "data" / "browser_engine"
    data_dir.mkdir(parents=True, exist_ok=True)

    # Find browser_engine plugin's service script
    service_script = app_root / "app" / "plugins" / "browser_engine" / "playwright_service.py"
    if not service_script.exists():
        return False

    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.Popen(
        [sys.executable, str(service_script)],
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    for _ in range(40):
        time.sleep(0.25)
        if port_file.exists():
            return True
    return False


async def ensure_playwright_service(app_root: Path):
    if await _health_check(app_root):
        return
    if not _start_service(app_root):
        return
    for _ in range(30):
        await asyncio.sleep(0.5)
        if await _health_check(app_root):
            return


async def _fetch_via_playwright(url: str, timeout: int, app_root: Path):
    import aiohttp
    port_file, _ = _get_port_files(app_root)
    if not port_file.exists():
        return None
    try:
        port = int(port_file.read_text().strip())
        base_url = f"http://127.0.0.1:{port}"
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{base_url}/fetch",
                json={"url": url, "timeout": timeout * 1000},
                timeout=aiohttp.ClientTimeout(total=timeout + 15),
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
    except Exception as e:
        print(f"[browser_fallback] playwright fetch failed for {url}: {e}")
    return None


async def browser_fallback_fetch(
    url: str,
    raw_html: str,
    extracted_text: str,
    timeout: int,
    text_only: bool,
    max_tokens: int,
    locale,
    app_root: Path,
    force: bool = False,
):
    """Try fetching via browser engine. Returns result string or None."""
    if not force and not is_spa_shell(raw_html, extracted_text):
        return None

    await ensure_playwright_service(app_root)
    result = await _fetch_via_playwright(url, timeout=timeout, app_root=app_root)
    if result is None or not result.get("ok"):
        return None

    pw_html = result.get("html", "")
    if not pw_html:
        return None

    from .text_extractor import extract_text_from_html
    text = extract_text_from_html(pw_html, text_only=text_only, url=url, locale=locale)
    if not text:
        return None

    from .text_extractor import _count_tokens, _truncate_by_tokens, _clean_reference_noise

    if text_only:
        text = _clean_reference_noise(text)

    tokens = _count_tokens(text)
    if tokens < 4000:
        result_str = locale.get("success_header", code=200)
        result_str += f"\n\n{text}"
        return result_str
    if tokens <= max_tokens:
        result_str = locale.get("token_length", tokens=tokens, length=len(text))
        result_str += f"\n\n{text}"
        return result_str
    truncated = _truncate_by_tokens(text, max_tokens)
    trunc_tokens = _count_tokens(truncated)
    pct = round((1 - trunc_tokens / tokens) * 100)
    result_str = locale.get("token_truncated", tokens=trunc_tokens, pct=pct, length=len(truncated))
    result_str += f"\n\n{truncated}"
    return result_str
