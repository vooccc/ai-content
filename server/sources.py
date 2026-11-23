# -*- coding: utf-8 -*-
"""稳定免费选题采集源：GitHub Trending / Hacker News / B站 / 微博热搜 / 科技 RSS / 搜狗微信。"""
from __future__ import annotations

import asyncio
import html
import math
import re
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional
from urllib.parse import quote_plus

import requests

from .wechat_search import search_wechat

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36"
)


class _RateLimiter:
    """源级冷却限流器，避免高频请求触发风控。"""

    def __init__(self, min_interval_sec: float):
        self.min_interval = min_interval_sec
        self._lock = threading.Lock()
        self._last_ts = 0.0

    def wait(self) -> None:
        with self._lock:
            now = time.monotonic()
            delta = self.min_interval - (now - self._last_ts)
            if delta > 0:
                time.sleep(delta)
            self._last_ts = time.monotonic()


_LIMITERS: Dict[str, _RateLimiter] = {
    "hackernews": _RateLimiter(0.4),
    "bilibili": _RateLimiter(1.2),
    "weibo": _RateLimiter(1.0),
    "wechat": _RateLimiter(1.8),
}


def _strip_html(text: str) -> str:
    no_script = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", text or "", flags=re.S | re.I)
    no_tags = re.sub(r"<[^>]+>", " ", no_script)
    cleaned = html.unescape(no_tags)
    return re.sub(r"\s+", " ", cleaned).strip()


def _is_ascii_term(s: str) -> bool:
    return bool(s) and all(ord(ch) < 128 for ch in s)


def fetch_github_trending(
    languages: List[str] | None = None,
    since: str = "daily",
    limit: int = 12,
) -> List[Dict[str, Any]]:
    """抓取 GitHub Trending 热门仓库。"""
    langs = languages if languages is not None else ["python", "typescript", ""]
    items: List[Dict[str, Any]] = []
    seen_urls: set[str] = set()
    for lang in langs:
        slug = quote_plus(lang.strip()) if lang.strip() else ""
        url = f"https://github.com/trending/{slug}?since={since}" if slug else f"https://github.com/trending?since={since}"
        try:
            r = requests.get(url, headers={"User-Agent": _UA}, timeout=12)
            if r.status_code != 200:
                continue
            body = r.text
        except Exception:
            continue

        articles = re.findall(r"<article\b[^>]*class=\"[^\"]*Box-row[^\"]*\"[^>]*>(.*?)</article>", body, flags=re.S | re.I)
        for block in articles:
            repo_m = re.search(r"<h2[^>]*>.*?<a[^>]*href=\"/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)\"", block, flags=re.S | re.I)
            if not repo_m:
                continue
            repo = repo_m.group(1).strip()
            repo_url = f"https://github.com/{repo}"
            if repo_url in seen_urls:
                continue
            seen_urls.add(repo_url)

            desc_m = re.search(r"<p\b[^>]*>(.*?)</p>", block, flags=re.S | re.I)
            desc = _strip_html(desc_m.group(1)) if desc_m else ""
            stars_m = re.search(r"([\d,]+)\s+stars\s+(?:today|this week|this month)", block, flags=re.I)
            stars_today = stars_m.group(1) if stars_m else ""
            lang_m = re.search(r'itemprop="programmingLanguage"[^>]*>(.*?)<', block, flags=re.S | re.I)
            prog_lang = _strip_html(lang_m.group(1)) if lang_m else (lang or "开源项目")

            summary_parts = [p for p in [desc, f"语言：{prog_lang}" if prog_lang else "", f"新增 {stars_today} stars" if stars_today else ""] if p]
            items.append({
                "source_type": "github_trending",
                "source_name": "GitHub Trending",
                "source_url": repo_url,
                "raw_title": f"{repo}：{desc[:50]}" if desc else repo,
                "raw_summary": " | ".join(summary_parts),
                "popularity": int(stars_today.replace(",", "")) if stars_today.replace(",", "").isdigit() else 0,
            })
            if len(items) >= limit:
                return items
    return items


