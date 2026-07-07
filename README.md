# Chatbox Booster v2

> MCP tool server that enhances AI chatboxes with web search, page fetching, PDF parsing, academic search, and user interaction dialogs.

## Architecture

Chatbox Booster v2 is a plugin-based MCP (Model Context Protocol) server:

- **Core** (`app/core/`) — thin framework: config, locale, shared services, plugin manager, MCP server entry
- **Plugins** (`app/plugins/`) — each feature domain is an independent plugin:
  - `search` — DuckDuckGo + Serper web search with quality scoring
  - `web_fetch` — webpage fetching with curl_cffi/lxml + optional browser fallback
  - `academic` — arXiv paper search + PDF text extraction
  - `interactive` — Tkinter confirmation/input/inquiry dialogs
  - `browser_engine` — optional Patchright browser service (not enabled by default)
- **Manager** (`app/manager/`) — system tray + local Web UI for configuration and plugin management
- **Installer** (`installer/`) — embedded Python packaging + Inno Setup script

## Quick Start (Development)

```bash
# Install dependencies
pip install -r requirements-dev.txt

# Run MCP server (for AI clients to connect)
python server.py

# Run management UI (separate process)
python manager_main.py
```

## MCP Client Configuration

After running the manager, copy the MCP config from the Web UI (`http://127.0.0.1:<port>?token=<token>`), or use:

```json
{
  "mcpServers": {
    "chatbox-booster": {
      "command": "<path-to-python>",
      "args": ["<path-to>/server.py"],
      "env": {}
    }
  }
}
```

## Plugin Development

Create a directory in `user_plugins/` with:

```
my_plugin/
  plugin.json    # manifest
  plugin.py      # entry module with register(ctx) function
  __init__.py    # empty
```

```python
# plugin.py
def register(ctx):
    async def my_tool(query: str) -> str:
        """My custom tool."""
        return ctx.locale.get("some_key")

    return [my_tool]
```

## Building the Installer

```bash
# 1. Prepare embedded Python runtime
python installer/prepare_runtime.py

# 2. Build installer with Inno Setup
iscc installer/build.iss
```

## Config

Edit `config/config.json` or use the Web UI. Key sections:
- `proxy` — DuckDuckGo/arXiv proxy settings
- `api` — Serper, Rerank, AI evaluation API keys
- `plugins` — enable/disable individual plugins
- `quality` — search result scoring weights
- `domains` — domain authority classifications