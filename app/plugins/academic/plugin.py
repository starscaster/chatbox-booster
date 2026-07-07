"""
Academic plugin — arXiv paper search and PDF text extraction.

Migrated from server.py, adapted to plugin framework.
"""
import asyncio
import io
import re
from typing import List



def register(ctx):
    arxiv_locale = ctx.locale_section("search_arxiv")
    pdf_locale = ctx.locale_section("search_pdf")

    async def arxiv_search(query: str, max_results: int = 5) -> str:
        """
        Search academic papers on arXiv.

        Args:
            query: Search keywords.
            max_results: Maximum results to return (default 5).
        """
        import aiohttp
        import xml.etree.ElementTree as ET

        url = "https://export.arxiv.org/api/query"
        search_query = f"all:{query}"
        params = {
            "search_query": search_query,
            "start": 0,
            "max_results": max_results,
            "sortBy": "relevance",
            "sortOrder": "descending",
        }
        timeout = aiohttp.ClientTimeout(total=30)

        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.get(url, params=params, proxy=None) as resp:
                    if resp.status != 200:
                        body = await resp.text()
                        return arxiv_locale.get("request_failed", code=resp.status, response=body[:200])
                    data = await resp.text()
                    if not data.strip().startswith("<?xml") and not data.strip().startswith("<feed"):
                        return arxiv_locale.get("non_xml_content", content=data[:200])
                    data = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", "", data)
                    root = ET.fromstring(data)
                    ns = {"atom": "http://www.w3.org/2005/Atom"}
                    results = []
                    for entry in root.findall("atom:entry", ns)[:max_results]:
                        title_el = entry.find("atom:title", ns)
                        title = title_el.text.strip() if title_el is not None and title_el.text else arxiv_locale.get("no_title")
                        summary_el = entry.find("atom:summary", ns)
                        summary = summary_el.text.strip() if summary_el is not None and summary_el.text else arxiv_locale.get("no_summary")
                        link_el = entry.find("atom:id", ns)
                        link = link_el.text.strip() if link_el is not None and link_el.text else "#"
                        published_el = entry.find("atom:published", ns)
                        published = published_el.text.strip() if published_el is not None and published_el.text else arxiv_locale.get("no_date")
                        summary = " ".join(summary.split())
                        results.append(
                            f"### {title}\n"
                            f"{arxiv_locale.get('date_label', date=published)}\n"
                            f"{arxiv_locale.get('link_label', link=link)}\n"
                            f"{arxiv_locale.get('summary_label', summary=summary[:200])}...\n"
                        )
                    if not results:
                        return arxiv_locale.get("no_results")
                    return f"{arxiv_locale.get('header')}\n" + "\n".join(results)
        except ET.ParseError as e:
            return arxiv_locale.get("xml_parse_error", error=str(e), content=data[:300] if "data" in dir() else "N/A")
        except Exception as e:
            return arxiv_locale.get("error", error=str(e))

    def _parse_pdf_page_selection(page_range: str, total_pages: int) -> List[int]:
        if total_pages <= 0:
            return []
        if not page_range or not page_range.strip():
            raise ValueError("page_range is required, for example: 1-10 or 22-32")
        selected_pages: List[int] = []
        seen = set()
        for raw_chunk in page_range.split(","):
            chunk = raw_chunk.strip()
            if not chunk:
                continue
            if "-" in chunk:
                start_text, end_text = chunk.split("-", 1)
                if not start_text.strip() or not end_text.strip():
                    raise ValueError(f"invalid page range: {chunk}")
                start = int(start_text.strip())
                end = int(end_text.strip())
            else:
                start = end = int(chunk)
            if start < 1 or end < 1:
                raise ValueError(f"page number must be >= 1: {chunk}")
            if start > end:
                raise ValueError(f"range start must be <= end: {chunk}")
            for page_num in range(max(start, 1), min(end, total_pages) + 1):
                if page_num not in seen:
                    seen.add(page_num)
                    selected_pages.append(page_num)
        if not selected_pages:
            raise ValueError(f"page range out of bounds: {page_range}")
        return selected_pages

    def _format_pdf_page_ranges(page_numbers: List[int]) -> str:
        if not page_numbers:
            return ""
        ranges = []
        start = page_numbers[0]
        end = page_numbers[0]
        for page_num in page_numbers[1:]:
            if page_num == end + 1:
                end = page_num
                continue
            ranges.append(f"{start}-{end}" if start != end else str(start))
            start = end = page_num
        ranges.append(f"{start}-{end}" if start != end else str(start))
        return ",".join(ranges)

    async def pdf_reader(pdf_url: str, page_range: str, timeout: int = 30) -> str:
        """
        Download and parse a PDF file, extracting text content.
        Suitable for arXiv PDF links or other public PDF documents.

        Args:
            pdf_url: URL of the PDF file.
            page_range: Page range, e.g. "1-10", "22-32", "1-3,8,10-12".
            timeout: Download timeout in seconds (default 30).
        """
        import aiohttp
        from pypdf import PdfReader

        try:
            async with asyncio.timeout(timeout):
                async with aiohttp.ClientSession() as session:
                    async with session.get(pdf_url, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
                        if resp.status != 200:
                            return pdf_locale.get("download_failed", code=resp.status)
                        pdf_data = await resp.read()
                        pdf_file = io.BytesIO(pdf_data)
                        reader = PdfReader(pdf_file)
                        total_pages = len(reader.pages)
                        selected_pages = _parse_pdf_page_selection(page_range, total_pages)
                        extracted_text = []
                        for page_num in selected_pages:
                            page = reader.pages[page_num - 1]
                            text = page.extract_text()
                            if text:
                                extracted_text.append(
                                    f"--- {pdf_locale.get('page_label', num=page_num)} ---\n{text.strip()}"
                                )
                        if not extracted_text:
                            return pdf_locale.get("no_text")
                        result = f"{pdf_locale.get('header')}\n"
                        result += f"**{pdf_locale.get('total_pages', count=total_pages)}**\n"
                        result += f"**{pdf_locale.get('requested_range', value=page_range.strip())}**\n"
                        result += f"**{pdf_locale.get('actual_range', value=_format_pdf_page_ranges(selected_pages))}**\n"
                        result += f"**{pdf_locale.get('pages_read', count=len(selected_pages))}**\n\n"
                        result += "\n\n".join(extracted_text)
                        return result
        except ValueError as e:
            return pdf_locale.get("invalid_page_range", error=str(e))
        except asyncio.TimeoutError:
            return pdf_locale.get("timeout", timeout=timeout)
        except aiohttp.ClientError as e:
            return pdf_locale.get("network_error", error=str(e))
        except Exception as e:
            return pdf_locale.get("error", error=str(e))

    return [arxiv_search, pdf_reader]