def fetch_hackernews_topics(
    keywords: List[str],
    hours: int = 48,
    min_points: int = 15,
    limit_per_kw: int = 6,
) -> tuple[List[Dict[str, Any]], List[str]]:
    """通过 Hacker News Algolia 官方免费 API 抓近期高赞讨论（带 points 与评论数）。"""
    items: List[Dict[str, Any]] = []
    errors: List[str] = []
    seen_urls: set[str] = set()
    cutoff = int(time.time()) - max(6, hours) * 3600

    # HN 为英文社区，优先取 ASCII 关键词，若全中文则补通用 AI/Agent/solo founder 兜底词
    en_terms = [k.strip() for k in (keywords or []) if _is_ascii_term(k.strip())]
    if not en_terms:
        en_terms = ["AI Agent", "Claude Code", "MCP", "indie hacker", "LLM tool"]

    for kw in en_terms[:5]:
        _LIMITERS["hackernews"].wait()
        try:
            r = requests.get(
                "https://hn.algolia.com/api/v1/search",
                params={
                    "query": kw,
                    "tags": "story",
                    "hitsPerPage": max(limit_per_kw * 2, 10),
                    "numericFilters": f"created_at_i>{cutoff},points>{min_points}",
                },
                headers={"User-Agent": _UA},
                timeout=12,
            )
            r.raise_for_status()
            hits = (r.json() or {}).get("hits") or []
        except Exception as e:
            errors.append(f"HackerNews[{kw}]: {e}")
            continue

        added_here = 0
        for h in hits:
            title = str(h.get("title") or "").strip()
            obj_id = str(h.get("objectID") or "").strip()
            url = str(h.get("url") or "").strip() or (f"https://news.ycombinator.com/item?id={obj_id}" if obj_id else "")
            if not title or not url or url in seen_urls:
                continue
            seen_urls.add(url)
            pts = int(h.get("points") or 0)
            comments = int(h.get("num_comments") or 0)
            story_text = _strip_html(str(h.get("story_text") or ""))
            hn_link = f"https://news.ycombinator.com/item?id={obj_id}" if obj_id else ""
            summary_parts = [
                story_text[:240] if story_text else title,
                f"HN 热度：{pts} points / {comments} 评论",
                f"讨论页：{hn_link}" if hn_link and hn_link != url else "",
            ]
            items.append({
                "source_type": "hackernews",
                "source_name": f"Hacker News ({pts}↑)",
                "source_url": url,
                "raw_title": title,
                "raw_summary": " | ".join(p for p in summary_parts if p),
                "popularity": pts + comments * 2,
            })
            added_here += 1
            if added_here >= limit_per_kw:
                break
    return items, errors


def _bilibili_headers(referer: str = "https://search.bilibili.com/") -> Dict[str, str]:
    buvid3 = f"{uuid.uuid4()}infoc"
    return {
        "User-Agent": _UA,
        "Referer": referer,
        "Accept": "application/json",
        "Cookie": f"buvid3={buvid3}",
    }


def _calc_bili_popularity(play: int, like: int, review: int) -> int:
    return int(like * 10 + review * 5 + (math.log10(max(play, 1)) * 20 if play > 0 else 0))


_BILI_FANS_CACHE: Dict[int, int] = {}


def _fetch_bilibili_followers(mid: int) -> int:
    """查询 B 站 UP 主粉丝数（带内存缓存，失败返回 0 不影响主流程）。"""
    if mid <= 0:
        return 0
    if mid in _BILI_FANS_CACHE:
        return _BILI_FANS_CACHE[mid]
    try:
        _LIMITERS["bilibili"].wait()
        r = requests.get(
            "https://api.bilibili.com/x/web-interface/card",
            params={"mid": mid},
            headers=_bilibili_headers(f"https://space.bilibili.com/{mid}"),
            timeout=6,
        )
        d = r.json() if r.status_code == 200 else {}
        fans = int(((d.get("data") or {}).get("follower")) or 0)
        if fans > 0:
            _BILI_FANS_CACHE[mid] = fans
        return fans
    except Exception:
        return 0


