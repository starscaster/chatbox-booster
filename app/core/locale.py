"""
Internationalization helper.

Loads locale JSON from the locale/ directory and provides formatted string lookups.
Detects system locale via Windows API, falls back to English.
"""
import json
from pathlib import Path
from typing import Dict, Optional


_APP_ROOT = Path(__file__).resolve().parent.parent.parent
_LOCALE_DIR = _APP_ROOT / "locale"
_cache: Dict[str, dict] = {}


def detect_locale() -> str:
    """Detect system locale. Returns 'zh' or 'en'."""
    try:
        import ctypes
        lang_id = ctypes.windll.kernel32.GetUserDefaultUILanguage()
        if (lang_id & 0x3FF) == 4:
            return "zh"
        return "en"
    except Exception:
        return "en"


def load_locale(locale_code: str) -> dict:
    """Load a full locale JSON file, with caching."""
    if locale_code in _cache:
        return _cache[locale_code]
    path = _LOCALE_DIR / f"{locale_code}.json"
    if not path.exists():
        path = _LOCALE_DIR / "en.json"
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    _cache[locale_code] = data
    return data


def load_section(locale_code: str, section: str) -> dict:
    """Load a single section from a locale file."""
    return load_locale(locale_code).get(section, {})


class LocaleHelper:
    """Convenience class for accessing locale strings with formatting."""

    def __init__(self, locale_code: Optional[str] = None, section: Optional[str] = None):
        self._code = locale_code or detect_locale()
        self._section = section
        if section:
            self._data = load_section(self._code, section)
        else:
            self._data = load_locale(self._code)

    def get(self, key: str, **kwargs) -> str:
        text = self._data.get(key, key)
        if kwargs:
            try:
                return text.format(**kwargs)
            except (KeyError, IndexError):
                return text
        return text

    @property
    def code(self) -> str:
        return self._code
