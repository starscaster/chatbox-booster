"""
REST API handlers for the management web UI.

Provides endpoints for:
- GET  /api/status     - server status and plugin list
- GET  /api/config     - full config
- POST /api/config     - update config values
- GET  /api/plugins    - plugin status list
- POST /api/plugins/{name}/toggle - enable/disable plugin
- GET  /api/logs       - recent log entries
- GET  /api/mcp-config - MCP client config JSON
"""
import json
import os
import sys
import re
import subprocess
import asyncio
import requests
from datetime import datetime
from pathlib import Path
from aiohttp import web

from ..core.dep_manager import install_packages, is_installed


def _get_ctx(request):
    return request.app["ctx"]


def _get_pm(request):
    return request.app["pm"]


def _get_restart_marker(request):
    ctx = _get_ctx(request)
    return ctx.get_data_root() / "manager" / ".needs_restart"


def _write_restart_marker(ctx, plugin_name, action):
    marker = ctx.get_data_root() / "manager" / ".needs_restart"
    marker.parent.mkdir(parents=True, exist_ok=True)
    info = {
        "plugin": plugin_name,
        "action": action,
        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }
    marker.write_text(json.dumps(info, ensure_ascii=False), encoding="utf-8")


async def handle_index(request):
    """Serve the main HTML page."""
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    return web.FileResponse(os.path.join(static_dir, "index.html"))


async def handle_status(request):
    ctx = _get_ctx(request)
    marker = _get_restart_marker(request)
    needs_restart = None
    if marker.exists():
        try:
            needs_restart = json.loads(marker.read_text(encoding="utf-8"))
        except Exception:
            needs_restart = {"plugin": "unknown", "action": "changed", "timestamp": ""}
    return web.json_response({
        "locale": ctx.locale_code,
        "app_root": str(ctx.get_app_root()),
        "python_exe": sys.executable,
        "logs": ctx.logger.recent[-20:],
        "needs_restart": needs_restart,
    })


async def handle_config_get(request):
    ctx = _get_ctx(request)
    return web.json_response(ctx.config.raw)


async def handle_config_set(request):
    ctx = _get_ctx(request)
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)
    for key, value in body.items():
        ctx.config.set(key, value)
    return web.json_response({"ok": True})


async def handle_plugins(request):
    pm = _get_pm(request)
    return web.json_response(pm.get_status())


async def handle_plugin_toggle(request):
    pm = _get_pm(request)
    ctx = _get_ctx(request)
    name = request.match_info["name"]
    try:
        body = await request.json()
        enabled = body.get("enabled", True)
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)
    pm.set_enabled(name, enabled)
    action = "enabled" if enabled else "disabled"
    _write_restart_marker(ctx, name, action)
    return web.json_response({"ok": True, "name": name, "enabled": enabled, "needs_restart": True})


async def handle_install_deps(request):
    """Install missing pip dependencies for a plugin."""
    pm = _get_pm(request)
    ctx = _get_ctx(request)
    name = request.match_info["name"]
    if name not in pm.plugins:
        return web.json_response({"error": f"plugin '{name}' not found"}, status=404)
    info = pm.plugins[name]
    all_met, missing_req, missing_opt = pm.check_dependencies(info)
    to_install = list(missing_req) + list(missing_opt)
    if not to_install:
        return web.json_response({"ok": True, "message": "all dependencies already installed", "installed": []})
    ctx.logger.info(f"Installing dependencies for plugin '{name}': {to_install}")
    success = install_packages(to_install, quiet=False)
    if success:
        ctx.logger.info(f"Successfully installed: {to_install}")
        return web.json_response({"ok": True, "installed": to_install})
    else:
        return web.json_response({"ok": False, "error": f"pip install failed for: {to_install}"}, status=500)


async def handle_logs(request):
    ctx = _get_ctx(request)
    return web.json_response({"logs": ctx.logger.recent})


async def handle_mcp_config(request):
    """Generate MCP client config JSON for copy-paste."""
    ctx = _get_ctx(request)
    server_path = ctx.get_app_root() / "server.py"
    python_exe = request.query.get("preview") or ctx.config.get("runtime.python_path") or sys.executable
    config = {
        "mcpServers": {
            "chatbox-booster": {
                "command": python_exe.replace("\\", "/"),
                "args": [str(server_path).replace("\\", "/")],
                "env": {},
            }
        }
    }
    return web.json_response(config)


