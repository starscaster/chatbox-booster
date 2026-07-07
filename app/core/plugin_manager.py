"""
Plugin manager - discovers, loads, and manages plugin lifecycle.

Plugin sources (in priority order):
  1. Built-in plugins in app/plugins/<name>/
  2. User plugins in user_plugins/<name>/
  3. pip packages exposing the entry point group 'chatbox_booster.plugins'

Each plugin directory must contain a plugin.json manifest.
The entry module must export a register(ctx: SharedContext) -> list[callable] function.
"""
import importlib
import importlib.util
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from .dep_manager import ensure_deps, is_installed
from .shared_services import SharedContext


_APP_ROOT = Path(__file__).resolve().parent.parent.parent
_BUILTIN_PLUGINS_DIR = _APP_ROOT / "app" / "plugins"
_USER_PLUGINS_DIR = _APP_ROOT / "user_plugins"


@dataclass
class PluginInfo:
    """Metadata for a discovered plugin."""
    name: str
    version: str
    description: str
    source: str  # "builtin" | "user" | "pip"
    path: Path
    entry: str
    pip_dependencies: List[str] = field(default_factory=list)
    optional_pip_dependencies: List[str] = field(default_factory=list)
    config_schema: Dict[str, Any] = field(default_factory=dict)
    enabled: bool = True
    loaded: bool = False
    load_error: Optional[str] = None
    tools: List[Callable] = field(default_factory=list)


def _load_manifest(plugin_dir: Path) -> Optional[dict]:
    manifest_path = plugin_dir / "plugin.json"
    if not manifest_path.exists():
        return None
    with open(manifest_path, encoding="utf-8") as f:
        return json.load(f)


def _discover_directory(directory: Path, source: str) -> List[PluginInfo]:
    """Discover plugins in a directory."""
    plugins = []
    if not directory.exists():
        return plugins
    for item in sorted(directory.iterdir()):
        if not item.is_dir():
            continue
        if item.name.startswith("_") or item.name.startswith("."):
            continue
        manifest = _load_manifest(item)
        if not manifest:
            continue
        plugins.append(
            PluginInfo(
                name=manifest.get("name", item.name),
                version=manifest.get("version", "0.0.0"),
                description=manifest.get("description", ""),
                source=source,
                path=item,
                entry=manifest.get("entry", "plugin.py"),
                pip_dependencies=manifest.get("pip_dependencies", []),
                optional_pip_dependencies=manifest.get("optional_pip_dependencies", []),
                config_schema=manifest.get("config_schema", {}),
            )
        )
    return plugins


def _discover_pip_entry_points() -> List[PluginInfo]:
    """Discover plugins installed as pip packages via entry points."""
    plugins = []
    try:
        from importlib.metadata import entry_points
        eps = entry_points()
        group = "chatbox_booster.plugins"
        if hasattr(eps, "select"):
            group_eps = eps.select(group=group)
        else:
            group_eps = eps.get(group, [])
        for ep in group_eps:
            try:
                mod = ep.load()
                manifest = getattr(mod, "PLUGIN_MANIFEST", None)
                if not manifest:
                    continue
                plugins.append(
                    PluginInfo(
                        name=manifest.get("name", ep.name),
                        version=manifest.get("version", "0.0.0"),
                        description=manifest.get("description", ""),
                        source="pip",
                        path=Path(ep.value.split(":")[0].replace(".", "/")),
                        entry=manifest.get("entry", "plugin.py"),
                        pip_dependencies=manifest.get("pip_dependencies", []),
                        optional_pip_dependencies=manifest.get("optional_pip_dependencies", []),
                        config_schema=manifest.get("config_schema", {}),
                    )
                )
            except Exception:
                continue
    except Exception:
        pass
    return plugins