def _fetch_bilibili_up_videos(account_ref: str, limit: int = 4) -> List[Dict[str, Any]]:
    """支持传 UP 主 UID（纯数字）或用户名关键词，抓取其最新视频。"""
    ref = (account_ref or "").strip()
    if not ref:
        return []
    mid: Optional[int] = int(ref) if ref.isdigit() else None
    up_name = ref

    if mid is None:
        _LIMITERS["bilibili"].wait()
        r = requests.get(
            "https://api.bilibili.com/x/web-interface/search/type",
            params={"keyword": ref, "search_type": "bili_user", "page": 1, "pagesize": 5},
            headers=_bilibili_headers(),
            timeout=12,
        )
        data = r.json() if r.status_code == 200 else {}
        if data.get("code") != 0:
            raise RuntimeError(f"B站用户检索返回 code={data.get('code')}")
        users = (data.get("data") or {}).get("result") or []
        if not users:
            return []
        exact = next((u for u in users if str(u.get("uname") or "").lower() == ref.lower()), None)
        picked = exact or (users[0] if int(users[0].get("fans") or 0) >= 500 else None)
        if not picked:
            return []
        mid = int(picked["mid"])
        up_name = str(picked.get("uname") or ref)

    _LIMITERS["bilibili"].wait()
    r2 = requests.get(
        "https://api.bilibili.com/x/space/arc/search",
        params={"mid": mid, "pn": 1, "ps": limit, "order": "pubdate"},
        headers=_bilibili_headers(f"https://space.bilibili.com/{mid}"),
        timeout=12,
    )
    d2 = r2.json() if r2.status_code == 200 else {}
    if d2.get("code") != 0:
        raise RuntimeError(f"B站空间接口返回 code={d2.get('code')}")
    vlist = ((d2.get("data") or {}).get("list") or {}).get("vlist") or []
    out: List[Dict[str, Any]] = []
    for v in vlist[:limit]:
        bvid = str(v.get("bvid") or "").strip()
        title = _strip_html(str(v.get("title") or ""))
        if not bvid or not title:
            continue
        desc = _strip_html(str(v.get("description") or ""))
        play = int(v.get("play") or 0)
        review = int(v.get("comment") or v.get("review") or 0)
        author = str(v.get("author") or up_name)
        out.append({
            "source_type": "bilibili",
            "source_name": f"B站UP·{author}",
            "source_url": f"https://www.bilibili.com/video/{bvid}",
            "raw_title": title,
            "raw_summary": f"{desc[:240] or title} | 播放 {play:,} / 评论 {review}",
            "popularity": _calc_bili_popularity(play, 0, review),
        })
    return out


def fetch_bilibili_topics(
    keywords: List[str],
    accounts: List[str] | None = None,
    limit_per_kw: int = 4,
) -> tuple[List[Dict[str, Any]], List[str]]:
    """免登录抓取 B 站最新实操视频 + 对标 UP 主最新更新（含 buvid3 与限流保护）。"""
    items: List[Dict[str, Any]] = []
    errors: List[str] = []
    seen_urls: set[str] = set()

    for kw in (keywords or [])[:4]:
        q = str(kw).strip()
        if not q:
            continue
        _LIMITERS["bilibili"].wait()
        try:
            r = requests.get(
                "https://api.bilibili.com/x/web-interface/search/type",
                params={
                    "keyword": q,
                    "search_type": "video",
                    "order": "pubdate",
                    "page": 1,
                    "pagesize": max(limit_per_kw * 2, 10),
                },
                headers=_bilibili_headers(),
                timeout=12,
            )
            data = r.json()
            if data.get("code") != 0:
                errors.append(f"B站[{q}]: API code={data.get('code')}")
                continue
            rows = (data.get("data") or {}).get("result") or []
        except Exception as e:
            errors.append(f"B站[{q}]: {e}")
            continue

        added = 0
        for v in rows:
            bvid = str(v.get("bvid") or "").strip()
            title = _strip_html(str(v.get("title") or ""))
            url = f"https://www.bilibili.com/video/{bvid}" if bvid else ""
            if not title or not url or url in seen_urls:
                continue
            seen_urls.add(url)
            play = int(v.get("play") or 0)
            like = int(v.get("like") or 0)
            review = int(v.get("review") or 0)
            mid = int(v.get("mid") or 0)
            followers = _fetch_bilibili_followers(mid) if (mid > 0 and play >= 5000 and added < 2) else 0
            author = str(v.get("author") or "").strip()
            desc = _strip_html(str(v.get("description") or ""))
            fans_note = f" / 粉 {followers:,}" if followers > 0 else ""
            items.append({
                "source_type": "bilibili",
                "source_name": f"B站·{author}" if author else "B站视频",
                "source_url": url,
                "raw_title": title,
                "raw_summary": f"{desc[:220] or title} | 播放 {play:,} / 点赞 {like} / 评论 {review}{fans_note}",
                "popularity": _calc_bili_popularity(play, like, review),
                "plays": play,
                "likes": like,
                "followers": followers,
            })
            added += 1
            if added >= limit_per_kw:
                break

    for acc in (accounts or [])[:5]:
        try:
            up_items = _fetch_bilibili_up_videos(acc, limit=3)
            for it in up_items:
                if it["source_url"] not in seen_urls:
                    seen_urls.add(it["source_url"])
                    items.append(it)
        except Exception as e:
            errors.append(f"B站UP[{acc}]: {e}")

    return items, errors


