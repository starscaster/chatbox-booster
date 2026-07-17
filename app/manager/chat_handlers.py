"""
Chat handler ? LLM proxy with MCP tool-calling support.

Streams LLM responses back to the browser via Server-Sent Events (SSE).
When the LLM requests tool calls, executes them locally via the MCP server
and feeds results back for another reasoning round.
"""
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List

from aiohttp import web


_APP_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_APP_ROOT) not in sys.path:
    sys.path.insert(0, str(_APP_ROOT))


def _get_ctx(request):
    return request.app["ctx"]

def _get_pm(request):
    return request.app["pm"]

def _get_mcp(request):
    return request.app["mcp"]


async def _extract_tool_definitions(mcp):
    """Get MCP tools and convert to OpenAI function-calling format."""
    tools = await mcp.list_tools()
    openai_tools = []
    for t in tools:
        params = t.parameters if hasattr(t, "parameters") else {}
        if params is None:
            params = {"type": "object", "properties": {}}
        openai_tools.append({
            "type": "function",
            "function": {
                "name": t.name,
                "description": t.description or "",
                "parameters": params,
            }
        })
    return openai_tools


async def _call_tool_locally(mcp, tool_name: str, arguments: dict) -> str:
    """Execute an MCP tool and return its text result."""
    try:
        result = await mcp.call_tool(tool_name, arguments)
        if hasattr(result, "content"):
            parts = []
            for c in result.content:
                if hasattr(c, "text"):
                    parts.append(c.text)
                elif hasattr(c, "data"):
                    import base64
                    parts.append(base64.b64encode(c.data).decode())
            return "\n".join(parts) if parts else str(result)
        return str(result)
    except Exception as e:
        return f"[Tool error: {e}]"


def _call_llm_api(url, headers, body):
    """Make a synchronous HTTP POST to the LLM API. Returns parsed JSON."""
    import requests
    response = requests.post(url, json=body, headers=headers, timeout=120, stream=True)
    response.raise_for_status()
    return response


async def handle_chat_models(request):
    """GET /api/chat/models ? list available models based on config."""
    ctx = _get_ctx(request)
    api_url = ctx.config.get("chat.api_url", "https://api.deepseek.com/v1/models")
    api_key = ctx.config.get("chat.api_key", "")
    if not api_key:
        return web.json_response({"models": []})
    try:
        import requests
        headers = {"Authorization": f"Bearer {api_key}"}
        resp = requests.get(api_url, headers=headers, timeout=10)
        if resp.status_code == 200:
            data = resp.json()
            models = data.get("data", [])
            return web.json_response({"models": [m.get("id", "") for m in models]})
        return web.json_response({"models": [], "error": f"HTTP {resp.status_code}"})
    except Exception as e:
        return web.json_response({"models": [], "error": str(e)})


async def handle_chat_config(request):
    """GET /api/chat/config ? return chat-specific config for the frontend."""
    ctx = _get_ctx(request)
    pm = _get_pm(request)
    chat_cfg = {
        "api_url": ctx.config.get("chat.api_url", "https://api.deepseek.com/v1/chat/completions"),
        "model": ctx.config.get("chat.model", "deepseek-v4-flash"),
        "system_prompt": ctx.config.get("chat.system_prompt", "You are a helpful assistant with access to web search and other tools."),
        "temperature": ctx.config.get("chat.temperature", 0.6),
        "max_tokens": ctx.config.get("chat.max_tokens", 64000),
        "has_api_key": bool(ctx.config.get("chat.api_key", "")),
    }
    return web.json_response(chat_cfg)