def _looks_like_path(s: str) -> bool:
    """Heuristic: a conda env name can't contain path separators or colon."""
    return "\\" in s or "/" in s or ":" in s


async def handle_python_env(request):
    """Detect available Python environments on this system."""
    ctx = _get_ctx(request)
    app_root = ctx.get_app_root()

    configured = ctx.config.get("runtime.python_path") or ""
    detections = []

    # 1. Current Python (always present)
    detections.append({
        "path": sys.executable,
        "source": "current",
        "label": "Current interpreter",
    })

    # 2. Embedded runtime (from installer prep)
    embedded = app_root / "runtime" / "python" / "python.exe"
    if embedded.exists():
        detections.append({
            "path": str(embedded),
            "source": "embedded",
            "label": "Embedded runtime",
        })

    # 3. venv / .venv in project root
    for venv_dir in (".venv", "venv", "env", ".env"):
        venv_python = app_root / venv_dir / "Scripts" / "python.exe"
        if venv_python.exists():
            detections.append({
                "path": str(venv_python),
                "source": "venv",
                "label": f"Venv ({venv_dir})",
            })

    # 4. Active conda environment
    conda_prefix = os.environ.get("CONDA_PREFIX", "")
    if conda_prefix:
        conda_python = Path(conda_prefix) / "python.exe"
        if conda_python.exists():
            detections.append({
                "path": str(conda_python),
                "source": "conda",
                "label": f"Conda ({Path(conda_prefix).name})",
            })

    # 5. pipx installations
    pipx_python = app_root.parent / "pipx" / "venvs" / "chatbox-booster" / "Scripts" / "python.exe"
    if pipx_python.exists():
        detections.append({
            "path": str(pipx_python),
            "source": "pipx",
            "label": "pipx",
        })

    # 6. Windows Python Launcher — py --list
    try:
        result = await asyncio.to_thread(
            lambda: subprocess.run(
                ["py", "--list"], capture_output=True, text=True, timeout=10,
            )
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                line = line.strip()
                m = re.match(r"-V:(\d+\.\d+)\s+\*?\s+", line)
                if not m:
                    continue
                ver = m.group(1)
                try:
                    r2 = await asyncio.to_thread(
                        lambda v=ver: subprocess.run(
                            ["py", f"-{v}", "-c", "import sys; print(sys.executable)"],
                            capture_output=True, text=True, timeout=10,
                        )
                    )
                    if r2.returncode == 0:
                        path = r2.stdout.strip()
                        if path:
                            detections.append({
                                "path": path,
                                "source": "py_launcher",
                                "label": f"Python {ver} (py launcher)",
                            })
                except Exception:
                    pass
    except FileNotFoundError:
        pass  # py launcher not installed on this system
    except Exception:
        pass

    # 7. Conda environments — conda env list
    try:
        result = await asyncio.to_thread(
            lambda: subprocess.run(
                ["conda", "env", "list"], capture_output=True, text=True, timeout=30,
            )
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                line = line.strip()
                if not line or line.startswith("#") or line.startswith(">"):
                    continue
                parts = line.split()
                if not parts:
                    continue

                if len(parts) >= 2:
                    # Format: <name> [*] <path>
                    env_path = parts[-1]
                    env_name = parts[0]
                elif len(parts) == 1 and _looks_like_path(parts[0]):
                    env_path = parts[0]
                    env_name = Path(env_path).name
                else:
                    continue

                python_path = Path(env_path) / "python.exe"
                if python_path.exists():
                    detections.append({
                        "path": str(python_path),
                        "source": "conda",
                        "label": f"Conda {env_name}",
                    })
    except FileNotFoundError:
        pass  # conda not installed on this system
    except Exception:
        pass

    return web.json_response({
        "current": sys.executable,
        "configured": configured or None,
        "detections": detections,
    })


async def handle_python_env_test(request):
    """Test a given Python interpreter: version and core imports."""
    ALL_DEPS = [
        ("fastmcp", True), ("aiohttp", True),  # core
        ("ddgs", True), ("requests", True), ("tiktoken", True),   # search
        ("curl_cffi", True), ("lxml", True),  # web_fetch
        ("pypdf", True),  # academic
        ("patchright", False),  # optional (browser_engine disabled by default)
    ]
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)

    python_path = (body.get("path") or "").strip()
    if not python_path:
        return web.json_response({"ok": False, "error": "path is required"}, status=400)
    if not Path(python_path).exists():
        return web.json_response({"ok": False, "error": f"File not found: {python_path}"})

    # Step 1: --version check
    try:
        r1 = await asyncio.to_thread(
            lambda: subprocess.run(
                [python_path, "--version"], capture_output=True, text=True, timeout=15,
            )
        )
        if r1.returncode != 0:
            return web.json_response({"ok": False, "error": f"Not a valid Python: {r1.stderr.strip() or r1.stdout.strip()}"})
        version = r1.stdout.strip() or r1.stderr.strip()
    except FileNotFoundError:
        return web.json_response({"ok": False, "error": "File not found"})
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)})

    # Step 2: test core imports needed by the MCP server
    test_code = (
        "import sys, json\n"
        "results = {'version': sys.version, 'executable': sys.executable, 'imports': {}, 'errors': []}\n"
        "for mod in ('fastmcp', 'aiohttp', 'ddgs', 'requests', 'tiktoken', 'curl_cffi', 'lxml', 'pypdf', 'patchright'):\n"
        "    try:\n"
        "        __import__(mod)\n"
        "        results['imports'][mod] = True\n"
        "    except ImportError as e:\n"
        "        results['imports'][mod] = False\n"
        "        results['errors'].append(f'{mod}: {e}')\n"
        "print(json.dumps(results, ensure_ascii=False))\n"
    )
    try:
        r2 = await asyncio.to_thread(
            lambda: subprocess.run(
                [python_path, "-c", test_code], capture_output=True, text=True, timeout=30,
            )
        )
        if r2.returncode != 0:
            return web.json_response({
                "ok": True,
                "version": version,
                "core_imports": {},
                "all_core_ok": False,
                "errors": [f"test script failed: {r2.stderr.strip()[:200]}"],
            })
        for line in reversed(r2.stdout.strip().splitlines()):
            line = line.strip()
            if line.startswith("{"):
                info = json.loads(line)
                break
        else:
            info = {}
    except Exception as e:
        return web.json_response({"ok": True, "version": version, "core_imports": {}, "all_core_ok": False, "errors": [str(e)]})

    required = info.get("imports", {})
    all_core_ok = all(required.get(m) for m in ("fastmcp", "aiohttp"))
    missing_required = [m for m, req in ALL_DEPS if req and not required.get(m)]
    has_warnings = any(not required.get(m) for m, req in ALL_DEPS if not req)

    return web.json_response({
        "ok": True,
        "version": version,
        "python_exe": info.get("executable", python_path),
        "core_imports": info.get("imports", {}),
        "all_core_ok": all_core_ok,
        "all_required_ok": len(missing_required) == 0,
        "missing_required": missing_required,
        "has_warnings": has_warnings,
        "errors": info.get("errors", []),
    })


