"""
SharedContext — the service container passed to every plugin's register() function.

Provides unified access to config, proxy resolution, locale, logging,
HTTP session factory, and a lightweight event bus for inter-plugin communication.
"""
import asyncio
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .config import Config
from .locale import LocaleHelper, detect_locale

_APP_ROOT = Path(__file__).resolve().parent.parent.parent
_LOG_DIR = _APP_ROOT / "logs"


class _EventBus:
    """Minimal async event bus for loose plugin coupling."""

    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = {}

    def on(self, event: str, handler: Callable) -> None:
        self._handlers.setdefault(event, []).append(handler)

    def emit(self, event: str, data: Any = None) -> None:
        for handler in self._handlers.get(event, []):
            try:
                result = handler(data)
                if asyncio.iscoroutine(result):
                    asyncio.ensure_future(result)
            except Exception as e:
                logging.warning(f"Event bus handler error for '{event}': {e}")


class _Logger:
    """Structured logger that writes to both console and a log file."""

    def __init__(self, name: str = "chatbox-booster"):
        self._logger = logging.getLogger(name)
        self._logger.setLevel(logging.DEBUG)
        self._file_handler: Optional[logging.FileHandler] = None
        self._setup()
        self._recent: List[str] = []
        self._max_recent = 200

    def _setup(self):
        if self._logger.handlers:
            return
        _LOG_DIR.mkdir(parents=True, exist_ok=True)
        log_file = _LOG_DIR / f"{datetime.now().strftime('%Y-%m-%d')}.log"
        self._file_handler = logging.FileHandler(log_file, encoding="utf-8")
        self._file_handler.setLevel(logging.DEBUG)
        fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")
        self._file_handler.setFormatter(fmt)
        self._logger.addHandler(self._file_handler)
        console = logging.StreamHandler()
        console.setLevel(logging.INFO)
        console.setFormatter(fmt)
        self._logger.addHandler(console)

    def _record(self, level: str, msg: str):
        entry = f"[{level}] {msg}"
        self._recent.append(entry)
        if len(self._recent) > self._max_recent:
            self._recent = self._recent[-self._max_recent:]

    def debug(self, msg: str):
        self._logger.debug(msg)
        self._record("DEBUG", msg)

    def info(self, msg: str):
        self._logger.info(msg)
        self._record("INFO", msg)

    def warning(self, msg: str):
        self._logger.warning(msg)
        self._record("WARNING", msg)

    def error(self, msg: str):
        self._logger.error(msg)
        self._record("ERROR", msg)

    @property
    def recent(self) -> List[str]:
        return list(self._recent)


class SharedContext:
    """
    The service container passed to plugin.register().
    Plugins use this to access shared resources instead of global state.
    """

    def __init__(self, config: Config):
        self.config = config
        self.locale_code = detect_locale()
        self.locale = LocaleHelper(self.locale_code)
        self.logger = _Logger()
        self.events = _EventBus()
        self._app_root = _APP_ROOT

    def get_proxy(self, key: str) -> Optional[str]:
        """Resolve proxy: env var PROXY_<KEY> takes priority, then config."""
        env_key = f"PROXY_{key.upper()}"
        env_val = os.environ.get(env_key)
        if env_val is not None:
            if env_val.strip().lower() in ("", "none", "null", "false"):
                return None
            return env_val
        val = self.config.get(f"proxy.{key}")
        return val if val else None

    def locale_section(self, section: str) -> LocaleHelper:
        return LocaleHelper(self.locale_code, section)

    def get_app_root(self) -> Path:
        return self._app_root

    def get_plugin_dir(self, plugin_name: str) -> Path:
        d = self._app_root / "data" / plugin_name
        d.mkdir(parents=True, exist_ok=True)
        return d

    async def http_session(self):
        import aiohttp
        return aiohttp.ClientSession()