class PluginManager:
    """Manages plugin discovery, loading, and lifecycle."""

    def __init__(self, ctx: SharedContext):
        self.ctx = ctx
        self.plugins: Dict[str, PluginInfo] = {}
        self._loaded_modules: Dict[str, Any] = {}

    def discover(self) -> List[PluginInfo]:
        """Discover all available plugins from all sources."""
        all_plugins: Dict[str, PluginInfo] = {}
        for p in _discover_directory(_BUILTIN_PLUGINS_DIR, "builtin"):
            all_plugins[p.name] = p
        for p in _discover_directory(_USER_PLUGINS_DIR, "user"):
            if p.name not in all_plugins:
                all_plugins[p.name] = p
        for p in _discover_pip_entry_points():
            if p.name not in all_plugins:
                all_plugins[p.name] = p
        self.plugins = all_plugins
        return list(all_plugins.values())

    def is_enabled(self, name: str) -> bool:
        """Check if a plugin is enabled in config."""
        return self.ctx.config.get(f"plugins.{name}.enabled", True)

    def set_enabled(self, name: str, enabled: bool) -> None:
        """Enable/disable a plugin in config."""
        self.ctx.config.set(f"plugins.{name}.enabled", enabled)

    def check_dependencies(self, info: PluginInfo) -> tuple:
        """Check if a plugin's dependencies are met.

        Returns (all_met, missing_required, missing_optional).
        """
        missing_required = []
        for pkg in info.pip_dependencies:
            import_name = pkg.split("[")[0].split("=")[0].strip().replace("-", "_")
            if not is_installed(import_name):
                missing_required.append(pkg)
        missing_optional = []
        for pkg in info.optional_pip_dependencies:
            import_name = pkg.split("[")[0].split("=")[0].strip().replace("-", "_")
            if not is_installed(import_name):
                missing_optional.append(pkg)
        return (len(missing_required) == 0, missing_required, missing_optional)

    def load_plugin(self, info: PluginInfo) -> bool:
        """Load a single plugin. Returns True on success."""
        if info.loaded:
            return True
        if not info.enabled:
            return False

        # Check and install required dependencies
        all_met, missing_req, _ = self.check_dependencies(info)
        if not all_met:
            self.ctx.logger.info(
                f"Installing dependencies for plugin '{info.name}': {missing_req}"
            )
            dep_map = {}
            for pkg in missing_req:
                import_name = pkg.split("[")[0].split("=")[0].strip().replace("-", "_")
                dep_map[import_name] = pkg
            if not ensure_deps(dep_map):
                info.load_error = f"Failed to install dependencies: {missing_req}"
                self.ctx.logger.error(info.load_error)
                return False

        # Load the entry module
        entry_path = info.path / info.entry
        if not entry_path.exists():
            info.load_error = f"Entry file not found: {entry_path}"
            self.ctx.logger.error(info.load_error)
            return False

        try:
            # Add plugin directory to sys.path so relative imports work
            plugin_parent = str(info.path.parent)
            if plugin_parent not in sys.path:
                sys.path.insert(0, plugin_parent)

            # Import the plugin package (e.g. "search.plugin")
            pkg_name = info.path.name
            mod_name = f"{pkg_name}.plugin"

            # If already loaded, reload
            if mod_name in sys.modules:
                module = importlib.reload(sys.modules[mod_name])
            else:
                # First import the package __init__
                try:
                    importlib.import_module(pkg_name)
                except Exception:
                    pass  # __init__.py might be empty, that's fine
                module = importlib.import_module(mod_name)

            self._loaded_modules[info.name] = module

            register_fn = getattr(module, "register", None)
            if register_fn is None:
                info.load_error = "Module missing register() function"
                self.ctx.logger.error(info.load_error)
                return False

            tools = register_fn(self.ctx)
            if tools is None:
                tools = []
            info.tools = tools
            info.loaded = True
            self.ctx.logger.info(
                f"Plugin '{info.name}' loaded with {len(tools)} tool(s)"
            )
            return True
        except Exception as e:
            info.load_error = str(e)
            self.ctx.logger.error(f"Failed to load plugin '{info.name}': {e}")
            return False

    def load_all(self) -> Dict[str, List[Callable]]:
        """Load all enabled plugins. Returns {plugin_name: [tools]}."""
        result = {}
        for name, info in self.plugins.items():
            info.enabled = self.is_enabled(name)
            if not info.enabled:
                self.ctx.logger.info(f"Plugin '{name}' is disabled, skipping")
                continue
            if self.load_plugin(info):
                result[name] = info.tools
        return result

    def get_status(self) -> List[dict]:
        """Get status of all plugins for UI display."""
        statuses = []
        for name, info in self.plugins.items():
            all_met, missing_req, missing_opt = self.check_dependencies(info)
            statuses.append({
                "name": info.name,
                "version": info.version,
                "description": info.description,
                "source": info.source,
                "enabled": info.enabled,
                "loaded": info.loaded,
                "load_error": info.load_error,
                "deps_met": all_met,
                "missing_required": missing_req,
                "missing_optional": missing_opt,
                "tool_count": len(info.tools),
            })
        return statuses