def fetch_weibo_hot_topics(keywords: List[str]) -> tuple[List[Dict[str, Any]], List[str]]:
    """抓取微博热搜公开榜，只保留与赛道关键词相关的破圈话题。"""
    _LIMITERS["weibo"].wait()
    try:
        r = requests.get(
            "https://weibo.com/ajax/side/hotSearch",
            headers={"User-Agent": _UA, "Accept": "application/json", "Referer": "https://weibo.com/"},
            timeout=12,
        )
        data = r.json()
    except Exception as e:
        return [], [f"微博热搜: {e}"]

    if data.get("ok") != 1:
        return [], []
    realtime = (data.get("data") or {}).get("realtime") or []
    terms = [k.strip().lower() for k in (keywords or []) if len(k.strip()) >= 2]
    # 补充 AI 破圈通用触发词
    for core in ("ai", "大模型", "claude", "deepseek", "openai", "agent", "一人公司", "副业", "程序员"):
        if core not in terms:
            terms.append(core)

    items: List[Dict[str, Any]] = []
    for row in realtime:
        topic_name = str(row.get("note") or row.get("word") or "").strip()
        if not topic_name:
            continue
        low = topic_name.lower()
        if not any(t in low for t in terms):
            continue
        hot_num = int(row.get("num") or row.get("raw_hot") or 0)
        items.append({
            "source_type": "weibo_hot",
            "source_name": "微博热搜破圈",
            "source_url": f"https://s.weibo.com/weibo?q={quote_plus('#' + topic_name + '#')}",
            "raw_title": f"微博热搜：{topic_name}",
            "raw_summary": f"微博热搜破圈话题「{topic_name}」，实时热度 {hot_num:,}",
            "popularity": hot_num,
        })
        if len(items) >= 5:
            break
    return items, []


def parse_rss_xml(xml_text: str, feed_name: str = "RSS", limit: int = 8) -> List[Dict[str, Any]]:
    """解析 RSS 2.0 或 Atom XML 为标准化选题候选列表。"""
    if not xml_text or not xml_text.strip():
        return []
    try:
        root = ET.fromstring(xml_text.strip())
    except Exception:
        return []

    out: List[Dict[str, Any]] = []
    rss_items = root.findall(".//item")
    if rss_items:
        for node in rss_items[:limit]:
            title = _strip_html(node.findtext("title") or "")
            link = (node.findtext("link") or "").strip()
            desc = _strip_html(node.findtext("description") or node.findtext("{http://purl.org/rss/1.0/modules/content/}encoded") or "")
            if title and link:
                out.append({
                    "source_type": "rss",
                    "source_name": feed_name,
                    "source_url": link,
                    "raw_title": title,
                    "raw_summary": desc[:400],
                    "popularity": 0,
                })
        return out

    ns = {"atom": "http://www.w3.org/2005/Atom"}
    entries = root.findall(".//atom:entry", ns) or root.findall(".//entry")
    for entry in entries[:limit]:
        title_el = entry.find("atom:title", ns)
        if title_el is None:
            title_el = entry.find("title")
        title = _strip_html(title_el.text if title_el is not None and title_el.text else "")

        link = ""
        for lk in entry.findall("atom:link", ns) + entry.findall("link"):
            href = (lk.attrib.get("href") or "").strip()
            rel = (lk.attrib.get("rel") or "alternate").strip()
            if href and rel in ("alternate", ""):
                link = href
                break
        if not link:
            id_el = entry.find("atom:id", ns)
            if id_el is None:
                id_el = entry.find("id")
            if id_el is not None and (id_el.text or "").startswith("http"):
                link = id_el.text.strip()

        sum_el = entry.find("atom:summary", ns)
        if sum_el is None:
            sum_el = entry.find("atom:content", ns)
        if sum_el is None:
            sum_el = entry.find("summary") or entry.find("content")
        summary = _strip_html(sum_el.text if sum_el is not None and sum_el.text else "")
        if title and link:
            out.append({
                "source_type": "rss",
                "source_name": feed_name,
                "source_url": link,
                "raw_title": title,
                "raw_summary": summary[:400],
                "popularity": 0,
            })
    return out


