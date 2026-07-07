"""
Text extraction from HTML content.

Migrated from MCPtool_0427.py, containing the HTMLParser and lxml-based
extraction logic, site rules integration, and token-based truncation.
"""
import json
import re
from html.parser import HTMLParser
from pathlib import Path

from .site_rules import SITE_RULES, detect_site as _detect_site


_TOKENIZER = None


def _get_tokenizer():
    global _TOKENIZER
    if _TOKENIZER is None:
        import tiktoken
        _TOKENIZER = tiktoken.get_encoding("cl100k_base")
    return _TOKENIZER


def _count_tokens(text: str) -> int:
    return len(_get_tokenizer().encode(text))


def _truncate_by_tokens(text: str, max_tokens: int) -> str:
    encoder = _get_tokenizer()
    token_ids = encoder.encode(text)
    if len(token_ids) <= max_tokens:
        return text
    return encoder.decode(token_ids[:max_tokens])


SAFE_REMOVE_PATTERNS = [
    re.compile(r"^\[\d+\]$"),
    re.compile(r"^\(\d+\)$"),
    re.compile(r"^\d+\.$"),
    re.compile(r"^Fig\.\s*\d+$"),
    re.compile(r"^Table\s*\d+$"),
]


def _clean_reference_noise(text: str) -> str:
    words = text.split()
    cleaned: list[str] = []
    for w in words:
        core = w.rstrip(".,;:!?)")
        if any(p.match(core) for p in SAFE_REMOVE_PATTERNS):
            suff = w[len(core):]
            if suff:
                cleaned.append(suff)
            continue
        cleaned.append(w)
    result = " ".join(cleaned)
    result = re.sub(r"\s([.,;:!?)])", r"\1", result)
    result = re.sub(r"[,;]\s*[,;]", ",", result)
    return result


_JSON_TEXT_KEYS = {"content", "text", "title", "description", "body", "summary",
                   "message", "own_text", "excerpt_title", "excerpt", "subject",
                   "name", "question_title", "answer_content", "headline"}
_JSON_SKIP_KEYS = {
    "id", "type", "state", "url", "href", "source_pin_id",
    "created", "updated", "is_deleted", "self_create",
    "view_permission", "comment_permission", "can_top", "is_top",
    "is_admin_close_repin", "admin_closed_comment",
    "meet_reaction_guide_conditions",
    "like_count", "comment_count", "repin_count", "reaction_count",
    "favorite_count", "favlists_count", "page_view_count", "voteup_count",
    "thumbnail", "width", "height", "is_watermark", "watermark_url",
    "original_url", "is_gif", "is_long", "text_link_type", "fold_type",
    "content_html", "url_token", "avatar_url", "avatar_url_template",
    "badge", "badge_v2", "user_type", "is_org", "is_advertiser",
}


def _strip_html_from_text(text: str) -> str:
    if not re.search(r"<[^>]+>", text):
        return text
    return re.sub(r"<[^>]+>", "", text)


def _dedup_texts(texts: list[str]) -> list[str]:
    if len(texts) <= 1:
        return texts
    result: list[str] = []
    for t in texts:
        tn = re.sub(r"\s+", "", t)
        if len(tn) < 8:
            continue
        dup = False
        for i, existing in enumerate(result):
            en = re.sub(r"\s+", "", existing)
            if tn == en:
                dup = True
                break
            if len(tn) > len(en) and en in tn:
                result[i] = t
                dup = True
                break
            if len(en) >= len(tn) and tn in en:
                dup = True
                break
        if not dup:
            result.append(t)
    return result


def _extract_text_from_json(data, text_only: bool = True) -> str:
    def _walk(obj, depth=0):
        if depth > 20:
            return
        if isinstance(obj, str):
            if len(obj.strip()) >= 8:
                yield _strip_html_from_text(obj)
        elif isinstance(obj, dict):
            extracted_any = False
            for key in _JSON_TEXT_KEYS:
                if key in obj:
                    val = obj[key]
                    if isinstance(val, str) and len(val.strip()) >= 8:
                        extracted_any = True
                        yield _strip_html_from_text(val)
                    elif isinstance(val, list):
                        extracted_any = True
                        for item in val:
                            yield from _walk(item, depth + 1)
                    elif isinstance(val, dict):
                        extracted_any = True
                        yield from _walk(val, depth + 1)
            if not extracted_any:
                for key, val in obj.items():
                    if key not in _JSON_SKIP_KEYS:
                        yield from _walk(val, depth + 1)
        elif isinstance(obj, list):
            for item in obj:
                yield from _walk(item, depth + 1)

    texts = _dedup_texts(list(_walk(data)))
    if not texts:
        return ""
    return "\n\n".join(texts)


