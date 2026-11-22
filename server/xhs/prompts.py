# -*- coding: utf-8 -*-
"""小红书图组单页生图提示词（纯背景图模板，零文字）。"""

_STYLE_BLOCK = """STYLE: abstract editorial illustration background, premium Xiaohongshu style, clean, refined, soft gradients, paper texture, decorative shapes only.
ASPECT: vertical 3:4 poster background, high resolution, mobile friendly.
COMPLIANCE: background only; no phone frame; no app screenshot; no browser UI; no white border.
COLORS: {colors}"""

_NO_TEXT = """ABSOLUTE HARD NEGATIVE CONSTRAINTS:
- NO text of any kind. No Chinese characters. No English letters. No Latin alphabet. No digits. No numbers. No punctuation. No typography. No calligraphy.
- NO logo, NO watermark, NO signature, NO user name, NO label, NO sticker text, NO sign, NO poster title.
- NO user interface. NO social media screenshot. NO Xiaohongshu app page. NO chat bubbles. NO comment section. NO menus. NO buttons. NO icons with letters or numbers.
- Do not draw any readable or unreadable pseudo text, garbled text, fake glyphs, blurred words, text-like strokes, or UI-like cards containing text.
- The image must be a blank decorative illustration background only. All readable content will be added later by a canvas layout engine.
硬约束：画面中绝对不能出现汉字、英文字母、数字、标点、乱码、伪文字、文字块、logo、水印、账号名、截图界面、小红书页面、聊天框、评论区、按钮菜单。只画抽象装饰背景和无字插画。"""

_COVER_TEMPLATE = """TASK: Generate a pure decorative illustration background for a vertical poster.
COMPOSITION:
  - soft abstract focal shapes around the upper and lower edges
  - calm open negative space in the middle
  - decorative non-symbolic shapes, plants, light blobs, ribbons, gradients, paper grain
  - no document/page/app/card screenshot look
SUBJECT MOOD: {subject}
{_no_text}
{_style_block}
OUTPUT: clean blank background illustration, no text, no UI, no screenshot."""

_CONTENT_TEMPLATE = """TASK: Generate a pure decorative illustration background for an information poster.
COMPOSITION:
  - soft abstract background with {point_count} empty rounded color areas or gentle geometric blocks
  - areas must be blank, with no glyphs, no headings, no small marks that look like text
  - decorative non-symbolic icons are allowed only if they contain no letters/numbers and do not resemble app UI
  - avoid screenshot, notes app, browser, chat, feed, or social media interface
SUBJECT MOOD: {subject}
{_no_text}
{_style_block}
OUTPUT: clean blank background illustration with empty areas only, no text, no UI, no screenshot."""

_SUMMARY_TEMPLATE = """TASK: Generate a pure decorative illustration background for a final summary poster.
COMPOSITION:
  - warm completion mood, gentle celebratory abstract shapes, stars, ribbons, soft glow
  - central open negative space, bottom open area
  - all decorative elements must be non-text and non-UI
  - avoid screenshot, notes app, browser, chat, feed, or social media interface
SUBJECT MOOD: {subject}
{_no_text}
{_style_block}
OUTPUT: clean blank background illustration, no text, no UI, no screenshot."""

_PALETTES = {
    "warm": "warm palette: ivory, cream, latte, soft orange, caramel, low saturation",
    "fresh": "fresh palette: white, pale blue, mint green, lemon yellow, bright and airy",
    "elegant": "elegant palette: warm gray, mist blue, dusty rose, champagne gold, premium texture",
    "vibrant": "vibrant palette: pink, purple, bright orange, electric blue accents, lively but clean",
}


def _subject(page: dict, topic: str = "") -> str:
    if topic:
        return topic[:24]
    content = page.get("content") or ""
    for line in content.splitlines():
        line = line.strip()
        if line:
            return line.replace("大标题：", "").replace("标题：", "")[:24]
    return "clean lifestyle knowledge poster"


def build_image_prompt(page: dict, topic: str = "", palette: str = "warm") -> str:
    ptype = page.get("type", "content")
    style_block = _STYLE_BLOCK.format(colors=_PALETTES.get(palette, _PALETTES["warm"]))
    subject = _subject(page, topic)
    if ptype == "cover":
        return _COVER_TEMPLATE.format(subject=subject, _no_text=_NO_TEXT, _style_block=style_block)
    if ptype == "summary":
        return _SUMMARY_TEMPLATE.format(subject=subject, _no_text=_NO_TEXT, _style_block=style_block)
    lines = [ln for ln in (page.get("content") or "").splitlines() if ln.strip()]
    point_count = min(4, max(2, len(lines) - 1)) if len(lines) > 1 else 4
    return _CONTENT_TEMPLATE.format(subject=subject, point_count=point_count,
                                    _no_text=_NO_TEXT, _style_block=style_block)