_RSS_CACHE: Dict[str, Dict[str, Any]] = {}
_RSS_CACHE_TTL_SEC = 600

OFFICIAL_AI_RSS_PRESETS: List[Dict[str, Any]] = [
    {"name": "OpenAI News", "url": "https://openai.com/news/rss.xml", "enabled": True},
    {"name": "Anthropic News", "url": "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_news.xml", "enabled": True},
    {"name": "Anthropic Engineering", "url": "https://raw.githubusercontent.com/Olshansk/rss-feeds/main/feeds/feed_anthropic_engineering.xml", "enabled": True},
    {"name": "Google DeepMind", "url": "https://deepmind.google/blog/rss.xml", "enabled": True},
    {"name": "Hugging Face Blog", "url": "https://huggingface.co/blog/feed.xml", "enabled": True},
    {"name": "Simon Willison", "url": "https://simonwillison.net/atom/everything/", "enabled": True},
    {"name": "Latent Space (AINews)", "url": "https://www.latent.space/feed", "enabled": True},
    {"name": "arXiv cs.AI", "url": "https://rss.arxiv.org/rss/cs.AI", "enabled": True},
]

_HF_PAPERS_CACHE: Dict[str, Any] = {"ts": 0.0, "items": []}
_REDDIT_CACHE: Dict[str, Dict[str, Any]] = {}
_BLUESKY_CACHE: Dict[str, Dict[str, Any]] = {}

DEFAULT_REDDIT_SUBREDDITS = ["LocalLLaMA", "ClaudeAI", "MachineLearning"]
DEFAULT_BLUESKY_HANDLES = [
    "karpathy.bsky.social",
    "simonwillison.net",
    "hardmaru.bsky.social",
    "emollick.bsky.social",
    "swyx.io",
]


def fetch_reddit_topics(
    subreddits: Optional[List[str]] = None,
    limit_per_sub: int = 6,
) -> tuple[List[Dict[str, Any]], List[str]]:
    """通过免 Key 的 Arctic Shift 镜像 API 抓取 Reddit AI 社区热帖（带 10 分钟缓存）。"""
    subs = [str(s).strip().lstrip("r/") for s in (subreddits or DEFAULT_REDDIT_SUBREDDITS) if str(s).strip()]
    if not subs:
        return [], []
    items: List[Dict[str, Any]] = []
    errors: List[str] = []
    seen: set[str] = set()
    now = time.time()
    for sub in subs[:6]:
        cached = _REDDIT_CACHE.get(sub)
        if cached and (now - cached["ts"] < _RSS_CACHE_TTL_SEC):
            for it in cached["items"][:limit_per_sub]:
                if it["source_url"] not in seen:
                    seen.add(it["source_url"])
                    items.append(it)
            continue
        try:
            if subs.index(sub) > 0:
                time.sleep(0.6)
            r = requests.get(
                "https://arctic-shift.photon-reddit.com/api/posts/search",
                params={"subreddit": sub, "limit": min(max(limit_per_sub, 5), 10)},
                headers={"User-Agent": _UA},
                timeout=12,
            )
            if r.status_code == 422:
                time.sleep(0.8)
                r = requests.get(
                    "https://arctic-shift.photon-reddit.com/api/posts/search",
                    params={"subreddit": sub, "limit": 5},
                    headers={"User-Agent": _UA},
                    timeout=12,
                )
            r.raise_for_status()
            rows = (r.json().get("data") or [])
            sub_items: List[Dict[str, Any]] = []
            for p in rows:
                title = str(p.get("title") or "").strip()
                if not title or p.get("removed_by_category"):
                    continue
                permalink = str(p.get("permalink") or "").strip()
                url = f"https://www.reddit.com{permalink}" if permalink.startswith("/") else str(p.get("url") or "").strip()
                if not url:
                    continue
                score = int(p.get("score") or 0)
                comments = int(p.get("num_comments") or 0)
                body = str(p.get("selftext") or "").replace("\n", " ").strip()
                ext_url = str(p.get("url") or "").strip()
                extra = f" | 外链: {ext_url}" if ext_url and "reddit.com" not in ext_url else ""
                sub_items.append({
                    "source_type": "reddit",
                    "source_name": f"Reddit·r/{sub}",
                    "source_url": url,
                    "raw_title": title,
                    "raw_summary": f"{body[:260] or title} | 赞 {score} / 评论 {comments}{extra}",
                    "popularity": max(0, score) + max(0, comments) * 3,
                })
            sub_items.sort(key=lambda x: x["popularity"], reverse=True)
            _REDDIT_CACHE[sub] = {"ts": now, "items": sub_items}
            for it in sub_items[:limit_per_sub]:
                if it["source_url"] not in seen:
                    seen.add(it["source_url"])
                    items.append(it)
        except Exception as e:
            errors.append(f"Reddit[r/{sub}]: {e}")
    return items, errors


