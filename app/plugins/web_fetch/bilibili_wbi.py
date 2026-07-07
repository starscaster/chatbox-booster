"""
Bilibili WBI signing and comment API module.

Migrated from _bilibili_wbi.py with no functional changes.
"""
import asyncio
import hashlib
import re
import time
from datetime import datetime
from urllib.parse import quote


MIXIN_KEY_ENC_TAB = (
    46, 47, 18, 2, 53, 8, 23, 32, 15, 50, 10, 31, 58, 3, 45, 35,
    27, 43, 5, 49, 33, 9, 42, 19, 29, 28, 14, 39, 12, 38, 41, 13,
    37, 48, 7, 16, 24, 55, 40, 61, 26, 17, 0, 1, 60, 51, 30, 4,
    22, 25, 54, 21, 56, 59, 6, 63, 57, 62, 11, 36, 20, 34, 44, 52,
)

_wbi_keys: tuple[str, str] | None = None
_wbi_keys_ts: float = 0.0
_WBI_CACHE_TTL = 3600


async def _get_wbi_keys(session) -> tuple[str, str]:
    global _wbi_keys, _wbi_keys_ts
    import aiohttp
    now = time.time()
    if _wbi_keys and (now - _wbi_keys_ts) < _WBI_CACHE_TTL:
        return _wbi_keys
    try:
        async with session.get(
            "https://api.bilibili.com/x/web-interface/nav",
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            data = await resp.json()
    except Exception:
        return _wbi_keys if _wbi_keys else ("", "")
    wbi_img = data.get("data", {}).get("wbi_img", {})
    img_url = wbi_img.get("img_url", "")
    sub_url = wbi_img.get("sub_url", "")
    try:
        img_key = img_url.rsplit("/", 1)[-1].split(".")[0]
        sub_key = sub_url.rsplit("/", 1)[-1].split(".")[0]
    except Exception:
        return _wbi_keys if _wbi_keys else ("", "")
    _wbi_keys = (img_key, sub_key)
    _wbi_keys_ts = now
    return _wbi_keys


def _gen_mixin_key(img_key: str, sub_key: str) -> str:
    raw = img_key + sub_key
    return "".join(raw[i] for i in MIXIN_KEY_ENC_TAB)[:32]


def _sign_params(params: dict, mixin_key: str) -> tuple[str, int]:
    wts = int(time.time())
    params = {**params, "wts": str(wts)}
    parts = []
    for k in sorted(params.keys()):
        v = str(params[k])
        v = re.sub(r"[!'()*]", "", v)
        parts.append(f"{quote(k, safe='')}={quote(v, safe='')}")
    query = "&".join(parts)
    w_rid = hashlib.md5((query + mixin_key).encode()).hexdigest()
    return w_rid, wts


_VIEW_API = "https://api.bilibili.com/x/web-interface/view"


def extract_bv(url: str) -> str | None:
    m = re.search(r"/video/(BV[a-zA-Z0-9]+)", url)
    if m:
        return m.group(1)
    m = re.search(r"/(BV[a-zA-Z0-9]{10})", url)
    if m:
        return m.group(1)
    return None


async def _get_oid(session, bv: str, timeout: int = 10) -> str:
    import aiohttp
    try:
        async with session.get(
            f"{_VIEW_API}?bvid={bv}",
            timeout=aiohttp.ClientTimeout(total=timeout),
        ) as resp:
            data = await resp.json(content_type=None)
            aid = data.get("data", {}).get("aid")
            return str(aid) if aid else ""
    except Exception:
        return ""


_COMMENT_API = "https://api.bilibili.com/x/v2/reply/wbi/main"


async def fetch_comments(url: str, max_replies: int = 20, timeout: int = 10) -> str:
    import aiohttp
    bv = extract_bv(url)
    if not bv:
        return ""
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.bilibili.com/",
    }
    connector = aiohttp.TCPConnector(ssl=False)
    async with aiohttp.ClientSession(connector=connector, headers=headers) as session:
        oid = await _get_oid(session, bv, timeout=timeout)
        if not oid:
            return ""
        img_key, sub_key = await _get_wbi_keys(session)
        if not img_key or not sub_key:
            return ""
        mixin_key = _gen_mixin_key(img_key, sub_key)
        params = {
            "oid": str(oid), "type": "1", "mode": "3",
            "pagination_str": '{"offset":""}', "plat": "1", "web_location": "1315875",
        }
        w_rid, wts = _sign_params(params, mixin_key)
        params["w_rid"] = w_rid
        params["wts"] = str(wts)
        try:
            async with session.get(
                _COMMENT_API, params=params, timeout=aiohttp.ClientTimeout(total=timeout),
            ) as resp:
                data = await resp.json()
        except Exception:
            return ""
        if data.get("code") != 0:
            return ""
        replies = data.get("data", {}).get("replies") or []
        if not replies:
            return ""
        lines = []
        for reply in replies[:max_replies]:
            member = reply.get("member", {})
            uname = member.get("uname", "anonymous")
            content = reply.get("content", {}).get("message", "")
            like = reply.get("like", 0)
            ctime = reply.get("ctime", 0)
            time_str = datetime.fromtimestamp(ctime).strftime("%Y-%m-%d %H:%M") if ctime else ""
            if not content.strip():
                continue
            lines.append(f"{uname}({like} likes {time_str}): {content}")
        if not lines:
            return ""
        return "## Comments\n\n" + "\n\n".join(lines)