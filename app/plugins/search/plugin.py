"""
Search plugin — DuckDuckGo and Serper web search with quality scoring.

Migrated from server.py, adapted to the plugin framework.
"""
import asyncio
import os
from typing import List

from .quality_evaluator import evaluate_ddgs_quality, ai_evaluate_quality


def register(ctx):
    """Register search tools with the MCP server."""
    ddgs_locale = ctx.locale_section("search_ddgs")
    serper_locale = ctx.locale_section("search_serper")

    async def DDGS_web_search(
        query: str,
        max_results: int = 5,
        region: str = "wt-wt",
        min_quality_score: float = 30.0,
        ai_evaluate: bool = False,
        intent: str = "",
    ) -> str:
        """
        DuckDuckGo web search with broad coverage and intelligent result ranking.

        Args:
            query: Search keywords. Use natural language search queries.
            max_results: Maximum number of results to return (default 5).
            region: Region-language code, e.g. "zh-cn" (default "wt-wt" for global).
            min_quality_score: Filter results below this score (default 30).
            ai_evaluate: Enable LLM-based content filtering (default False).
            intent: When ai_evaluate is True, describe evaluation focus.
        """
        from ddgs import DDGS

        def _search_sync():
            ddgs_proxy = ctx.get_proxy("ddgs")
            with DDGS(proxy=ddgs_proxy) as ddgs:
                actual_request_count = max_results * 2 + 2
                return list(ddgs.text(
                    query=query,
                    region=region,
                    safesearch="off",
                    max_results=actual_request_count,
                ))

        try:
            results = await asyncio.to_thread(_search_sync)
            if not results:
                return ddgs_locale.get("no_results")

            overall_assessment = ""
            if ai_evaluate:
                min_quality_score = 50.0
                ai_scored, overall_assessment = ai_evaluate_quality(results, query, intent, ctx)
                scored_results = []
                for s in ai_scored:
                    if s["index"] < len(results):
                        item = results[s["index"]]
                        scored_results.append({
                            "title": item.get("title", ddgs_locale.get("no_title")),
                            "link": item.get("href", "#"),
                            "body": item.get("body", ddgs_locale.get("no_body")),
                            "quality_score": float(s["quality_score"]),
                            "result_type": s["result_type"],
                            "original_index": s["index"],
                        })
            else:
                scored_results = []
                for i, item in enumerate(results):
                    title = item.get("title", ddgs_locale.get("no_title"))
                    link = item.get("href", "#")
                    body = item.get("body", ddgs_locale.get("no_body"))
                    quality_score, result_type = evaluate_ddgs_quality(title, body, link, query, ctx)
                    scored_results.append({
                        "title": title,
                        "link": link,
                        "body": body,
                        "quality_score": float(quality_score),
                        "result_type": result_type,
                        "original_index": i,
                    })

            scored_results.sort(key=lambda x: x["quality_score"], reverse=True)
            qualified_results = [r for r in scored_results if r["quality_score"] > min_quality_score]
            top_results = qualified_results[:max_results]

            formatted_results = []
            for idx, item in enumerate(top_results, 1):
                type_label = (
                    ddgs_locale.get("type_specific")
                    if item["result_type"] == "specific_article"
                    else ddgs_locale.get("type_aggregation")
                )
                if item["quality_score"] >= 80.0:
                    quality_badge = ddgs_locale.get("quality_label_high")
                elif item["quality_score"] >= 60.0:
                    quality_badge = ddgs_locale.get("quality_label_medium")
                else:
                    quality_badge = ddgs_locale.get("quality_label_low")

                formatted_results.append(
                    f"### {idx}. [{item['original_index']}] {item['title']}\n"
                    f"{quality_badge} | {type_label} | {ddgs_locale.get('quality_score')}: {item['quality_score']}\n"
                    f"{ddgs_locale.get('link_label', link=item['link'])}\n"
                    f"{item['body']}\n"
                )

            if not formatted_results:
                return overall_assessment + ddgs_locale.get("no_qualified")

            output = f"{ddgs_locale.get('header')}\n"
            if ai_evaluate and overall_assessment:
                output += f"> **{ddgs_locale.get('overall_label')}**: {overall_assessment}\n\n"
            output += f"*{ddgs_locale.get('filter_summary', total=len(results), top=len(top_results))}*\n\n"
            output += "\n".join(formatted_results)
            return output
        except Exception as e:
            return ddgs_locale.get("error", error=str(e))

    async def Serper_web_search(query: str, max_results: int = 5) -> str:
        """
        Google search via Serper API. Backup engine, requires API key.

        Args:
            query: Search keywords.
            max_results: Maximum results to return (default 5).
        """
        import aiohttp

        api_key = os.getenv("SERPER_API_KEY") or ctx.config.get("api.serper.api_key")
        if not api_key:
            return serper_locale.get("missing_key")

        url = os.getenv("SERPER_API_URL") or ctx.config.get(
            "api.serper.url", "https://google.serper.dev/search"
        )
        headers = {"X-API-KEY": api_key, "Content-Type": "application/json"}
        payload = {"q": query, "num": max_results}

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload, headers=headers) as resp:
                    if resp.status != 200:
                        return serper_locale.get("request_failed", code=resp.status)
                    data = await resp.json()
                    if "organic" not in data:
                        return serper_locale.get("no_results")
                    results = []
                    for item in data.get("organic", [])[:max_results]:
                        title = item.get("title", serper_locale.get("no_title"))
                        link = item.get("link", "#")
                        snippet = item.get("snippet", serper_locale.get("no_snippet"))
                        results.append(
                            f"### {title}\n{serper_locale.get('link_label', link=link)}\n{snippet}\n"
                        )
                    if not results:
                        return serper_locale.get("no_results")
                    return f"{serper_locale.get('header')}\n" + "\n".join(results)
        except Exception as e:
            return serper_locale.get("error", error=str(e))

    return [DDGS_web_search, Serper_web_search]