_VOID_TAGS = {"meta", "link", "br", "hr", "img", "input", "area", "base", "col",
              "embed", "param", "source", "track", "wbr"}

HEADER_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
NEWLINE_TAGS = {"p", "br", "li", "div", "tr", "blockquote"}

CONTENT_SELECTORS = [
    '//article[contains(@class, "markdown-body")]',
    '//*[contains(@class, "markdown-body")]',
    "//article",
    "//main",
    '//*[@role="main"]',
    '//*[contains(@class, "post-content")]',
    '//*[contains(@class, "entry-content")]',
    '//*[contains(@class, "article-content")]',
    '//*[contains(@class, "content")]',
]
IGNORE_CONTAINER = './/*[@id="readme"]//*[contains(@class, "markdown-body")]'
COMMENT_SELECTORS = [
    '//*[@id="comments"]',
    '//*[contains(@class, "comments-area")]',
    '//*[contains(@class, "comment-list")]',
    '//*[contains(@class, "comment-section")]',
    '//section[contains(@class, "comments")]',
    '//div[contains(@class, "comments")]',
    '//*[@id="disqus_thread"]',
]
SKIP_CLASS_KEYWORDS = ["sidebar", "aside", "recommend", "related", "hot"]


class _TextExtractor(HTMLParser):
    def __init__(self, text_only: bool = False):
        super().__init__()
        self._text_chunks: list[str] = []
        self._skip_tags = {"script", "style", "noscript", "head", "meta", "link", "title"}
        self._skip_depth = 0
        self._text_only = text_only
        self._in_link = False
        self._link_href = ""
        self._link_text_chunks: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self._skip_tags:
            if tag in _VOID_TAGS:
                return
            self._skip_depth += 1
            return
        if tag == "a" and self._skip_depth == 0:
            if not self._text_only:
                attrs_dict = dict(attrs)
                self._link_href = attrs_dict.get("href", "").strip()
            self._in_link = True
            self._link_text_chunks = []

    def handle_endtag(self, tag):
        if tag in self._skip_tags:
            if tag in _VOID_TAGS:
                return
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "a":
            if self._skip_depth == 0 and self._link_href:
                link_text = " ".join(self._link_text_chunks).strip()
                if link_text:
                    self._text_chunks.append(f"[{link_text}]({self._link_href})")
                else:
                    self._text_chunks.append(f"<{self._link_href}>")
            elif self._skip_depth == 0:
                self._text_chunks.extend(self._link_text_chunks)
            self._in_link = False
            self._link_href = ""
            self._link_text_chunks = []
            return
        if tag in ("p", "br", "li", "h1", "h2", "h3", "h4", "h5", "h6", "div", "tr", "blockquote"):
            self._text_chunks.append("\n")
        elif tag == "td":
            self._text_chunks.append(" | ")

    def handle_data(self, data):
        if self._skip_depth > 0:
            return
        stripped = data.strip()
        if stripped:
            if self._in_link:
                self._link_text_chunks.append(stripped)
            else:
                self._text_chunks.append(stripped)

    def get_text(self) -> str:
        return " ".join(self._text_chunks)


def _apply_generic_skip(tree, container, has_matched_container: bool):
    if has_matched_container:
        return
    for keyword in SKIP_CLASS_KEYWORDS:
        for el in tree.xpath(f'//*[contains(@class, "{keyword}")]'):
            if el.getparent() is not None:
                try:
                    el.getparent().remove(el)
                except Exception:
                    pass


