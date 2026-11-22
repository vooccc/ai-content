# -*- coding: utf-8 -*-
"""搜狗微信搜索：按关键词搜公众号文章（标题/摘要/发布时间/来源公众号/链接）。"""
from __future__ import annotations

import re
import asyncio
import random
import datetime as _dt
from urllib.parse import quote

import httpx

_UAS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Edg/123.0.0.0 Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
]


def _ua() -> str:
    return random.choice(_UAS)


def _strip_tags(html: str) -> str:
    text = re.sub(r"<[^>]+>", "", html or "")
    for a, b in (("&nbsp;", " "), ("&amp;", "&"), ("&lt;", "<"),
                 ("&gt;", ">"), ("&quot;", '"'), ("&#39;", "'")):
        text = text.replace(a, b)
    return re.sub(r"\s+", " ", text).strip()


def _parse(html: str, limit: int) -> list[dict]:
    out: list[dict] = []
    m = re.search(r'<ul[^>]*class="news-list"[^>]*>(.*?)</ul>', html, re.S)
    if not m:
        return out
    scope = m.group(1)
    for li in re.findall(r"<li[^>]*>(.*?)</li>", scope, re.S):
        if len(out) >= limit:
            break
        a = re.search(r'<h3[^>]*>\s*<a[^>]*href="([^"]*)"[^>]*>(.*?)</a>', li, re.S)
        if not a:
            continue
        url = a.group(1).replace("&amp;", "&")
        if url.startswith("/"):
            url = "https://weixin.sogou.com" + url
        title = _strip_tags(a.group(2))
        if not title:
            continue
        sm = re.search(r'<p[^>]*class="txt-info"[^>]*>(.*?)</p>', li, re.S)
        summary = _strip_tags(sm.group(1)) if sm else ""
        src = (re.search(r'<span[^>]*class="all-time-y2"[^>]*>(.*?)</span>', li, re.S)
               or re.search(r'<a[^>]*class="account"[^>]*>(.*?)</a>', li, re.S))
        source = _strip_tags(src.group(1)) if src else ""
        date_text = ""
        ts_val = None
        m_tc = re.search(r"timeConvert\('(\d{10})'\)", li)
        if m_tc:
            ts_val = int(m_tc.group(1))
        else:
            for cand in re.findall(r"(\d{10})", li):
                v = int(cand)
                if 1420000000 <= v <= 2050000000:
                    ts_val = v
                    break
        if ts_val:
            try:
                date_text = _dt.datetime.fromtimestamp(ts_val).strftime("%Y-%m-%d")
            except Exception:
                pass
        out.append({"title": title, "url": url, "summary": summary,
                    "source": source, "date": date_text})
    return out


async def search_wechat(query: str, num: int = 8) -> list[dict]:
    query = (query or "").strip()
    if not query:
        return []
    num = max(1, min(num, 30))
    base_headers = {
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://weixin.sogou.com/",
    }
    out: list[dict] = []
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            try:
                await c.get("https://weixin.sogou.com/", headers={**base_headers, "User-Agent": _ua()})
            except Exception:
                pass
            pages = (num + 9) // 10
            for page in range(1, pages + 1):
                if len(out) >= num:
                    break
                url = (f"https://weixin.sogou.com/weixin?query={quote(query)}"
                       f"&type=2&page={page}&ie=utf8&s_from=input&_sug_=n")
                r = await c.get(url, headers={**base_headers, "User-Agent": _ua()})
                if r.status_code != 200:
                    break
                parsed = _parse(r.text, num - len(out))
                if not parsed:
                    break
                out.extend(parsed)
                if page < pages:
                    await asyncio.sleep(0.5 + random.random())
    except Exception:
        pass
    return out[:num]
