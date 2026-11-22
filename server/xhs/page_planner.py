# -*- coding: utf-8 -*-
"""小红书页大纲解析：把 outline 文本切成页清单 [{index,type,content}]。"""
import re
from typing import Any, Dict, List

_MARKER_RE = re.compile(r"^\s*\[(封面|cover|内容|content|总结|summary)\]\s*(.*)$", re.IGNORECASE)
_TYPE_MAP = {
    "封面": "cover", "cover": "cover",
    "内容": "content", "content": "content",
    "总结": "summary", "summary": "summary",
}
_TYPE_CN = {"cover": "封面", "content": "内容", "summary": "总结"}

_PREFIX_RE = re.compile(
    r"^\s*(?:[-*•·]|\d+[).、]|#+)?\s*"
    r"(?:大标题|标题|主标题|副标题|小标题|正文|文案|页眉|页面标题|"
    r"要点\s*\d*|重点\s*\d*|结论|总结|互动|互动引导|CTA|"
    r"背景|画面|画面描述|主视觉|配图|插画|布局|留白|风格|色调|"
    r"用户口吻|口吻|场景|元素|装饰)\s*[：:]\s*",
    re.IGNORECASE,
)
_META_PREFIX_RE = re.compile(
    r"^\s*(?:[-*•·]|\d+[).、]|#+)?\s*"
    r"(?:画面|画面描述|主视觉|配图|插画|布局|留白|风格|色调|场景|元素|装饰|用户口吻|口吻)\s*[：:]",
    re.IGNORECASE,
)
_BULLET_RE = re.compile(r"^\s*(?:[-*•·]|\d+[).、]|#+)\s*")
_KEY_VALUE_RE = re.compile(r"^\s*([^：:]{1,10})\s*[：:]\s*(.+)$")


def parse_pages(outline_text: str) -> List[Dict[str, Any]]:
    if not outline_text or not outline_text.strip():
        return []
    pages: List[Dict[str, Any]] = []
    preamble: List[str] = []
    for raw in outline_text.splitlines():
        line = raw.strip()
        if not line:
            continue
        m = _MARKER_RE.match(line)
        if m:
            ptype = _TYPE_MAP.get(m.group(1).lower(), "content")
            pages.append({"type": ptype, "content": m.group(2).strip()})
        elif pages:
            pages[-1]["content"] = (pages[-1]["content"] + "\n" + line).strip() if pages[-1]["content"] else line
        else:
            preamble.append(line)
    if not pages:
        return [{"index": 0, "type": "cover", "content": "\n".join(preamble) or outline_text.strip()}]
    if preamble and pages[0]["type"] == "cover" and not pages[0]["content"]:
        pages[0]["content"] = "\n".join(preamble)
    if not any(p["type"] == "cover" for p in pages):
        pages[0]["type"] = "cover"
    if len(pages) > 1 and not any(p["type"] == "summary" for p in pages):
        pages[-1]["type"] = "summary"
    for i, p in enumerate(pages):
        p["index"] = i
    return pages


def page_label(page: Dict[str, Any]) -> str:
    cn = _TYPE_CN.get(page.get("type", "content"), "内容")
    content = (page.get("content") or "").replace("\n", " ")[:18]
    return f"{cn} · {content}" if content else cn


def _split_fragments(content: str) -> List[str]:
    text = (content or "").replace("|", "｜")
    text = re.sub(r"(?<!^)\s*(?=(?:要点|重点)\s*\d+\s*[：:])", "\n", text)
    text = re.sub(r"(?<!^)\s*(?=(?:副标题|小标题|互动引导|互动|结论|总结)\s*[：:])", "\n", text)
    parts: List[str] = []
    for line in text.splitlines():
        for part in re.split(r"\s*｜\s*", line):
            part = part.strip()
            if part:
                parts.append(part)
    return parts


def _clean_line(line: str) -> str:
    text = (line or "").strip()
    text = _MARKER_RE.sub(lambda m: m.group(2).strip(), text)
    text = _BULLET_RE.sub("", text)
    text = _PREFIX_RE.sub("", text)
    text = re.sub(r"\s+", " ", text).strip(" \t\r\n-—:：。")
    return text


def _is_meta_line(line: str) -> bool:
    return bool(_META_PREFIX_RE.match(line or ""))


def _short(text: str, n: int) -> str:
    chars = list(_clean_line(text))
    return "".join(chars[:n])


def _kv(lines: List[str], keys: List[str]) -> str:
    for line in lines:
        m = _KEY_VALUE_RE.match(line)
        if not m:
            continue
        key = m.group(1).strip().lower()
        if any(k.lower() in key for k in keys):
            val = _clean_line(m.group(2))
            if val:
                return val
    return ""


def _display_lines(content: str, keep_meta: bool = False) -> List[str]:
    lines: List[str] = []
    for raw in _split_fragments(content):
        raw = raw.strip()
        if not raw or (not keep_meta and _is_meta_line(raw)):
            continue
        text = _clean_line(raw)
        if text:
            lines.append(text)
    return lines


def extract_labels(page: Dict[str, Any]) -> Dict[str, Any]:
    content = (page.get("content") or "").strip()
    raw_lines = _split_fragments(content)
    ptype = page.get("type", "content")
    if not raw_lines:
        return {"title": "", "subtitle": "", "points": [], "header": ""}

    lines = _display_lines(content)
    if not lines:
        lines = _display_lines(content, keep_meta=True)

    if ptype == "cover":
        title = _kv(raw_lines, ["大标题", "主标题", "标题"]) or (lines[0] if lines else "")
        subtitle = _kv(raw_lines, ["副标题", "小标题"]) or (lines[1] if len(lines) > 1 else "")
        return {"title": _short(title, 18), "subtitle": _short(subtitle, 24), "points": [], "header": ""}

    if ptype == "summary":
        title = _kv(raw_lines, ["总结", "结论", "标题"]) or (lines[0] if lines else "")
        subtitle = _kv(raw_lines, ["互动", "引导", "副标题", "cta"]) or (lines[1] if len(lines) > 1 else "点关注看更多")
        points = [_short(x, 24) for x in lines[2:5] if x]
        return {"title": _short(title, 20), "subtitle": _short(subtitle, 24), "points": points, "header": "总结"}

    header = _kv(raw_lines, ["页眉", "页面标题", "标题", "主题"]) or (lines[0] if lines else "核心要点")
    points: List[str] = []
    for line in lines:
        text = _short(line, 46)
        if text and text not in points:
            points.append(text)
        if len(points) >= 4:
            break
    if not points and header:
        points.append(_short(header, 46))
    return {"title": _short(header, 18), "subtitle": "", "points": points, "header": _short(header, 12)}