def _extract_page_metadata(tree, locale) -> str:
    meta_parts: list[str] = []
    title_els = tree.xpath("//title")
    title_text = ""
    if title_els:
        title_text = (title_els[0].text or "").strip()
        if title_text:
            meta_parts.append(f"**{locale.get('meta_title')}**: {title_text}")
    desc_els = tree.xpath('//meta[@name="description"]/@content')
    if desc_els and desc_els[0].strip():
        meta_parts.append(f"**{locale.get('meta_description')}**: {desc_els[0].strip()}")
    kw_els = tree.xpath('//meta[@name="keywords"]/@content')
    if kw_els and kw_els[0].strip():
        meta_parts.append(f"**{locale.get('meta_keywords')}**: {kw_els[0].strip()}")
    og_title = tree.xpath('//meta[@property="og:title"]/@content')
    if og_title and og_title[0].strip() and og_title[0].strip() != title_text:
        meta_parts.append(f"**{locale.get('meta_og_title')}**: {og_title[0].strip()}")
    og_desc = tree.xpath('//meta[@property="og:description"]/@content')
    if og_desc and og_desc[0].strip():
        meta_parts.append(f"**{locale.get('meta_og_description')}**: {og_desc[0].strip()}")
    og_site = tree.xpath('//meta[@property="og:site_name"]/@content')
    if og_site and og_site[0].strip():
        meta_parts.append(f"**{locale.get('meta_site')}**: {og_site[0].strip()}")
    og_type = tree.xpath('//meta[@property="og:type"]/@content')
    if og_type and og_type[0].strip():
        meta_parts.append(f"**{locale.get('meta_type')}**: {og_type[0].strip()}")
    pub_time = tree.xpath('//meta[@property="article:published_time"]/@content')
    if pub_time and pub_time[0].strip():
        meta_parts.append(f"**{locale.get('meta_published')}**: {pub_time[0].strip()}")
    mod_time = tree.xpath('//meta[@property="article:modified_time"]/@content')
    if mod_time and mod_time[0].strip():
        meta_parts.append(f"**{locale.get('meta_modified')}**: {mod_time[0].strip()}")
    author_els = tree.xpath('//meta[@property="article:author"]/@content | //meta[@name="author"]/@content')
    if author_els and author_els[0].strip():
        meta_parts.append(f"**{locale.get('meta_author')}**: {author_els[0].strip()}")
    canonical = tree.xpath('//link[@rel="canonical"]/@href')
    if canonical and canonical[0].strip():
        meta_parts.append(f"**{locale.get('meta_canonical')}**: {canonical[0].strip()}")
    time_els = tree.xpath("//time[@datetime]")
    for t in time_els[:3]:
        dt = (t.get("datetime") or "").strip()
        txt = "".join(t.itertext()).strip()
        if dt:
            meta_parts.append(
                f"**{locale.get('meta_time')}**: {txt} ({dt})" if txt else f"**{locale.get('meta_time')}**: {dt}"
            )
    if meta_parts:
        return "\n".join(meta_parts) + "\n\n---\n\n"
    return ""


def _extract_comments(tree, main_container, locale, custom_selectors=None) -> str:
    selectors = custom_selectors or COMMENT_SELECTORS
    for selector in selectors:
        elements = tree.xpath(selector)
        for el in elements:
            if main_container is not None:
                if el is main_container:
                    continue
                try:
                    is_inside = False
                    for ancestor in el.iterancestors():
                        if ancestor is main_container:
                            is_inside = True
                            break
                    if is_inside:
                        continue
                except Exception:
                    pass
            text = _tree_to_text(el)
            if len(text.strip()) > 50:
                return f"## {locale.get('meta_comments_header')}\n\n{text.strip()}"
    return ""


def _find_content_container(tree, custom_selectors=None):
    selectors = custom_selectors or CONTENT_SELECTORS
    for selector in selectors:
        elements = tree.xpath(selector)
        for el in elements:
            if el.tag == "main":
                return el
            if el.tag == "article":
                return el
            text = (el.text or "") + "".join(el.xpath(".//text()"))
            if len(text.strip()) > 200:
                if not el.xpath(IGNORE_CONTAINER):
                    return el
    return None


