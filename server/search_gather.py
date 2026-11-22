# -*- coding: utf-8 -*-
"""自包含资料收集与本地文档解析（零依赖柳如烟 backend）。

- 联网搜资料：Tavily（若配置 key）→ 百度 → Bing 级联，带反爬相关性过滤与正文提取。
- 本地目录导入：支持 .txt / .md / .markdown / .pdf / .docx / .pptx + 图片扫描。
"""
from __future__ import annotations

import asyncio
import os
import re
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import httpx

from .paths import find_tavily_api_key

_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
)
_BAIDU_AD_PATTERNS = {"baidu.com/baidu.php", "e.baidu.com", "baichuan.baidu.com"}
_BING_AD_PATTERNS = {"bing.com/a?", "bing.com/aclick?", "bing.com/click?", "microsoft.com/", "bing.com/rewards/", "go.microsoft.com/"}

_QUERY_STOP = [
    "我用", "我搭", "我做", "我的", "我们", "怎么样", "怎么", "如何",
    "一套", "一个", "值得收藏", "值得", "分享一下", "分享", "聊聊", "谈谈",
    "记录一下", "记录", "手把手", "保姆级",
]

LOCAL_DOC_EXTS = {".txt", ".md", ".markdown", ".pdf", ".docx", ".pptx"}
LOCAL_IMG_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp"}


def _has_cjk(text: str) -> bool:
    return any("\u4e00" <= c <= "\u9fff" or "\u3040" <= c <= "\u30ff" or "\uac00" <= c <= "\ud7af" for c in (text or ""))


def _search_query(topic: str) -> str:
    q = re.sub(r"20\d{2}\s*年?", " ", topic.strip())
    for w in _QUERY_STOP:
        q = q.replace(w, " ")
    q = re.sub(r"^[的了吧呢和与及，,、\s]+|[的了吧呢，,、\s]+$", "", q)
    q = re.sub(r"\s+", " ", q).strip()
    return q if len(q) >= 3 else topic.strip()


def _looks_relevant(web: list, query: str) -> int:
    q = re.sub(r"\s+", "", query)
    grams = {q[i:i + 2] for i in range(len(q) - 1)} if len(q) >= 2 else {q}
    if not grams:
        return len(web)
    hit = 0
    for r in web:
        if isinstance(r, dict):
            title = str(r.get("title") or r.get("name") or "")
            if any(g in title for g in grams):
                hit += 1
    return hit


