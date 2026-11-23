# -*- coding: utf-8 -*-
"""微信公众号精品排版主题渲染器（基于 gzh-design-skill 微信兼容规范）。

严格遵守微信公众号编辑器铁律：
- 全内联 style，零 <style> / <script> / class / id / display:grid / position:absolute
- 正文文本统一包裹在 <span leaf="">...</span> 内，防微信编辑器重排样式
- 代码块每行独立 <p>，缩进使用全角空格，不使用 white-space:pre
"""
from __future__ import annotations

import html
import re
from typing import Any, Dict, List

THEME_SPECS: Dict[str, Dict[str, str]] = {
    "moyu_green": {
        "id": "moyu_green",
        "name": "摸鱼绿",
        "desc": "emerald 杂志卡片风，适合 AI 工具实操、教程、清单测评",
        "primary": "#059669",
        "accent": "#10B981",
        "light_bg": "#ECFDF5",
        "light_border": "#A7F3D0",
        "title_color": "#111827",
        "body_color": "#374151",
        "muted_color": "#6B7280",
        "container_bg": "#FFFFFF",
        "underline_css": "border-bottom:2px solid #A7F3D0;font-weight:600;",
        "quote_bg": "#F0FDF4",
        "quote_border": "#059669",
        "code_inline_bg": "#ECFDF5",
        "code_inline_color": "#059669",
        "h2_mode": "badge",
    },
    "graphite_minimal": {
        "id": "graphite_minimal",
        "name": "石墨极简",
        "desc": "石墨灰+超大留白+几何细线，适合科技评论与一人公司深度思考",
        "primary": "#52525B",
        "accent": "#F97316",
        "light_bg": "#FAFAFA",
        "light_border": "#E4E4E7",
        "title_color": "#27272A",
        "body_color": "#52525B",
        "muted_color": "#A1A1AA",
        "container_bg": "#FFFFFF",
        "underline_css": "border-bottom:2px solid #52525B;font-weight:600;",
        "quote_bg": "#FAFAFA",
        "quote_border": "#52525B",
        "code_inline_bg": "#F4F4F5",
        "code_inline_color": "#27272A",
        "h2_mode": "watermark",
    },
    "red_white": {
        "id": "red_white",
        "name": "红白色系",
        "desc": "经典编辑风，淡粉下划线+正红锚点，适合深度分析与观点输出",
        "primary": "#DC2626",
        "accent": "#991B1B",
        "light_bg": "#FEF2F2",
        "light_border": "#FECACA",
        "title_color": "#1C1917",
        "body_color": "#374151",
        "muted_color": "#9CA3AF",
        "container_bg": "#FFFFFF",
        "underline_css": "border-bottom:2px solid #FECACA;font-weight:600;",
        "quote_bg": "#FEF2F2",
        "quote_border": "#DC2626",
        "code_inline_bg": "#FEF2F2",
        "code_inline_color": "#DC2626",
        "h2_mode": "badge",
    },
    "olive_journal": {
        "id": "olive_journal",
        "name": "橄榄手记",
        "desc": "米白纸感+墨黑+暖橙点睛，适合案例复盘与系统性方法论",
        "primary": "#1E1F23",
        "accent": "#ED7B2F",
        "light_bg": "#EEEFE9",
        "light_border": "#BFC1B7",
        "title_color": "#23251D",
        "body_color": "#4D4F46",
        "muted_color": "#65675E",
        "container_bg": "#FDFDF8",
        "underline_css": "border-bottom:2px solid #ED7B2F;font-weight:600;color:#23251D;",
        "quote_bg": "#EEEFE9",
        "quote_border": "#ED7B2F",
        "code_inline_bg": "#E5E7E0",
        "code_inline_color": "#1E1F23",
        "h2_mode": "tag",
    },
}

_FONT_STACK = "-apple-system,BlinkMacSystemFont,'PingFang SC','Hiragino Sans GB','Microsoft YaHei',sans-serif"


def list_themes() -> List[Dict[str, str]]:
    return [
        {
            "id": spec["id"],
            "name": spec["name"],
            "desc": spec["desc"],
            "primary": spec["primary"],
        }
        for spec in THEME_SPECS.values()
    ]