def _walk(node, parts, text_only: bool = False):
    if node.tag in ("script", "style", "noscript", "head", "meta", "link", "title", "nav"):
        return
    if node.tag == "a":
        if text_only:
            link_text = "".join(node.itertext()).strip()
            if link_text:
                parts.append(link_text)
        else:
            href = (node.get("href") or "").strip()
            link_text = "".join(node.itertext()).strip()
            if href:
                if link_text:
                    parts.append(f"[{link_text}]({href})")
                else:
                    parts.append(f"<{href}>")
            elif link_text:
                parts.append(link_text)
        tail = (node.tail or "").strip()
        if tail and node.tag not in ("html", "body"):
            parts.append(tail)
        return
    if node.tag in HEADER_TAGS:
        parts.append("\n")
    text = (node.text or "").strip()
    if text and node.tag not in ("html", "body"):
        parts.append(text)
    for child in node:
        tag = child.tag if hasattr(child, "tag") else None
        if tag in NEWLINE_TAGS:
            parts.append("\n")
        elif tag == "td":
            parts.append(" | ")
        _walk(child, parts, text_only)
    if node.tag in HEADER_TAGS:
        parts.append("\n")
    tail = (node.tail or "").strip()
    if tail and node.tag not in ("html", "body"):
        parts.append(tail)


def _tree_to_text(node, text_only: bool = False) -> str:
    parts = []
    _walk(node, parts, text_only)
    raw = "".join(parts)
    raw = re.sub(r"[ \t]{2,}", " ", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()


def lxml_extract_text(html_text: str, text_only: bool = False, url: str = "", locale=None) -> str:
    from lxml import html as lxml_html
    from lxml.etree import ParseError
    try:
        tree = lxml_html.fromstring(html_text)
    except ParseError:
        return ""

    site = _detect_site(url) if url else None
    site_rule = SITE_RULES.get(site) if site else None

    if site_rule and site_rule.get("content_selectors"):
        effective_selectors = site_rule["content_selectors"] + CONTENT_SELECTORS
    else:
        effective_selectors = CONTENT_SELECTORS

    container = _find_content_container(tree, effective_selectors)
    has_matched = container is not None

    if container is None:
        body = tree.xpath("//body")
        container = body[0] if body else tree

    recommend_blocks: list[str] = []
    if site_rule and site_rule.get("recommend_selectors"):
        rec_limit = site_rule.get("recommend_limit", 5)
        for rec_sel in site_rule["recommend_selectors"]:
            for el in tree.xpath(rec_sel):
                rec_text = _tree_to_text(el, text_only=text_only)
                if rec_text.strip():
                    chunks = [c.strip() for c in rec_text.split("\n\n") if c.strip()]
                    if len(chunks) > rec_limit:
                        chunks = chunks[:rec_limit]
                        rec_text = "\n\n".join(chunks)
                    recommend_blocks.append(rec_text)
                try:
                    p = el.getparent()
                    if p is not None:
                        p.remove(el)
                except Exception:
                    pass

    if site_rule and site_rule.get("skip_selectors"):
        for skip_sel in site_rule["skip_selectors"]:
            for el in tree.xpath(skip_sel):
                try:
                    p = el.getparent()
                    if p is not None:
                        p.remove(el)
                except Exception:
                    pass

    _apply_generic_skip(tree, container, has_matched)
    text = _tree_to_text(container, text_only=text_only)

    if recommend_blocks:
        rec_appendix = "\n\n---\n\n" + "\n\n---\n\n".join(recommend_blocks)
        text = text.strip() + rec_appendix

    if not text_only:
        has_comment_api = site_rule and site_rule.get("comment_api")
        if has_comment_api:
            pass
        elif site_rule and site_rule.get("comment_selectors"):
            if locale:
                comment_text = _extract_comments(tree, container, locale, site_rule["comment_selectors"])
            else:
                comment_text = ""
            if comment_text:
                text = text.strip() + "\n\n---\n\n" + comment_text
        else:
            if locale:
                comment_text = _extract_comments(tree, container, locale)
            else:
                comment_text = ""
            if comment_text:
                text = text.strip() + "\n\n---\n\n" + comment_text
        if locale:
            metadata = _extract_page_metadata(tree, locale)
            if metadata:
                text = metadata + text

    return text.strip()


def extract_text_from_html(html: str, text_only: bool = False, url: str = "", locale=None) -> str:
    text = lxml_extract_text(html, text_only=text_only, url=url, locale=locale)
    if text:
        return text
    extractor = _TextExtractor(text_only=text_only)
    try:
        extractor.feed(html)
    except Exception:
        return html
    raw = extractor.get_text()
    raw = re.sub(r"[ \t]{2,}", " ", raw)
    raw = re.sub(r"\n{3,}", "\n\n", raw)
    return raw.strip()