def _extract_regex(html: str, max_chars: int) -> str:
    html = re.sub(r"<(script|style|nav|header|footer|aside|form|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    m = re.search(r"<(article|main)[^>]*>(.*?)</\1>", html, flags=re.S | re.I)
    scope = m.group(2) if m else html
    paras = []
    for p in re.findall(r"<p[^>]*>(.*?)</p>", scope, flags=re.S | re.I):
        text = re.sub(r"<[^>]+>", "", p)
        text = re.sub(r"\s+", " ", text).strip()
        if len(text) >= 24:
            paras.append(text)
    article = "\n".join(paras)
    if len(article) < 80:
        text = re.sub(r"<[^>]+>", "", scope)
        article = re.sub(r"\s+", " ", text).strip()
    return article[:max_chars]


async def _extract_article(url: str, max_chars: int = 1200) -> str:
    if not url.startswith("http"):
        return ""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as c:
            r = await c.get(url, headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
            if r.status_code != 200:
                return ""
            html = r.text
    except Exception:
        return ""
    try:
        import trafilatura
        text = (trafilatura.extract(html, output_format="markdown", include_comments=False, include_tables=True) or "").strip()
        if len(text) >= 80:
            return text[:max_chars]
    except Exception:
        pass
    return _extract_regex(html, max_chars)


async def _search_tavily(query: str, limit: int = 6) -> List[Dict]:
    api_key = find_tavily_api_key()
    if not api_key:
        return []
    async with httpx.AsyncClient(timeout=20) as client:
        r = await client.post(
            "https://api.tavily.com/search",
            json={
                "api_key": api_key,
                "query": query,
                "max_results": limit,
                "search_depth": "advanced",
                "include_answer": False,
            },
        )
        r.raise_for_status()
        raw = r.json()
    return [
        {"title": item.get("title", ""), "url": item.get("url", ""), "snippet": item.get("content", "")}
        for item in (raw.get("results") or [])[:limit]
    ]


async def _search_baidu(query: str, limit: int = 6) -> List[Dict]:
    headers = {
        "User-Agent": _UA,
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        "Referer": "https://www.baidu.com/",
    }
    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        try:
            await client.get("https://www.baidu.com/", headers=headers)
        except Exception:
            pass
        r = await client.get("https://www.baidu.com/s", params={"wd": query, "rn": str(min(limit + 5, 20)), "ie": "utf-8"}, headers=headers)
        if r.status_code != 200:
            return []
        html = r.text

    containers = re.findall(r'<div[^>]*class="[^"]*\bresult\b[^"]*\bc-container\b[^"]*"[^>]*>(.*?)</div>\s*</div>', html, re.S) or [html]
    raw_hits: List[Dict[str, str]] = []
    for ch in containers:
        for h3 in re.findall(r"<h3[^>]*>(.*?)</h3>", ch, re.S):
            title = re.sub(r"<[^>]+>", "", h3).strip()
            lm = re.search(r'href=["\']([^"\']+)["\']', h3)
            if not title or not lm:
                continue
            url = lm.group(1)
            if not url.startswith("http") or any(p in url for p in _BAIDU_AD_PATTERNS):
                continue
            raw_hits.append({"title": title, "url": url})
            if len(raw_hits) >= limit:
                break
        if len(raw_hits) >= limit:
            break

    async def _resolve(item: Dict[str, str]) -> Dict[str, str]:
        if "baidu.com/link" not in item["url"]:
            return item
        try:
            async with httpx.AsyncClient(timeout=5, follow_redirects=False) as c:
                head = await c.head(item["url"], headers={"User-Agent": _UA})
                real = head.headers.get("Location") or head.headers.get("location")
                if real and real.startswith("http"):
                    item["url"] = real
        except Exception:
            pass
        return item

    return list(await asyncio.gather(*(_resolve(h) for h in raw_hits)))


async def _search_bing(query: str, limit: int = 6) -> List[Dict]:
    is_cjk = _has_cjk(query)
    base_url = "https://cn.bing.com/search" if is_cjk else "https://www.bing.com/search"
    params = {"q": query, "count": str(min(limit + 5, 20))}
    if is_cjk:
        params["setlang"] = "zh-CN"
    async with httpx.AsyncClient(timeout=12, follow_redirects=True) as client:
        r = await client.get(base_url, params=params, headers={"User-Agent": _UA, "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8"})
        if r.status_code != 200:
            return []
        html = r.text
    out: List[Dict] = []
    for algo in re.findall(r'<li\s+class="b_algo"[^>]*>(.*?)</li>', html, re.S):
        hm = re.search(r'<h2[^>]*>\s*<a\s+[^>]*href=["\']([^"\']+)["\'][^>]*>(.*?)</a>\s*</h2>', algo, re.S)
        if not hm:
            continue
        url = hm.group(1)
        title = re.sub(r"<[^>]+>", "", hm.group(2)).strip()
        if not title or not url.startswith("http") or any(p in url for p in _BING_AD_PATTERNS):
            continue
        out.append({"title": title, "url": url})
        if len(out) >= limit:
            break
    return out


async def gather_material(topic: str) -> str:
    if not topic.strip():
        return "（无主题，基于模型知识创作）"
    query = _search_query(topic)
    web: List[Dict] = []
    used = ""
    for name, fn in (("tavily", _search_tavily), ("baidu", _search_baidu), ("bing", _search_bing)):
        try:
            w = await fn(query, limit=6)
        except Exception:
            w = []
        if not w:
            continue
        if name == "tavily":
            web, used = w, name
            break
        rel = _looks_relevant(w, query)
        if len(w) >= 2 and rel >= 1:
            web, used = w, name
            break
        if w and rel >= 1 and not web:
            web, used = w, name
    if not web:
        return "（Tavily/百度/Bing 都没搜到，基于主题与模型知识创作；也可直接粘贴你的素材）"

    hits = [r for r in web if isinstance(r, dict) and str(r.get("url") or "").startswith("http")]
    arts = await asyncio.gather(*[_extract_article(str(r["url"])) for r in hits], return_exceptions=True)
    bodies = {str(r["url"]): a for r, a in zip(hits, arts) if isinstance(a, str) and len(a) >= 80}

    blocks = [f"【联网资料 · 来源 {used} · 搜索词「{query}」】"]
    for r in web:
        title = r.get("title") or ""
        url = str(r.get("url") or "")
        body = bodies.get(url)
        if body:
            blocks.append(f"### {title}\n{body}\n来源：{url}")
        else:
            snip = re.sub(r"\s+", " ", str(r.get("snippet") or "")).strip()
            blocks.append(f"### {title}\n{snip or '（未抓到正文，仅标题/链接）'}\n来源：{url}")
    return "\n\n".join(blocks)


def _read_doc_text(fp: Path, max_chars: int = 3500) -> str:
    ext = fp.suffix.lower()
    if ext in {".txt", ".md", ".markdown"}:
        return fp.read_text(encoding="utf-8-sig", errors="replace").strip()[:max_chars]
    if ext == ".pdf":
        from pypdf import PdfReader
        reader = PdfReader(str(fp))
        parts = [(page.extract_text() or "").strip() for page in reader.pages[:30]]
        return "\n\n".join(p for p in parts if p).strip()[:max_chars]
    if ext == ".docx":
        from docx import Document
        doc = Document(str(fp))
        parts = [p.text.strip() for p in doc.paragraphs if p.text.strip()]
        return "\n".join(parts).strip()[:max_chars]
    if ext == ".pptx":
        from pptx import Presentation
        prs = Presentation(str(fp))
        parts = []
        for slide in prs.slides:
            for shape in slide.shapes:
                if getattr(shape, "has_text_frame", False) and shape.text.strip():
                    parts.append(shape.text.strip())
        return "\n".join(parts).strip()[:max_chars]
    return ""


def read_local_dir(dir_path: str, existing_images: Optional[set] = None) -> Tuple[List[str], List[str], List[Dict[str, str]]]:
    """扫描本地目录的文档与图片，返回 (doc_blocks, file_names, new_image_entries)。"""
    d = Path(dir_path)
    existing = set(existing_images or set())
    blocks: List[str] = []
    files: List[str] = []
    imgs_added: List[Dict[str, str]] = []
    for fn in sorted(os.listdir(d)):
        fp = d / fn
        if not fp.is_file():
            continue
        ext = fp.suffix.lower()
        if ext in LOCAL_DOC_EXTS:
            try:
                text = _read_doc_text(fp)
                if text:
                    blocks.append(f"### 本地素材：{fn}\n{text}")
                    files.append(fn)
            except Exception:
                continue
        elif ext in LOCAL_IMG_EXTS and str(fp) not in existing:
            imgs_added.append({"name": fn, "path": str(fp)})
            existing.add(str(fp))
    return blocks, files, imgs_added