def fetch_bluesky_topics(
    handles: Optional[List[str]] = None,
    limit_per_author: int = 4,
) -> tuple[List[Dict[str, Any]], List[str]]:
    """通过 Bluesky 免 Key 公开 getAuthorFeed 接口抓取 AI 大牛动态流（带 10 分钟缓存）。"""
    actors = [str(h).strip().lstrip("@") for h in (handles or DEFAULT_BLUESKY_HANDLES) if str(h).strip()]
    if not actors:
        return [], []
    items: List[Dict[str, Any]] = []
    errors: List[str] = []
    seen: set[str] = set()
    now = time.time()
    for actor in actors[:8]:
        cached = _BLUESKY_CACHE.get(actor)
        if cached and (now - cached["ts"] < _RSS_CACHE_TTL_SEC):
            for it in cached["items"][:limit_per_author]:
                if it["source_url"] not in seen:
                    seen.add(it["source_url"])
                    items.append(it)
            continue
        try:
            r = requests.get(
                "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed",
                params={"actor": actor, "limit": max(limit_per_author * 3, 10), "filter": "posts_no_replies"},
                headers={"User-Agent": _UA},
                timeout=10,
            )
            r.raise_for_status()
            feed = (r.json().get("feed") or [])
            author_items: List[Dict[str, Any]] = []
            for entry in feed:
                if entry.get("reason"):  # 跳过纯转发
                    continue
                post = entry.get("post") or {}
                rec = post.get("record") or {}
                text = str(rec.get("text") or "").replace("\n", " ").strip()
                if len(text) < 20:
                    continue
                uri = str(post.get("uri") or "")
                rkey = uri.rsplit("/", 1)[-1] if "/" in uri else ""
                author_info = post.get("author") or {}
                handle = str(author_info.get("handle") or actor)
                disp = str(author_info.get("displayName") or handle)
                url = f"https://bsky.app/profile/{handle}/post/{rkey}" if rkey else f"https://bsky.app/profile/{handle}"
                likes = int(post.get("likeCount") or 0)
                reposts = int(post.get("repostCount") or 0)
                replies = int(post.get("replyCount") or 0)
                ext = ((post.get("embed") or {}).get("external") or {})
                ext_title = str(ext.get("title") or "").strip()
                ext_uri = str(ext.get("uri") or "").strip()
                title = text[:95] + ("…" if len(text) > 95 else "")
                if ext_title:
                    title = f"{ext_title[:70]} — {text[:45]}"
                extra = f" | 引用: {ext_uri}" if ext_uri else ""
                author_items.append({
                    "source_type": "bluesky",
                    "source_name": f"Bluesky·{disp}",
                    "source_url": url,
                    "raw_title": title,
                    "raw_summary": f"{text[:300]} | 赞 {likes} / 转 {reposts} / 评 {replies}{extra}",
                    "popularity": likes + reposts * 2 + replies,
                })
            author_items.sort(key=lambda x: x["popularity"], reverse=True)
            _BLUESKY_CACHE[actor] = {"ts": now, "items": author_items}
            for it in author_items[:limit_per_author]:
                if it["source_url"] not in seen:
                    seen.add(it["source_url"])
                    items.append(it)
        except Exception as e:
            errors.append(f"Bluesky[{actor}]: {e}")
    return items, errors


