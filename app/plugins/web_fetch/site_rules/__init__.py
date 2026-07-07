"""
Site-level content extraction rules.

Each site registers an entry in SITE_RULES with content/comment/skip/recommend selectors.
"""
from urllib.parse import urlparse

BILI_RULE = {
    "content_selectors": [
        '//*[@id="video_page_detail"]',
        '//*[contains(@class, "video-info-container")]',
        '//div[contains(@class, "video-desc")]',
        '//*[contains(@class, "video-toolbar")]',
    ],
    "comment_selectors": [
        '//*[contains(@class, "reply-list")]',
        '//*[@id="comment"]',
        '//*[contains(@class, "comment-container")]',
        '//*[contains(@class, "bb-comment")]',
    ],
    "skip_selectors": [
        '//*[contains(@class, "slide-ad")]',
        '//*[contains(@class, "ad-report")]',
        '//*[contains(@class, "side-bar")]',
        '//aside',
        '//*[contains(@class, "right-container")]',
        '//*[@id="multi_page"]',
    ],
    "recommend_selectors": [
        '//*[contains(@class, "video-page-special")]',
        '//*[contains(@class, "rec-list")]',
        '//*[contains(@class, "recommend")]',
        '//*[contains(@class, "related")]',
    ],
    "recommend_limit": 5,
    "comment_api": True,
}

SITE_RULES: dict[str, dict] = {
    "bilibili.com": BILI_RULE,
}


def detect_site(url: str) -> str | None:
    try:
        hostname = urlparse(url).hostname or ""
    except Exception:
        return None
    for domain in SITE_RULES:
        if domain in hostname:
            return domain
    return None