async def handle_python_env_install_deps(request):
    """Install project dependencies into a specified Python interpreter."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "invalid JSON"}, status=400)

    python_path = (body.get("path") or "").strip()
    if not python_path:
        return web.json_response({"ok": False, "error": "path is required"}, status=400)
    if not Path(python_path).exists():
        return web.json_response({"ok": False, "error": f"File not found: {python_path}"})

    deps = body.get("deps") or [
        "fastmcp", "aiohttp",
        "ddgs", "requests", "tiktoken",
        "curl_cffi", "lxml",
        "pypdf",
    ]

    try:
        result = await asyncio.to_thread(
            lambda: subprocess.run(
                [python_path, "-m", "pip", "install"] + deps + ["-q"],
                capture_output=True, text=True, timeout=300,
            )
        )
        if result.returncode == 0:
            return web.json_response({"ok": True, "installed": deps})
        else:
            err = result.stderr.strip()[:500] or result.stdout.strip()[:500]
            return web.json_response({"ok": False, "error": err}, status=500)
    except subprocess.TimeoutExpired:
        return web.json_response({"ok": False, "error": "pip install timed out (300s)"}, status=504)
    except Exception as e:
        return web.json_response({"ok": False, "error": str(e)}, status=500)


async def handle_test_api(request):
    """Test an API endpoint with the provided config (without saving)."""
    try:
        body = await request.json()
    except Exception:
        return web.json_response({"ok": False, "message": "invalid JSON"}, status=400)

    api_type = body.get("type")
    cfg = body.get("config", {})
    url = (cfg.get("url") or "").strip()
    api_key = (cfg.get("api_key") or "").strip()
    model = (cfg.get("model") or "").strip()

    if not url or not api_key:
        return web.json_response({"ok": False, "message": "URL or API key is empty"})

    if not url.startswith("http"):
        url = "https://" + url

    try:
        timeout = float(cfg.get("timeout", 10))
    except (ValueError, TypeError):
        timeout = 10.0

    try:
        if api_type == "rerank":
            headers = {"Authorization": f"Bearer {api_key}"}
            payload = {"model": model, "query": "test", "documents": ["hello"]}

            def _do():
                return requests.post(url, json=payload, timeout=timeout, headers=headers)

            response = await asyncio.to_thread(_do)

            if response.status_code == 200:
                data = response.json()
                results = data.get("results", [])
                return web.json_response({
                    "ok": True,
                    "status_code": response.status_code,
                    "message": f"Rerank API connected, model responded with {len(results)} result(s)",
                    "detail": "",
                })
            else:
                return web.json_response({
                    "ok": False,
                    "status_code": response.status_code,
                    "message": f"HTTP {response.status_code}",
                    "detail": response.text[:500],
                })

        elif api_type == "ai_eval":
            headers = {"Authorization": f"Bearer {api_key}"}
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": "Hi"}],
                "max_tokens": 5,
                "temperature": 0,
            }

            def _do():
                return requests.post(url, json=payload, timeout=timeout, headers=headers)

            response = await asyncio.to_thread(_do)

            if response.status_code == 200:
                data = response.json()
                choices = data.get("choices", [])
                return web.json_response({
                    "ok": True,
                    "status_code": response.status_code,
                    "message": f"AI eval API connected, got {len(choices)} choice(s)",
                    "detail": "",
                })
            else:
                return web.json_response({
                    "ok": False,
                    "status_code": response.status_code,
                    "message": f"HTTP {response.status_code}",
                    "detail": response.text[:500],
                })

        elif api_type == "serper":
            headers = {"X-API-KEY": api_key}
            payload = {"q": "test", "num": 1}

            def _do():
                return requests.post(url, json=payload, timeout=timeout, headers=headers)

            response = await asyncio.to_thread(_do)

            if response.status_code == 200:
                return web.json_response({
                    "ok": True,
                    "status_code": response.status_code,
                    "message": "Serper API connected",
                    "detail": "",
                })
            else:
                return web.json_response({
                    "ok": False,
                    "status_code": response.status_code,
                    "message": f"HTTP {response.status_code}",
                    "detail": response.text[:500],
                })

        else:
            return web.json_response({"ok": False, "message": f"Unknown API type: {api_type}"})

    except requests.exceptions.Timeout:
        return web.json_response({"ok": False, "message": f"Request timed out after {timeout}s"})
    except requests.exceptions.ConnectionError:
        return web.json_response({"ok": False, "message": f"Connection error: could not reach {url}"})
    except Exception as e:
        return web.json_response({"ok": False, "message": f"Error: {str(e)[:200]}"})


def setup_routes(app):
    app.router.add_get("/", handle_index)
    app.router.add_get("/api/status", handle_status)
    app.router.add_get("/api/config", handle_config_get)
    app.router.add_post("/api/config", handle_config_set)
    app.router.add_post("/api/test-api", handle_test_api)
    app.router.add_get("/api/plugins", handle_plugins)
    app.router.add_post("/api/plugins/{name}/toggle", handle_plugin_toggle)
    app.router.add_post("/api/plugins/{name}/install-deps", handle_install_deps)
    app.router.add_get("/api/logs", handle_logs)
    app.router.add_get("/api/mcp-config", handle_mcp_config)
    app.router.add_get("/api/python-env", handle_python_env)
    app.router.add_post("/api/python-env/test", handle_python_env_test)
    app.router.add_post("/api/python-env/install-deps", handle_python_env_install_deps)
    # Static files
    app.router.add_static("/static", path=str(app["static_dir"]), name="static")