def fetch_hf_daily_papers(limit: int = 12) -> tuple[List[Dict[str, Any]], List[str]]:
    """抓取 Hugging Face Daily Papers（免 Key 官方接口，按社区 upvotes 排序，带 10 分钟缓存）。"""
    now = time.time()
    if _HF_PAPERS_CACHE["items"] and (now - _HF_PAPERS_CACHE["ts"] < _RSS_CACHE_TTL_SEC):
        return list(_HF_PAPERS_CACHE["items"][:limit]), []
    try:
        r = requests.get("https://huggingface.co/api/daily_papers", headers={"User-Agent": _UA}, timeout=12)
        r.raise_for_status()
        rows = r.json() or []
        items: List[Dict[str, Any]] = []
        for row in rows:
            paper = row.get("paper") or {}
            pid = str(paper.get("id") or "").strip()
            title = str(row.get("title") or paper.get("title") or "").strip()
            if not title or not pid:
                continue
            summary = str(row.get("summary") or paper.get("summary") or "").replace("\n", " ").strip()
            upvotes = int(paper.get("upvotes") or 0)
            comments = int(row.get("numComments") or 0)
            gh = str(paper.get("githubRepo") or "").strip()
            url = f"https://huggingface.co/papers/{pid}"
            extra = f" | GitHub: {gh}" if gh else ""
            items.append({
                "source_type": "hf_papers",
                "source_name": "HF Daily Papers",
                "source_url": url,
                "raw_title": title,
                "raw_summary": f"{summary[:320]} | 点赞 {upvotes} / 评论 {comments}{extra}",
                "popularity": upvotes * 10 + comments * 5,
            })
        items.sort(key=lambda x: x["popularity"], reverse=True)
        _HF_PAPERS_CACHE["ts"] = now
        _HF_PAPERS_CACHE["items"] = items
        return items[:limit], []
    except Exception as e:
        return [], [f"HF Daily Papers: {e}"]


def fetch_rss_feeds(feeds: List[Dict[str, Any]], limit_per_feed: int = 15) -> tuple[List[Dict[str, Any]], List[str], Dict[str, int]]:
    items: List[Dict[str, Any]] = []
    errors: List[str] = []
    per_feed: Dict[str, int] = {}
    now = time.time()
    for f in feeds or []:
        if not isinstance(f, dict) or f.get("enabled") is False:
            continue
        url = str(f.get("url") or "").strip()
        name = str(f.get("name") or url).strip()
        if not url:
            continue
        cached = _RSS_CACHE.get(url)
        if cached and (now - cached["ts"] < _RSS_CACHE_TTL_SEC) and cached.get("limit", 0) >= limit_per_feed:
            parsed = cached["items"][:limit_per_feed]
            items.extend(parsed)
            per_feed[name] = len(parsed)
            continue
        try:
            headers = {"User-Agent": _UA}
            if cached:
                if cached.get("etag"):
                    headers["If-None-Match"] = cached["etag"]
                if cached.get("last_modified"):
                    headers["If-Modified-Since"] = cached["last_modified"]
            r = requests.get(url, headers=headers, timeout=12)
            if r.status_code == 304 and cached:
                _RSS_CACHE[url]["ts"] = now
                parsed = cached["items"][:limit_per_feed]
                items.extend(parsed)
                per_feed[name] = len(parsed)
                continue
            r.raise_for_status()
            parsed = parse_rss_xml(r.text, feed_name=name, limit=limit_per_feed)
            _RSS_CACHE[url] = {
                "ts": now,
                "etag": r.headers.get("ETag") or "",
                "last_modified": r.headers.get("Last-Modified") or "",
                "limit": limit_per_feed,
                "items": parsed,
            }
            items.extend(parsed)
            per_feed[name] = len(parsed)
        except Exception as e:
            per_feed[name] = 0
            errors.append(f"RSS[{name}]: {e}")
    return items, errors, per_feed