def _render_inline(text: str, spec: Dict[str, str]) -> str:
    """行内语法渲染：行内代码 / 加粗 / 高亮 / 下划线 / 链接。"""
    code_tokens: List[str] = []

    def _stash_code(m: re.Match) -> str:
        code_txt = html.escape(m.group(1))
        span = (
            f'<span style="background:{spec["code_inline_bg"]};color:{spec["code_inline_color"]};'
            f'padding:1px 6px;border-radius:4px;font-family:\'SF Mono\',Consolas,Monaco,monospace;'
            f'font-size:14px;"><span leaf="">{code_txt}</span></span>'
        )
        code_tokens.append(span)
        return f"__CODE_TOK_{len(code_tokens) - 1}__"

    s = re.sub(r"`([^`]+)`", _stash_code, text)
    s = html.escape(s)

    # 链接 [label](url)
    s = re.sub(
        r"\[([^\]]+)\]\((https?://[^)\s]+)\)",
        lambda m: (
            f'<a href="{html.escape(m.group(2), quote=True)}" '
            f'style="color:{spec["primary"]};text-decoration:none;'
            f'border-bottom:1px solid {spec["light_border"]};">'
            f'<span leaf="">{m.group(1)}</span></a>'
        ),
        s,
    )
    # ==高亮==
    s = re.sub(
        r"==(.+?)==",
        lambda m: (
            f'<span style="background:{spec["light_bg"]};color:{spec["title_color"]};'
            f'padding:1px 5px;border-radius:3px;{spec["underline_css"]}">'
            f'<span leaf="">{m.group(1)}</span></span>'
        ),
        s,
    )
    # ++下划线++
    s = re.sub(
        r"\+\+(.+?)\+\+",
        lambda m: f'<span style="{spec["underline_css"]}"><span leaf="">{m.group(1)}</span></span>',
        s,
    )
    # **加粗** -> 不把 font-size/border-bottom 打在 <strong> 上，遵循微信兼容铁律
    s = re.sub(
        r"\*\*(.+?)\*\*",
        lambda m: f'<span style="font-weight:700;color:{spec["title_color"]};"><span leaf="">{m.group(1)}</span></span>',
        s,
    )
    # *斜体*
    s = re.sub(r"\*(.+?)\*", lambda m: f'<em><span leaf="">{m.group(1)}</span></em>', s)

    if "__CODE_TOK_" in s:
        for idx, tok in enumerate(code_tokens):
            s = s.replace(f"__CODE_TOK_{idx}__", tok)
    return f'<span leaf="">{s}</span>' if "<span leaf=" not in s else s


