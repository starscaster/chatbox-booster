"""
Configuration manager with dot-notation access.

Reads from config.json (falling back to config.example.json on first run),
supports environment variable overrides, and persists changes back to disk.
"""
import json
import os
import shutil
from pathlib import Path
from typing import Any, Optional


_APP_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_DIR = _APP_ROOT / "config"
_CONFIG_FILE = _CONFIG_DIR / "config.json"
_EXAMPLE_FILE = _CONFIG_DIR / "config.example.json"


def ensure_config_exists() -> Path:
    """Copy config.example.json to config.json if it doesn't exist yet."""
    if not _CONFIG_FILE.exists():
        if _EXAMPLE_FILE.exists():
            shutil.copy(_EXAMPLE_FILE, _CONFIG_FILE)
            print(
                f"Created default config.json from config.example.json. "
                f"Please edit {_CONFIG_FILE} before starting the server.",
                flush=True,
            )
        else:
            raise FileNotFoundError(
                f"Missing {_CONFIG_FILE.name} and no template {_EXAMPLE_FILE.name}"
            )
    return _CONFIG_FILE


class Config:
    """Dot-notation config reader/writer backed by JSON."""

    def __init__(self, path: Optional[Path] = None):
        self._path = path or _CONFIG_FILE
        self._data: dict = {}
        self.reload()

    def reload(self) -> None:
        if self._path.exists():
            with open(self._path, encoding="utf-8") as f:
                self._data = json.load(f)
        else:
            self._data = {}

    def save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with open(self._path, "w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def get(self, dotted_key: str, default: Any = None) -> Any:
        """Get value by dot-notation key, e.g. config.get('proxy.ddgs')."""
        env_key = "PROXY_" + dotted_key.upper().replace(".", "_")
        env_val = os.environ.get(env_key)
        if env_val is not None:
            if env_val.strip().lower() in ("", "none", "null", "false"):
                return default
            return env_val

        parts = dotted_key.split(".")
        cur = self._data
        for part in parts:
            if isinstance(cur, dict) and part in cur:
                cur = cur[part]
            else:
                return default
        return cur

    def set(self, dotted_key: str, value: Any) -> None:
        """Set value by dot-notation key and persist to disk."""
        parts = dotted_key.split(".")
        cur = self._data
        for part in parts[:-1]:
            if part not in cur or not isinstance(cur[part], dict):
                cur[part] = {}
            cur = cur[part]
        cur[parts[-1]] = value
        self.save()

    def get_section(self, dotted_key: str) -> dict:
        val = self.get(dotted_key, {})
        return val if isinstance(val, dict) else {}

    @property
    def raw(self) -> dict:
        return self._data

    @property
    def path(self) -> Path:
        return self._path