def fetch_wechat_topics(keywords: List[str], limit_per_kw: int = 4) -> tuple[List[Dict[str, Any]], List[str]]:
    items: List[Dict[str, Any]] = []
    errors: List[str] = []
    for kw in (keywords or [])[:3]:
        q = str(kw).strip()
        if not q:
            continue
        _LIMITERS["wechat"].wait()
        try:
            rows = asyncio.run(search_wechat(q, num=limit_per_kw))
            for row in rows or []:
                title = str(row.get("title") or "").strip()
                url = str(row.get("url") or "").strip()
                if not title:
                    continue
                src_acc = str(row.get("source") or row.get("account") or q).strip()
                items.append({
                    "source_type": "wechat_search",
                    "source_name": f"公众号·{src_acc}",
                    "source_url": url,
                    "raw_title": title,
                    "raw_summary": str(row.get("summary") or "").strip()[:400],
                    "popularity": 0,
                })
        except Exception as e:
            errors.append(f"搜狗微信[{q}]: {e}")
    return items, errors


def gather_all_sources(
    sources_config: Dict[str, Any],
    search_terms: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """按账号 sources_config 并发抓取所有开启的免费源。"""
    cfg = sources_config or {}
    all_items: List[Dict[str, Any]] = []
    errors: List[str] = []
    rss_detail: Dict[str, int] = {}
    stats = {
        "github_trending": 0,
        "hackernews": 0,
        "hf_papers": 0,
        "reddit": 0,
        "bluesky": 0,
        "bilibili": 0,
        "weibo_hot": 0,
        "rss": 0,
        "wechat_search": 0,
    }
    base_keywords = [str(k).strip() for k in (cfg.get("wechat_keywords") or []) if str(k).strip()]
    merged_terms = list(dict.fromkeys([*(base_keywords), *(search_terms or [])]))

    tasks = {}
    with ThreadPoolExecutor(max_workers=9) as pool:
        if cfg.get("github_trending", True):
            langs = cfg.get("github_languages") or ["python", "typescript", ""]
            tasks[pool.submit(lambda: (fetch_github_trending(languages=langs, limit=12), []))] = "github_trending"
        if cfg.get("hackernews", True):
            tasks[pool.submit(fetch_hackernews_topics, merged_terms, 48, 15, 5)] = "hackernews"
        if cfg.get("hf_papers", True):
            tasks[pool.submit(fetch_hf_daily_papers, 12)] = "hf_papers"
        if cfg.get("reddit", True):
            subs = cfg.get("reddit_subreddits") or DEFAULT_REDDIT_SUBREDDITS
            tasks[pool.submit(fetch_reddit_topics, subs, 6)] = "reddit"
        if cfg.get("bluesky", True):
            handles = cfg.get("bluesky_accounts") or DEFAULT_BLUESKY_HANDLES
            tasks[pool.submit(fetch_bluesky_topics, handles, 4)] = "bluesky"
        if cfg.get("bilibili", True):
            bili_kws = base_keywords or ["AI工具实操", "一人公司", "Claude Code"]
            tasks[pool.submit(fetch_bilibili_topics, bili_kws, cfg.get("bilibili_accounts") or [], 4)] = "bilibili"
        if cfg.get("weibo_hot", True):
            tasks[pool.submit(fetch_weibo_hot_topics, merged_terms)] = "weibo_hot"
        rss_feeds = [f for f in (cfg.get("rss_feeds") or []) if isinstance(f, dict) and f.get("enabled") is not False]
        if rss_feeds:
            tasks[pool.submit(fetch_rss_feeds, rss_feeds, 15)] = "rss"
        if cfg.get("wechat_search", True) and base_keywords:
            tasks[pool.submit(fetch_wechat_topics, base_keywords, 3)] = "wechat_search"

        for fut in as_completed(tasks):
            key = tasks[fut]
            try:
                res = fut.result()
                if key == "rss" and len(res) == 3:
                    items, errs, per_feed = res
                    rss_detail.update(per_feed)
                else:
                    items, errs = res
                all_items.extend(items)
                errors.extend(errs)
                stats[key] = len(items)
            except Exception as e:
                errors.append(f"{key}: {e}")

    return {"items": all_items, "stats": stats, "rss_detail": rss_detail, "errors": errors}
