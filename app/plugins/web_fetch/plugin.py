"""
Web fetch plugin — fetches webpages via curl_cffi with browser fallback.

Migrated from MCPtool_0427.py, adapted to plugin framework.
"""
import asyncio
from typing import List

from .text_extractor import (
    extract_text_from_html,
    _extract_text_from_json,
    _count_tokens,
    _truncate_by_tokens,
    _clean_reference_noise,
)
from .browser_fallback import is_spa_shell, browser_fallback_fetch
from .site_rules import SITE_RULES, detect_site as _detect_site


_BROWSER_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.7",
    "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8,en-US;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Cache-Control": "max-age=0",
    "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
_IMPERSONATE_CHAIN = ["chrome131", "chrome124", "firefox133"]


def _is_network_error(msg: str) -> bool:
    msg_lower = msg.lower()
    for kw in ("could not resolve host", "connection refused", "connection reset",
               "network is unreachable", "host is unreachable", "failed to connect",
               "ssl", "certificate", "timed out"):
        if kw in msg_lower:
            return True
    return False


def register(ctx):
    locale = ctx.locale_section("webpage_fetch")
    app_root = ctx.get_app_root()
    data_root = ctx.get_data_root()

    async def fetch_webpage_tool(
        url: str,
        timeout: int = 20,
        max_tokens: int = 15000,
        text_only: bool = True,
    ) -> str:
        """
        Fetch and extract content from an HTTP/HTTPS webpage.

        Args:
            url: Webpage URL (must start with http:// or https://).
            timeout: Request timeout in seconds (default 20).
            max_tokens: Maximum tokens to return (default 15000).
            text_only: True = plain text only. False = include links, metadata, comments.
                       For community content, set to False. For official/authoritative pages, True.
        """
        if not url.startswith(("http://", "https://")):
            return locale.get("invalid_url", url=url)

        async def _enrich_with_comments(text: str) -> str:
            if text_only:
                return text
            site = _detect_site(url)
            if not (site and SITE_RULES.get(site, {}).get("comment_api")):
                return text
            if site == "bilibili.com":
                try:
                    from .bilibili_wbi import fetch_comments
                    comments = await fetch_comments(url, max_replies=20, timeout=timeout)
                    if comments:
                        text = text.strip() + "\n\n---\n\n" + comments
                except Exception:
                    pass
            return text

        from curl_cffi import requests as curl_requests

        last_error = ""
        raw_body = ""
        resp_status = 0

        for impersonate_target in _IMPERSONATE_CHAIN:
            try:
                async with curl_requests.AsyncSession() as session:
                    resp = await session.get(
                        url,
                        impersonate=impersonate_target,
                        headers=_BROWSER_HEADERS,
                        timeout=timeout,
                    )
                    resp_status = resp.status_code
                    raw_body = resp.text

                    if resp_status == 403:
                        last_error = locale.get("403_browser_fallback", url=url)
                        browser_text = await browser_fallback_fetch(
                            url=url,
                            raw_html=raw_body,
                            extracted_text="",
                            timeout=timeout,
                            text_only=text_only,
                            max_tokens=max_tokens,
                            locale=locale,
                            app_root=app_root,
                            force=True,
                        )
                        if browser_text:
                            browser_text = await _enrich_with_comments(browser_text)
                            return browser_text
                        continue

                    if resp_status != 200:
                        return locale.get("status_not_200", url=url, code=resp_status, reason=resp.reason)

                    break
            except Exception as e:
                last_error = str(e)
                if _is_network_error(last_error):
                    break
                continue
            except asyncio.TimeoutError:
                return locale.get("timeout", timeout=timeout)
        else:
            if last_error:
                return last_error
            return locale.get("parse_error", type="403", message="all attempts failed")

        content_type = resp.headers.get("Content-Type", "")
        is_json = "application/json" in content_type
        if not is_json and "text/html" not in content_type and "text/plain" not in content_type:
            return locale.get("unsupported_content_type", url=url, code=resp_status, type=content_type)

        if is_json:
            import json
            try:
                data = json.loads(raw_body)
                text = _extract_text_from_json(data, text_only=text_only)
            except json.JSONDecodeError:
                text = raw_body
        else:
            text = extract_text_from_html(raw_body, text_only=text_only, url=url, locale=locale)

        # SPA fallback
        _needs_fallback = is_spa_shell(raw_body, text or "") and ("text/html" in content_type)
        if _needs_fallback:
            browser_result = await browser_fallback_fetch(
                url=url,
                raw_html=raw_body,
                extracted_text=text or "",
                timeout=timeout,
                text_only=text_only,
                max_tokens=max_tokens,
                locale=locale,
                app_root=app_root,
                force=False,
            )
            if browser_result:
                browser_result = await _enrich_with_comments(browser_result)
                return browser_result

        if not text:
            return locale.get("empty_content", url=url, code=resp_status)

        if text_only:
            text = _clean_reference_noise(text)

        text = await _enrich_with_comments(text)

        tokens = _count_tokens(text)
        if tokens < 4000:
            result = locale.get("success_header", code=resp_status)
            result += f"\n\n{text}"
            return result
        if tokens <= max_tokens:
            result = locale.get("token_length", tokens=tokens, length=len(text))
            result += f"\n\n{text}"
            return result

        truncated_text = _truncate_by_tokens(text, max_tokens)
        trunc_tokens = _count_tokens(truncated_text)
        pct = round((1 - trunc_tokens / tokens) * 100)
        result = locale.get("token_truncated", tokens=trunc_tokens, pct=pct, length=len(truncated_text))
        result += f"\n\n{truncated_text}"
        return result

    return [fetch_webpage_tool]