def _render_code_block(lines: List[str], lang: str) -> str:
    lang_label = html.escape((lang or "text").strip())
    code_rows: List[str] = []
    for ln in lines:
        expanded = ln.replace("\t", "    ")
        lead = len(expanded) - len(expanded.lstrip(" "))
        indented = ("　" * (lead // 2)) + (" " * (lead % 2)) + expanded.lstrip(" ")
        safe = html.escape(indented) if indented else "&nbsp;"
        code_rows.append(
            '<p style="margin:0;font-family:\'SF Mono\',Consolas,Monaco,monospace;'
            f'font-size:13px;line-height:1.65;color:#E2E8F0;"><span leaf="">{safe}</span></p>'
        )
    body = "\n    ".join(code_rows)
    return (
        '<section style="margin:18px 0 22px;border-radius:8px;overflow:hidden;'
        'background:#1E293B;box-shadow:0 4px 16px -8px rgba(15,23,42,0.35);">\n'
        '  <section style="display:flex;align-items:center;padding:9px 14px;background:#0F172A;">\n'
        '    <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#FF5F56;margin-right:7px;font-size:0;line-height:0;overflow:hidden;">.</span>\n'
        '    <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#FFBD2E;margin-right:7px;font-size:0;line-height:0;overflow:hidden;">.</span>\n'
        '    <span style="display:inline-block;width:10px;height:10px;border-radius:50%;background:#27C93F;font-size:0;line-height:0;overflow:hidden;">.</span>\n'
        f'    <span style="margin-left:12px;font-size:12px;color:#94A3B8;font-family:Consolas,Monaco,monospace;letter-spacing:1px;"><span leaf="">{lang_label}</span></span>\n'
        '  </section>\n'
        f'  <section style="padding:12px 14px;">\n    {body}\n  </section>\n'
        '</section>'
    )


def _render_image_block(url: str, alt: str, spec: Dict[str, str]) -> str:
    safe_url = html.escape(url.strip(), quote=True)
    is_gif = url.lower().split("?")[0].endswith(".gif")
    cap_html = ""
    if alt.strip():
        badge = ""
        if is_gif:
            badge = (
                f'<span style="display:inline-block;background:{spec["light_bg"]};color:{spec["primary"]};'
                'font-size:11px;font-weight:700;padding:1px 8px;border-radius:4px;margin-right:6px;">'
                '<span leaf="">GIF 动图</span></span>'
            )
        cap_html = (
            f'\n<p style="font-size:12px;color:{spec["muted_color"]};text-align:center;margin:0 0 22px;">'
            f'{badge}<span leaf="">— {html.escape(alt.strip())}</span></p>'
        )
    mb = "8px" if cap_html else "20px"
    return (
        f'<section style="background:#FFFFFF;border-radius:10px;padding:6px;'
        f'border:1px solid {spec["light_border"]};box-shadow:0 4px 12px -2px rgba(0,0,0,0.06);margin:18px 0 {mb};">\n'
        f'  <section style="margin:0;border-radius:6px;overflow:hidden;">\n'
        f'    <span leaf=""><img src="{safe_url}" alt="{html.escape(alt.strip(), quote=True)}" '
        f'style="max-width:100%;height:auto;display:block;margin:0 auto;"></span>\n'
        f'  </section>\n'
        f'</section>{cap_html}'
    )


def _render_h2(title: str, idx: int, spec: Dict[str, str]) -> str:
    num = f"{idx:02d}"
    mode = spec.get("h2_mode", "badge")
    safe = html.escape(title.strip())
    if mode == "watermark":
        return (
            '<section style="margin:38px 0 18px;padding-bottom:10px;border-bottom:1px solid #E4E4E7;">\n'
            f'  <p style="font-size:12px;font-weight:700;color:{spec["accent"]};letter-spacing:2px;margin:0 0 4px;"><span leaf="">PART {num}</span></p>\n'
            f'  <p style="font-size:19px;font-weight:800;color:{spec["title_color"]};margin:0;line-height:1.4;"><span leaf="">{safe}</span></p>\n'
            '</section>'
        )
    if mode == "tag":
        return (
            '<section style="margin:34px 0 16px;padding:10px 14px;background:#EEEFE9;border-left:4px solid #ED7B2F;border-radius:4px;">\n'
            f'  <p style="font-size:11px;font-weight:700;color:#ED7B2F;letter-spacing:2px;margin:0 0 3px;"><span leaf="">SECTION {num}</span></p>\n'
            f'  <p style="font-size:18px;font-weight:800;color:{spec["title_color"]};margin:0;line-height:1.4;"><span leaf="">{safe}</span></p>\n'
            '</section>'
        )
    return (
        '<section style="margin:34px 0 18px;display:flex;align-items:center;gap:10px;">\n'
        f'  <span style="display:inline-block;background:{spec["primary"]};color:#FFFFFF;font-size:12px;'
        f'font-weight:700;padding:3px 9px;border-radius:6px;letter-spacing:1px;"><span leaf="">{num}</span></span>\n'
        f'  <p style="font-size:19px;font-weight:800;color:{spec["title_color"]};margin:0;line-height:1.4;flex:1;"><span leaf="">{safe}</span></p>\n'
        '</section>'
    )


def _render_table(rows: List[List[str]], spec: Dict[str, str]) -> str:
    if not rows:
        return ""
    head = rows[0]
    body = rows[1:]
    th_cells = "".join(
        f'<th style="padding:10px 12px;text-align:left;font-size:13px;font-weight:700;'
        f'color:{spec["title_color"]};background:{spec["light_bg"]};border-bottom:2px solid {spec["light_border"]};">'
        f'<span leaf="">{html.escape(c)}</span></th>'
        for c in head
    )
    tr_html: List[str] = []
    for r_i, row in enumerate(body):
        bg = "#FFFFFF" if r_i % 2 == 0 else "#FAFAFA"
        tds = "".join(
            f'<td style="padding:9px 12px;font-size:13px;color:{spec["body_color"]};'
            f'background:{bg};border-bottom:1px solid #E5E7EB;">{_render_inline(c, spec)}</td>'
            for c in row
        )
        tr_html.append(f"<tr>{tds}</tr>")
    return (
        '<section style="margin:18px 0 22px;overflow-x:auto;border:1px solid #E5E7EB;border-radius:8px;">\n'
        f'  <table style="width:100%;border-collapse:collapse;"><thead><tr>{th_cells}</tr></thead>'
        f'<tbody>{"".join(tr_html)}</tbody></table>\n'
        '</section>'
    )


def render_wechat_theme_html(
    md_text: str,
    theme_id: str = "moyu_green",
    author: str = "",
    footer: str = "",
) -> str:
    """将 Markdown 渲染为符合公众号排版铁律的内联样式 HTML。"""
    spec = THEME_SPECS.get(theme_id) or THEME_SPECS["moyu_green"]
    text = (md_text or "").replace("\r\n", "\n")
    text = re.sub(r"\n*发布检查[:：].*均已过.*$", "", text, flags=re.S).strip()
    if not text:
        return "<p></p>"

    lines = text.split("\n")
    blocks: List[str] = []
    i = 0
    h2_idx = 0
    first_quote_done = False

    while i < len(lines):
        raw = lines[i]
        s = raw.strip()
        if not s:
            i += 1
            continue

        # 围栏代码块
        if s.startswith("```"):
            lang = s[3:].strip()
            i += 1
            code_lines: List[str] = []
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code_lines.append(lines[i])
                i += 1
            if i < len(lines):
                i += 1
            blocks.append(_render_code_block(code_lines, lang))
            continue

        # 独立图片行 ![alt](url)
        img_m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)$", s)
        if img_m:
            blocks.append(_render_image_block(img_m.group(2), img_m.group(1), spec))
            i += 1
            continue

        # 标题
        h_m = re.match(r"^(#{1,4})\s+(.+)$", s)
        if h_m:
            lvl = len(h_m.group(1))
            title_txt = h_m.group(2).strip()
            if lvl == 1:
                blocks.append(
                    f'<p style="font-size:22px;font-weight:800;color:{spec["title_color"]};'
                    f'margin:0 0 20px;line-height:1.4;"><span leaf="">{html.escape(title_txt)}</span></p>'
                )
            elif lvl == 2:
                h2_idx += 1
                blocks.append(_render_h2(title_txt, h2_idx, spec))
            else:
                blocks.append(
                    f'<p style="font-size:16px;font-weight:700;color:{spec["title_color"]};'
                    f'margin:24px 0 10px;padding-left:10px;border-left:3px solid {spec["primary"]};line-height:1.5;">'
                    f'<span leaf="">{html.escape(title_txt)}</span></p>'
                )
            i += 1
            continue

        # 分割线
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
            blocks.append(
                f'<section style="margin:26px auto;width:48%;height:1px;background:{spec["light_border"]};">'
                '<span leaf=""><br></span></section>'
            )
            i += 1
            continue

        # 引用块（连续 > 行）
        if s.startswith(">"):
            q_lines: List[str] = []
            while i < len(lines) and lines[i].strip().startswith(">"):
                q_lines.append(lines[i].strip().lstrip(">").strip())
                i += 1
            q_body = "<br>".join(_render_inline(ln, spec) for ln in q_lines if ln)
            if not first_quote_done and len(blocks) <= 1:
                first_quote_done = True
                blocks.append(
                    f'<section style="margin:10px 0 26px;padding:20px 20px 18px;'
                    f'border-top:1px solid {spec["light_border"]};border-bottom:1px solid {spec["light_border"]};'
                    f'background:{spec["quote_bg"]};border-radius:8px;">\n'
                    f'  <p style="font-size:11px;color:{spec["primary"]};letter-spacing:2px;margin:0 0 10px;font-weight:700;"><span leaf="">导读</span></p>\n'
                    f'  <p style="font-size:15px;font-weight:600;color:{spec["title_color"]};margin:0;line-height:1.8;">{q_body}</p>\n'
                    '</section>'
                )
            else:
                blocks.append(
                    f'<section style="margin:18px 0 20px;padding:14px 18px;background:{spec["quote_bg"]};'
                    f'border-left:3px solid {spec["quote_border"]};border-radius:0 6px 6px 0;">\n'
                    f'  <p style="margin:0;font-size:14px;color:{spec["body_color"]};line-height:1.8;">{q_body}</p>\n'
                    '</section>'
                )
            continue

        # Markdown 表格
        if "|" in s and i + 1 < len(lines) and re.match(r"^\|?[\s:|-]+\|[\s:|-]*$", lines[i + 1].strip()):
            tbl_rows: List[List[str]] = []
            header = [c.strip() for c in s.strip("|").split("|")]
            tbl_rows.append(header)
            i += 2
            while i < len(lines) and "|" in lines[i].strip():
                row_cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                tbl_rows.append(row_cells)
                i += 1
            blocks.append(_render_table(tbl_rows, spec))
            continue

        # 无序/有序列表
        if re.match(r"^[-*]\s+", s) or re.match(r"^\d+\.\s+", s):
            is_ol = bool(re.match(r"^\d+\.\s+", s))
            items: List[str] = []
            idx_num = 1
            while i < len(lines):
                cur = lines[i].strip()
                m_li = re.match(r"^(\d+)\.\s+(.+)$", cur) if is_ol else re.match(r"^[-*]\s+(.+)$", cur)
                if not m_li:
                    break
                txt = m_li.group(2) if is_ol else m_li.group(1)
                marker = f"{idx_num}." if is_ol else "•"
                idx_num += 1
                items.append(
                    f'<p style="margin:0 0 8px;font-size:15px;line-height:1.85;color:{spec["body_color"]};">'
                    f'<span style="color:{spec["primary"]};font-weight:700;margin-right:8px;"><span leaf="">{marker}</span></span>'
                    f'{_render_inline(txt, spec)}</p>'
                )
                i += 1
            blocks.append(f'<section style="margin:10px 0 18px;padding-left:6px;">\n  ' + "\n  ".join(items) + "\n</section>")
            continue

        # 普通段落
        blocks.append(
            f'<p style="margin:0 0 16px;font-size:15px;line-height:1.85;color:{spec["body_color"]};'
            f'letter-spacing:0.4px;">{_render_inline(s, spec)}</p>'
        )
        i += 1

    if footer.strip():
        blocks.append(
            f'<section style="margin:28px 0 12px;padding:16px 18px;background:{spec["light_bg"]};'
            f'border:1px solid {spec["light_border"]};border-radius:8px;">\n'
            f'  <p style="margin:0;font-size:14px;line-height:1.75;color:{spec["title_color"]};font-weight:600;">'
            f'{_render_inline(footer.strip(), spec)}</p>\n'
            '</section>'
        )

    if author.strip():
        blocks.append(
            f'<p style="text-align:right;font-size:12px;color:{spec["muted_color"]};margin:20px 0 6px;letter-spacing:1px;">'
            f'<span leaf="">—— {html.escape(author.strip())}</span></p>'
        )

    inner = "\n".join(blocks)
    return (
        f'<section style="max-width:677px;margin:0 auto;padding:18px 14px;background:{spec["container_bg"]};'
        f'font-family:{_FONT_STACK};color:{spec["body_color"]};line-height:1.8;letter-spacing:0.4px;overflow-x:hidden;">\n'
        f'{inner}\n'
        '</section>'
    )
