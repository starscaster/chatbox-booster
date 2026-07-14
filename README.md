# Chatbox Booster

> A plugin-based MCP (Model Context Protocol) server that adds web search, page fetching, PDF parsing, academic search, and user interaction dialogs to AI chat clients.

Chatbox Booster works as a stdio MCP server. Connect it to any MCP-compatible AI client (Chatbox, Claude Desktop, Cursor, etc.) and your assistant gains the ability to search the web, fetch and extract webpage content, read PDFs, search academic papers, and show interactive dialogs.

## Quick Start

### 1. Install

Download the latest installer from the [Releases](https://github.com/your-org/chatbox-booster/releases) page and run it. Two variants are available:

| Variant | Description |
|---------|-------------|
| Base | Core runtime only. Plugin dependencies auto-install on first use. |
| Full | All plugin dependencies pre-installed. Larger download, no auto-install wait. |

After installation, launch **Chatbox Booster Settings** from the Start Menu.

### 2. Configure

The system tray icon provides access to the management Web UI (opens in your default browser). From there you can:

- Enable/disable plugins (each feature is a toggle)
- Configure API keys (Serper, Rerank, and AI evaluation endpoints)
- Set up proxy (DuckDuckGo and arXiv proxy support)
- Select Python environment (choose which interpreter the MCP server uses)
- Copy MCP config (ready-to-use JSON for your AI client)

### 3. Connect your AI client

Copy the MCP configuration from the Web UI's **MCP Setup** tab and paste it into your AI client's MCP settings.

Example (your path and Python interpreter will differ):

```json
{
  "mcpServers": {
    "chatbox-booster": {
      "command": "C:\\Users\\You\\AppData\\Local\\ChatboxBooster\\runtime\\python\\python.exe",
      "args": ["C:\\Users\\You\\AppData\\Local\\ChatboxBooster\\server.py"],
      "env": {}
    }
  }
}
```

Once connected, your AI assistant will have access to all enabled tools.

## Tools

| Tool | Plugin | Description |
|------|--------|-------------|
| `DDGS_web_search` | search | DuckDuckGo web search with quality-based result ranking. Optional AI-powered evaluation for relevance filtering. |
| `Serper_web_search` | search | Google search via Serper API (requires API key). |
| `fetch_webpage_tool` | web_fetch | Fetch and extract content from any webpage. Handles SPAs and anti-scraping sites via automatic browser fallback. |
| `arxiv_search` | academic | Search academic papers on arXiv by relevance. |
| `pdf_reader` | academic | Download and extract text from PDF files with page range selection. |
| `interactive_dialog_UA` | interactive | Yes/No/Cancel confirmation dialog for sensitive operations. |
| `interactive_dialog_input` | interactive | Single-line text input dialog. |
| `interactive_dialog_inquiry` | interactive | Structured form dialog with auto-parsed questions and optional remarks. |
| `get_date` | built-in | Returns current system time (helps the AI stay time-aware). |
| `add` | built-in | Simple addition tool for testing MCP connectivity. |

## Plugins

Each feature domain is a self-contained plugin under `app/plugins/`:

- **search** - DuckDuckGo + Serper with quality scoring and optional AI reranking
- **web_fetch** - Webpage fetching via curl_cffi with automatic SPA/anti-scraping browser fallback
- **academic** - arXiv paper search and PDF text extraction
- **interactive** - Tkinter-based desktop dialogs (confirmation, text input, structured forms)
- **browser_engine** - Patchright/Playwright browser service (infrastructure for web_fetch fallback, no user-facing tools)

Plugins are **disabled by default**. Enable them from the Web UI. Most plugins auto-install their dependencies on first enable.

## Configuration

Configuration is managed through the Web UI. Key sections:

- **Proxy** - HTTP proxy settings for DuckDuckGo and arXiv
- **API Keys** - Serper, Rerank, and AI evaluation endpoints and credentials
- **Quality** - search result scoring weights and domain authority classification
- **Plugins** - enable/disable individual plugins
- **Playwright** - browser engine settings (headless mode, timeouts, concurrency)

Manual edits can also be made in `config/config.json` (auto-created from `config.example.json` on first run).

## Building from Source

```bash
# Clone the repository
git clone <repo-url>
cd chatbox-booster

# Install core dependencies
pip install -r requirements-core.txt

# For development, install all dependencies
pip install -r requirements-dev.txt

# Run the manager (system tray + Web UI)
python manager_main.py

# Build installer (requires Inno Setup)
python installer/prepare_runtime.py          # base variant
python installer/prepare_runtime.py --full   # full variant
iscc installer/build-base.iss
iscc installer/build-full.iss
```

## Plugin Development

Create a directory in `user_plugins/` with:

```
user_plugins/
  my_plugin/
    plugin.json    # manifest (name, version, dependencies, entry, etc.)
    plugin.py      # entry module with register(ctx) function
    __init__.py
```

```python
# my_plugin/plugin.py
def register(ctx):
    async def my_tool(query: str) -> str:
        """Describe what this tool does."""
        return f"You searched for: {query}"

    return [my_tool]
```

See any built-in plugin for a complete example.

## Project Structure

```
chatbox-booster/
  server.py            # MCP server entry point (stdin/stdout)
  manager_main.py      # Management UI entry point (tray + Web UI)
  app/
    core/              # Framework: config, locale, plugin manager, shared services
    manager/           # System tray, Web UI server, REST API
      static/          # Frontend (index.html, app.js, style.css)
    plugins/           # Built-in plugins
  config/
    config.example.json   # Default configuration template
  installer/           # Inno Setup scripts + runtime preparation
  locale/              # i18n strings (en.json, zh.json)
  user_plugins/        # User-installed custom plugins
  data/                # Runtime state (auto-created)
  logs/                # Application logs (auto-created)
```