async def handle_chat_send(request):
    """POST /api/chat/message ? stream LLM response with tool-calling via SSE."""
    ctx = _get_ctx(request)
    pm = _get_pm(request)
    mcp = _get_mcp(request)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid JSON"}, status=400)

    messages = body.get("messages", [])
    if not messages:
        return web.json_response({"error": "no messages"}, status=400)

    # Config
    api_url = ctx.config.get("chat.api_url", "https://api.deepseek.com/v1/chat/completions")
    api_key = ctx.config.get("chat.api_key", "")
    model = body.get("model", ctx.config.get("chat.model", "deepseek-v4-flash"))
    temperature = body.get("temperature", ctx.config.get("chat.temperature", 0.6))
    max_tokens = body.get("max_tokens", ctx.config.get("chat.max_tokens", 64000))
    system_prompt = body.get("system_prompt", ctx.config.get(
        "chat.system_prompt",
        "You are a helpful assistant with access to web search and other tools."
    ))

    if not api_key:
        return web.json_response({"error": "no API key configured"}, status=400)

    # Build tool definitions
    tools = await _extract_tool_definitions(mcp)

    # Build full message list with system prompt
    full_messages = [{"role": "system", "content": system_prompt}] + messages

    # SSE streaming response
    response = web.StreamResponse()
    response.content_type = "text/event-stream"
    response.charset = "utf-8"
    response.headers["Cache-Control"] = "no-cache"
    response.headers["X-Accel-Buffering"] = "no"
    await response.prepare(request)

    async def sse_send(event_type, data):
        payload = json.dumps({"type": event_type, **data}, ensure_ascii=False)
        await response.write(f"data: {payload}\n\n".encode("utf-8"))

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    try:
        import aiohttp

        max_rounds = 5  # prevent infinite tool-calling loops

        for round_num in range(max_rounds):
            request_body = {
                "model": model,
                "messages": full_messages,
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            }
            if tools:
                request_body["tools"] = tools

            accumulated_content = ""
            tool_calls = []

            async with aiohttp.ClientSession() as session:
                async with session.post(api_url, json=request_body, headers=headers, timeout=aiohttp.ClientTimeout(total=120)) as resp:
                    if resp.status != 200:
                        error_text = await resp.text()
                        await sse_send("error", {"error": f"LLM API error (HTTP {resp.status}): {error_text[:500]}"})
                        await response.write(b"event: done\ndata: {}\n\n")
                        return response

                    async for line in resp:
                        line = line.decode("utf-8").strip()
                        if not line or line.startswith(":"):
                            continue
                        if line.startswith("data: "):
                            line = line[6:]
                        if line == "[DONE]":
                            break
                        try:
                            chunk = json.loads(line)
                        except json.JSONDecodeError:
                            continue

                        choices = chunk.get("choices", [])
                        if not choices:
                            continue
                        delta = choices[0].get("delta", {})

                        # Content streaming
                        content_delta = delta.get("content", "")
                        if content_delta:
                            accumulated_content += content_delta
                            await sse_send("content", {"text": content_delta})

                        # Tool calls
                        tc_delta = delta.get("tool_calls", [])
                        for tc in tc_delta:
                            idx = tc.get("index", 0)
                            while len(tool_calls) <= idx:
                                tool_calls.append({"id": "", "function": {"name": "", "arguments": ""}})
                            if tc.get("id"):
                                tool_calls[idx]["id"] = tc["id"]
                            fn = tc.get("function", {})
                            if fn.get("name"):
                                tool_calls[idx]["function"]["name"] += fn["name"]
                            if fn.get("arguments"):
                                tool_calls[idx]["function"]["arguments"] += fn["arguments"]

                        # Check for finish
                        finish_reason = choices[0].get("finish_reason")
                        if finish_reason and finish_reason != "tool_calls":
                            break

            # If no tool calls, we are done
            if not tool_calls:
                break

            # Execute tool calls
            for tc in tool_calls:
                tool_name = tc["function"]["name"]
                try:
                    tool_args = json.loads(tc["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    tool_args = {}

                await sse_send("tool_call", {
                    "name": tool_name,
                    "arguments": tool_args,
                })

                result_text = await _call_tool_locally(mcp, tool_name, tool_args)

                await sse_send("tool_result", {
                    "name": tool_name,
                    "result": result_text[:8000],
                })

                # Add to message history for next round
                full_messages.append({
                    "role": "assistant",
                    "content": accumulated_content or None,
                    "tool_calls": [
                        {
                            "id": tc["id"],
                            "type": "function",
                            "function": {
                                "name": tc["function"]["name"],
                                "arguments": tc["function"]["arguments"],
                            }
                        }
                    ],
                })
                full_messages.append({
                    "role": "tool",
                    "tool_call_id": tc["id"],
                    "content": result_text[:8000],
                })

        await response.write(b"event: done\ndata: {}\n\n")
        return response

    except asyncio.TimeoutError:
        await sse_send("error", {"error": "Request timed out"})
        await response.write(b"event: done\ndata: {}\n\n")
        return response
    except Exception as e:
        await sse_send("error", {"error": str(e)})
        await response.write(b"event: done\ndata: {}\n\n")
        return response


def setup_chat_routes(app):
    """Register chat API routes."""
    app.router.add_get("/api/chat/config", handle_chat_config)
    app.router.add_get("/api/chat/models", handle_chat_models)
    app.router.add_post("/api/chat/message", handle_chat_send)
