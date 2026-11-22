# -*- coding: utf-8 -*-
"""YAML 工作流加载器：flows/*.yaml + prompts/**/*.md → WorkflowDef，构建 REGISTRY。

核心原则：**编排是配置，取数是代码**。
- 换工作流 / 改节点顺序 / 改审核插点 = 改 YAML，不改代码。
- 接一个全新数据源 = 在 TOOL_REGISTRY 注册一个工具函数（一次性）。

roles 的值支持两种写法：
- 文件引用（推荐）：``planner: prompts/content/planner.md`` → 读文件内容当 system prompt。
- inline 字符串：``planner: "你是..."`` → 原样当 system prompt。
"""
from __future__ import annotations

import os
import re
import json
import html
from typing import Any, Dict, List, Tuple
from urllib.parse import urlparse

import yaml

from workflow.engine import WorkflowDef, Node

_BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # ai-content/
_FLOWS_DIR = os.path.join(_BASE, "flows")
_PROMPTS_DIR = os.path.join(_BASE, "prompts", "content")
_STYLES_DIR = os.path.join(_PROMPTS_DIR, "styles")


# ───────────────────── 工具注册表（data 节点按名字引用）─────────────────────


def content_gather(state: dict) -> dict:
    """content_pipeline 的 collect 节点：收集资料写入 ``state.data.material``。

    三级回退（顺序即优先级，保证与柳如烟的契约 0 影响）：

    1. **宿主注入优先** —— 宿主（柳如烟）已把搜索底座抓好的资料写进 ``state.data.material``，
       原样返回。搜索底座（百度/Bing/反爬/小红书）留在柳如烟、与 agent 共享，只维护一份。
    2. **给定链接抓取** —— ``state.sources`` 非空时，逐个抓 URL 正文（微信/GitHub/普通页）
       拼成 material。这是「读取网络素材」，不是搜索：用户填几个参考链接进来。
    3. **兜底** —— 都没有时，回退到 topic 提示，绝不抛错、不崩链。
    """
    existing = state.get("data")
    if isinstance(existing, dict) and existing.get("material"):
        return existing  # 宿主路径：0 影响

    sources = _normalize_sources(state.get("sources"))
    if sources:
        material = _fetch_urls(sources)
        return {"material": material}

    topic = state.get("topic", "")
    return {"material": f"（未由宿主注入资料；基于主题「{topic}」与模型知识创作。）"}


TOOL_REGISTRY: Dict[str, Any] = {
    "content.gather": content_gather,
}


# ───────────────────── 网络素材抓取（content.gather 的 sources 路径用）─────────────────────
#
# 设计原则：**读取给定素材，不做搜索/反爬/翻页/JS 渲染**。
# 三类站点各有干净取法（实测）：微信服务端渲染、GitHub 走 API 拿 README、普通页剥标签。
# 任何一条失败都不崩链——记进 material 标注出来，其余继续。


_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
_TIMEOUT = 15
_MIN_LEN = 200  # 正文短于此视为抓取失败


def _normalize_sources(raw: Any) -> List[str]:
    """sources 可空：接受 URL 列表，或逗号/换行/空白分隔的字符串。"""
    if not raw:
        return []
    if isinstance(raw, (list, tuple)):
        items = [str(x) for x in raw]
    else:
        items = re.split(r"[\n,\s]+", str(raw))
    urls: List[str] = []
    for it in items:
        it = it.strip()
        if it.startswith("http://") or it.startswith("https://"):
            urls.append(it)
    return urls


def _http_get(url: str, headers: Dict[str, str]) -> "Any":
    """requests.get 的薄封装，SSL 校验失败时降级（Windows venv 普遍缺 CA 证书）。

    这是环境问题不是代码问题——不降级则所有 https 链接必挂。降级时屏蔽
    InsecureRequestWarning，避免日志噪音。返回值：requests.Response。
    """
    import requests
    try:
        return requests.get(url, headers=headers, timeout=_TIMEOUT, verify=True)
    except Exception:
        try:
            from urllib3 import disable_warnings
            from urllib3.exceptions import InsecureRequestWarning
            disable_warnings(InsecureRequestWarning)
        except Exception:
            pass
        return requests.get(url, headers=headers, timeout=_TIMEOUT, verify=False)


def _strip_tags(html_text: str) -> str:
    """剥 HTML 标签 → 纯文本（按段落换行）。script/style 整段先删。"""
    no_script = re.sub(r"<(script|style)\b[^>]*>.*?</\1>", "", html_text,
                       flags=re.S | re.I)
    # 段落/列表项边界转成换行，保留结构
    with_breaks = re.sub(r"</(p|div|li|h[1-6]|br|tr)\s*>", "\n",
                         no_script, flags=re.I)
    no_tags = re.sub(r"<[^>]+>", "", with_breaks)
    text = html.unescape(no_tags)
    # 压掉连续空行，trim 每行
    lines = [ln.strip() for ln in text.splitlines()]
    text = "\n".join(ln for ln in lines if ln)
    return text


def _fetch_github_readme(url: str) -> Dict[str, Any]:
    """GitHub 仓库根 URL → 走 API 拿 README（公开仓库无需 token，返回干净 markdown）。

    仓库页是 SPA，requests 直接抓到的是转义后的 JSON 壳；API 这条路最干净。
    支持 https://github.com/{owner}/{repo}[/tree/branch] 与 .git 后缀。
    """
    path = urlparse(url).path.strip("/")
    path = path[:-4] if path.endswith(".git") else path
    parts = path.split("/")
    if len(parts) < 2:
        return {"url": url, "title": "", "content": "", "ok": False,
                "status": "非仓库根 URL，跳过 GitHub 抓取"}
    owner, repo = parts[0], parts[1]
    api = f"https://api.github.com/repos/{owner}/{repo}/readme"
    r = _http_get(api, {"User-Agent": "ai-content-collect",
                        "Accept": "application/vnd.github.raw"})
    if r.status_code != 200:
        return {"url": url, "title": f"{owner}/{repo}", "content": "", "ok": False,
                "status": f"GitHub API {r.status_code}"}
    body = (r.text or "").strip()
    title = f"{owner}/{repo}"
    m = re.match(r"^#\s+(.+)$", body)
    if m:
        title = m.group(1).strip()
    return {"url": url, "title": title, "content": body, "ok": True,
            "status": f"GitHub README，{len(body)} 字"}


def _fetch_wechat(url: str) -> Dict[str, Any]:
    """微信公众号文章：定位 id="js_content" 容器取正文，og:title / activity-name 取标题。

    微信正文是服务端渲染的（容器 style visibility:hidden 只是 JS 渲染期开关，
    HTML 里实际有完整内容）。requests 能直接拿到。
    """
    r = _http_get(url, {"User-Agent": _UA})
    if r.status_code != 200:
        return {"url": url, "title": "", "content": "", "ok": False,
                "status": f"HTTP {r.status_code}"}
    t = r.text
    # 标题：og:title 最干净；退而求其次取 activity-name 里的文字
    title = ""
    m = re.search(r'<meta\s+property="og:title"\s+content="(.*?)"', t, re.I)
    if not m:
        m = re.search(r'id="activity-name"[^>]*>\s*<span[^>]*>(.*?)</span>', t, re.S)
    if m:
        title = html.unescape(m.group(1)).strip()
    # 正文容器：取 id="js_content" 所在开标签的 ">" 之后一段窗口剥标签
    # （从引号后截会带上 style="..." 残留属性，所以跳到开标签结束的 >）
    start = re.search(r'id=["\']js_content["\']', t)
    content = ""
    if start:
        gt = t.find(">", start.end())
        seg_start = gt + 1 if gt > 0 else start.end()
        seg = t[seg_start:seg_start + 200000]
        content = _strip_tags(seg)
        # 截到常见页脚标记前（点赞/分享/关注/投诉等）
        for marker in ["阅读原文", "Like the author", "继续访问", "继续滑动看下一个",
                       "微信扫一扫关注", "预览时标签不可点", "投诉", "赞 在看",
                       "修改于", "分享 收藏"]:
            idx = content.find(marker)
            if idx > 0:
                content = content[:idx].strip()
    return {"url": url, "title": title or "微信文章",
            "content": content.strip(), "ok": bool(content),
            "status": "微信文章" if content else "微信正文未抓到"}


def _fetch_generic(url: str) -> Dict[str, Any]:
    """普通网页：抓 HTML，删 script/style/nav，剥标签取正文。"""
    r = _http_get(url, {"User-Agent": _UA})
    if r.status_code != 200:
        return {"url": url, "title": "", "content": "", "ok": False,
                "status": f"HTTP {r.status_code}"}
    t = r.text
    # 删 nav/header/footer/aside 整块
    t = re.sub(r"<(nav|header|footer|aside|form|noscript)\b[^>]*>.*?</\1>",
               "", t, flags=re.S | re.I)
    content = _strip_tags(t)
    # title
    title = ""
    m = re.search(r"<title>(.*?)</title>", t, re.S | re.I)
    if m:
        title = html.unescape(m.group(1)).strip()
    return {"url": url, "title": title or urlparse(url).netloc,
            "content": content, "ok": bool(content),
            "status": "普通网页" if content else "正文为空"}


def _fetch_url(url: str) -> Dict[str, Any]:
    """按域名分派到对应抓取器，统一兜底失败。返回
    {url, title, content, ok, status}。"""
    host = urlparse(url).netloc.lower()
    try:
        if "github.com" in host:
            res = _fetch_github_readme(url)
        elif "mp.weixin.qq.com" in host:
            res = _fetch_wechat(url)
        else:
            res = _fetch_generic(url)
    except Exception as e:  # noqa: BLE001
        return {"url": url, "title": "", "content": "", "ok": False,
                "status": f"异常：{e}"}
    # 正文过短视为失败
    if res.get("ok") and len(res.get("content", "")) < _MIN_LEN:
        res["ok"] = False
        res["status"] = f"正文过短（{len(res.get('content', ''))} 字），视为抓取失败"
    return res


def _fetch_urls(urls: List[str]) -> str:
    """批量抓取 → 拼成 material 文本。失败条目照样写进结果并标注。"""
    blocks: List[str] = []
    for i, url in enumerate(urls, 1):
        res = _fetch_url(url)
        head = f"【素材 {i} · {res.get('title') or '（无标题）'}】\n来源：{url}\n状态："
        if res.get("ok"):
            body = res["content"]
            head += f"成功（{res.get('status', '')}，{len(body)} 字）"
        else:
            head += f"抓取失败：{res.get('status', '未知')}"
            body = "（本条未能抓取，请人工查看链接或改用其他素材。）"
        blocks.append(head + "\n\n" + body)
    return "\n\n" + "─" * 30 + "\n\n".join(blocks)


# ───────────────────── 终稿格式化（markdown → 公众号可粘贴 HTML）─────────────────────


# 公众号 inline style 模板：每个标签的样式字符串。
# 公众号编辑器不加载外部 CSS，所有样式必须 inline。
_WECHAT_STYLE_TEMPLATES: Dict[str, Dict[str, str]] = {
    "default": {
        "h1": "margin:30px 0 15px;font-size:22px;font-weight:bold;color:#333;",
        "h2": "margin:30px 0 15px;font-size:19px;font-weight:bold;color:#333;"
              "border-left:4px solid #07c160;padding-left:12px;line-height:1.4;",
        "h3": "margin:25px 0 10px;font-size:17px;font-weight:bold;color:#555;",
        "h4": "margin:20px 0 8px;font-size:16px;font-weight:bold;color:#666;",
        "p": "margin:0 0 20px;font-size:16px;line-height:1.8;color:#3f3f3f;"
             "letter-spacing:0.5px;",
        "blockquote": "margin:20px 0;padding:15px 20px;background:#f7f7f7;"
                      "border-left:4px solid #ddd;font-size:15px;color:#888;"
                      "border-radius:0 4px 4px 0;",
        "pre": "margin:20px 0;padding:16px;background:#282c34;border-radius:5px;"
               "overflow-x:auto;",
        "code": "font-size:14px;color:#abb2bf;",
        "inline_code": "background:#fff5f5;color:#fa755e;padding:2px 6px;"
                       "border-radius:3px;font-size:14px;",
        "ul": "margin:0 0 20px;padding-left:25px;font-size:16px;line-height:1.8;"
              "color:#3f3f3f;",
        "ol": "margin:0 0 20px;padding-left:25px;font-size:16px;line-height:1.8;"
              "color:#3f3f3f;",
        "li": "margin-bottom:6px;",
        "a": "color:#07c160;text-decoration:none;border-bottom:1px solid #07c160;",
        "strong": "font-weight:bold;color:#333;",
        "em": "font-style:italic;color:#555;",
        "hr": "border:none;border-top:1px solid #e5e5e5;margin:30px 0;",
        "img": "max-width:100%;border-radius:4px;margin:20px auto;display:block;",
        "table": "width:100%;border-collapse:collapse;margin:20px 0;font-size:15px;",
        "th": "border:1px solid #ddd;padding:8px 12px;background:#f5f5f5;"
              "font-weight:bold;text-align:left;",
        "td": "border:1px solid #ddd;padding:8px 12px;",
    },
    "liurun": {
        "h1": "margin:35px 0 15px;font-size:22px;font-weight:bold;color:#2b2b2b;",
        "h2": "margin:35px 0 15px;font-size:19px;font-weight:bold;color:#2b2b2b;"
              "border-left:3px solid #999;padding-left:12px;line-height:1.4;",
        "h3": "margin:25px 0 10px;font-size:17px;font-weight:bold;color:#444;",
        "h4": "margin:20px 0 8px;font-size:16px;font-weight:bold;color:#555;",
        "p": "margin:0 0 18px;font-size:16px;line-height:1.75;color:#3f3f3f;"
             "letter-spacing:0.3px;",
        "blockquote": "margin:20px 0;padding:12px 20px;background:#fafafa;"
                      "border-left:3px solid #ccc;font-size:15px;color:#666;",
        "pre": "margin:20px 0;padding:16px;background:#f5f5f5;border-radius:3px;"
               "overflow-x:auto;border:1px solid #e0e0e0;",
        "code": "font-size:14px;color:#333;",
        "inline_code": "background:#f0f0f0;color:#333;padding:2px 6px;"
                       "border-radius:2px;font-size:14px;",
        "ul": "margin:0 0 18px;padding-left:22px;font-size:16px;line-height:1.75;"
              "color:#3f3f3f;",
        "ol": "margin:0 0 18px;padding-left:22px;font-size:16px;line-height:1.75;"
              "color:#3f3f3f;",
        "li": "margin-bottom:4px;",
        "a": "color:#576b95;text-decoration:none;",
        "strong": "font-weight:bold;color:#2b2b2b;",
        "em": "font-style:italic;color:#555;",
        "hr": "border:none;border-top:1px solid #e0e0e0;margin:30px 0;",
        "img": "max-width:100%;border-radius:2px;margin:20px auto;display:block;",
        "table": "width:100%;border-collapse:collapse;margin:20px 0;font-size:15px;",
        "th": "border:1px solid #e0e0e0;padding:8px 12px;background:#fafafa;"
              "font-weight:bold;text-align:left;",
        "td": "border:1px solid #e0e0e0;padding:8px 12px;",
    },
    "khazix": {
        "h1": "margin:28px 0 12px;font-size:22px;font-weight:bold;color:#333;",
        "h2": "margin:28px 0 12px;font-size:19px;font-weight:bold;color:#333;"
              "line-height:1.4;",
        "h3": "margin:22px 0 8px;font-size:17px;font-weight:bold;color:#555;",
        "h4": "margin:18px 0 6px;font-size:16px;font-weight:bold;color:#666;",
        "p": "margin:0 0 16px;font-size:16px;line-height:1.85;color:#3a3a3a;"
             "letter-spacing:0.3px;",
        "blockquote": "margin:18px 0;padding:12px 18px;background:#fffbf5;"
                      "border-left:3px solid #f0a050;font-size:15px;color:#7a6a55;"
                      "border-radius:0 4px 4px 0;",
        "pre": "margin:18px 0;padding:16px;background:#2d2d2d;border-radius:5px;"
               "overflow-x:auto;",
        "code": "font-size:14px;color:#e6e6e6;",
        "inline_code": "background:#fff3e8;color:#c8770f;padding:2px 6px;"
                       "border-radius:3px;font-size:14px;",
        "ul": "margin:0 0 16px;padding-left:22px;font-size:16px;line-height:1.85;"
              "color:#3a3a3a;",
        "ol": "margin:0 0 16px;padding-left:22px;font-size:16px;line-height:1.85;"
              "color:#3a3a3a;",
        "li": "margin-bottom:5px;",
        "a": "color:#f07a2c;text-decoration:none;",
        "strong": "font-weight:bold;color:#333;",
        "em": "font-style:italic;color:#666;",
        "hr": "border:none;border-top:1px solid #eee;margin:25px 0;",
        "img": "max-width:100%;border-radius:6px;margin:18px auto;display:block;",
        "table": "width:100%;border-collapse:collapse;margin:18px 0;font-size:15px;",
        "th": "border:1px solid #eee;padding:8px 12px;background:#fffaf3;"
              "font-weight:bold;text-align:left;",
        "td": "border:1px solid #eee;padding:8px 12px;",
    },
}


def _preprocess_article(text: str) -> str:
    """终稿预处理：去尾行标记、压缩空行、trim 行尾、确保标题前后有空行。"""
    # 去掉 finalizer 添加的"发布检查"尾行
    text = re.sub(r"\n*发布检查[:：].*均已过.*$", "", text, flags=re.S)
    # 压缩连续空行（>2 → 1）
    text = re.sub(r"\n{3,}", "\n\n", text)
    # trim 每行行尾空格
    lines = [ln.rstrip() for ln in text.splitlines()]
    text = "\n".join(lines)
    # 确保 markdown 标题前后有空行
    text = re.sub(r"([^\n])\n(#{1,6}\s)", r"\1\n\n\2", text)
    text = re.sub(r"(#{1,6}\s[^\n]+)\n([^\n#])", r"\1\n\n\2", text)
    return text.strip()


def _md_to_html(text: str) -> str:
    """markdown → HTML（优先用 markdown 库；未装则 regex 降级）。"""
    try:
        import markdown as md
        return md.markdown(text, extensions=["extra", "sane_lists"])
    except ImportError:
        return _md_to_html_fallback(text)


def _md_to_html_fallback(text: str) -> str:
    """无 markdown 库时的简易转换（只处理常用语法）。"""
    lines = text.split("\n")
    out: List[str] = []
    in_ul = False
    in_ol = False
    for ln in lines:
        s = ln.strip()
        if not s:
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if in_ol:
                out.append("</ol>")
                in_ol = False
            out.append("")
            continue
        m = re.match(r"^(#{1,6})\s+(.+)$", s)
        if m:
            lvl = len(m.group(1))
            out.append(f"<h{lvl}>{html.escape(m.group(2))}</h{lvl}>")
            continue
        m = re.match(r"^\d+\.\s+(.+)$", s)
        if m:
            if not in_ol:
                out.append("<ol>")
                in_ol = True
            if in_ul:
                out.append("</ul>")
                in_ul = False
            out.append(f"<li>{html.escape(m.group(1))}</li>")
            continue
        if s.startswith("- ") or s.startswith("* "):
            if not in_ul:
                out.append("<ul>")
                in_ul = True
            if in_ol:
                out.append("</ol>")
                in_ol = False
            out.append(f"<li>{html.escape(s[2:])}</li>")
            continue
        if s.startswith("> "):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if in_ol:
                out.append("</ol>")
                in_ol = False
            out.append(f"<blockquote><p>{html.escape(s[2:])}</p></blockquote>")
            continue
        if re.match(r"^(-{3,}|\*{3,}|_{3,})$", s):
            if in_ul:
                out.append("</ul>")
                in_ul = False
            if in_ol:
                out.append("</ol>")
                in_ol = False
            out.append("<hr/>")
            continue
        if in_ul:
            out.append("</ul>")
            in_ul = False
        if in_ol:
            out.append("</ol>")
            in_ol = False
        content = html.escape(s)
        content = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", content)
        content = re.sub(r"\*(.+?)\*", r"<em>\1</em>", content)
        content = re.sub(r"`(.+?)`", r"<code>\1</code>", content)
        out.append(f"<p>{content}</p>")
    if in_ul:
        out.append("</ul>")
    if in_ol:
        out.append("</ol>")
    return "\n".join(out)


def _apply_inline_styles(html_body: str, tpl: Dict[str, str]) -> str:
    """给 HTML 标签注入 inline style（公众号不加载外部 CSS）。

    先暂存 pre 块（避免内部 code 被当 inline code 处理）→
    给其余标签加 style → 还原 pre 块并加 pre/code 样式。
    """
    pre_blocks: List[str] = []

    def _stash_pre(m: Any) -> str:
        pre_blocks.append(m.group(0))
        return f"__PRE_BLOCK_{len(pre_blocks) - 1}__"

    html_body = re.sub(r"<pre[^>]*>.*?</pre>", _stash_pre, html_body, flags=re.S)

    tag_map = [
        ("h1", tpl.get("h1", "")), ("h2", tpl.get("h2", "")),
        ("h3", tpl.get("h3", "")), ("h4", tpl.get("h4", "")),
        ("h5", tpl.get("h5", tpl.get("h4", ""))),
        ("h6", tpl.get("h6", tpl.get("h4", ""))),
        ("p", tpl.get("p", "")),
        ("blockquote", tpl.get("blockquote", "")),
        ("ul", tpl.get("ul", "")), ("ol", tpl.get("ol", "")),
        ("li", tpl.get("li", "")),
        ("code", tpl.get("inline_code", "")),
        ("strong", tpl.get("strong", "")),
        ("em", tpl.get("em", "")),
        ("a", tpl.get("a", "")),
        ("hr", tpl.get("hr", "")),
        ("img", tpl.get("img", "")),
        ("table", tpl.get("table", "")),
        ("th", tpl.get("th", "")), ("td", tpl.get("td", "")),
    ]

    for tag, style in tag_map:
        if not style:
            continue

        def _make_replacer(_tag: str, _style: str):
            def _repl(m: Any) -> str:
                full = m.group(0)
                if "style=" in full:
                    return full
                if full.endswith("/>"):
                    return full[:-2].rstrip() + f' style="{_style}"/>'
                return full[:-1].rstrip() + f' style="{_style}">'
            return _repl

        html_body = re.sub(rf"<{tag}\b[^>]*>", _make_replacer(tag, style), html_body)

    for idx, block in enumerate(pre_blocks):
        placeholder = f"__PRE_BLOCK_{idx}__"
        pre_style = tpl.get("pre", "")
        code_style = tpl.get("code", "")
        styled = re.sub(r"<pre(\s[^>]*)?>", f'<pre style="{pre_style}">',
                        block, count=1)
        styled = re.sub(r"<code(\s[^>]*)?>", f'<code style="{code_style}">',
                        styled, count=1)
        html_body = html_body.replace(placeholder, styled)

    return html_body


def _extract_metadata(text: str, platform: str) -> Dict[str, Any]:
    """从终稿提取元信息（标题、字数、阅读时长等）。"""
    title = ""
    m = re.search(r"^#\s+(.+)$", text, re.M)
    if m:
        title = m.group(1).strip()
    else:
        m = re.search(r"^##\s+(.+)$", text, re.M)
        if m:
            title = m.group(1).strip()
        else:
            for ln in text.splitlines():
                ln = ln.strip()
                if ln and not ln.startswith("#"):
                    title = ln[:50]
                    break

    cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    en_words = len(re.findall(r"[a-zA-Z]+", text))
    word_count = cn_chars + en_words
    read_time = max(1, round(word_count / 300))

    paragraphs = len([p for p in re.split(r"\n\s*\n", text) if p.strip()])
    headings = len(re.findall(r"^#{1,6}\s", text, re.M))

    return {
        "title": title,
        "word_count": word_count,
        "chinese_chars": cn_chars,
        "read_time": f"{read_time}分钟",
        "paragraphs": paragraphs,
        "headings": headings,
        "platform": platform,
    }


def content_format(state: dict) -> dict:
    """content_pipeline 的 format_output 节点：终稿 markdown → 公众号可粘贴 HTML。

    读 ``state.final``（终稿）+ ``state.platform`` + ``state._style``（可选写作风格名），
    输出三种格式 + 元信息：

    - **html**: 带 inline style 的 HTML，直接复制粘贴到公众号后台即所见即所得
    - **markdown**: 预处理后的干净 markdown（归档用）
    - **plain_text**: 纯文本（预览 / 校对用）
    - **metadata**: 标题、字数、阅读时长等结构化元信息

    样式模板按写作风格选择（default / liurun / khazix），确保视觉效果与内容调性一致。
    """
    article = state.get("final", "") or state.get("styled", "")
    if not isinstance(article, str):
        article = str(article) if article else ""
    platform = state.get("platform", "")
    style_name = state.get("_style", "") or ""

    if not article:
        return {"html": "", "markdown": "", "plain_text": "",
                "metadata": {}, "error": "终稿为空"}

    cleaned = _preprocess_article(article)
    html_body = _md_to_html(cleaned)
    tpl = _WECHAT_STYLE_TEMPLATES.get(style_name) or _WECHAT_STYLE_TEMPLATES["default"]
    html_body = _apply_inline_styles(html_body, tpl)

    container_style = (
        "max-width:677px;margin:0 auto;padding:20px 8px;"
        "font-family:-apple-system,BlinkMacSystemFont,'Segoe UI','PingFang SC',"
        "'Hiragino Sans GB','Microsoft YaHei',sans-serif;"
        "font-size:16px;color:#3f3f3f;word-wrap:break-word;"
    )
    html_out = f'<section style="{container_style}">\n{html_body}\n</section>'

    metadata = _extract_metadata(cleaned, platform)

    plain_text = re.sub(r"<[^>]+>", "", html_out).strip()
    plain_text = re.sub(r"\n{3,}", "\n\n", plain_text)

    return {
        "html": html_out,
        "markdown": cleaned,
        "plain_text": plain_text,
        "metadata": metadata,
    }


# 注册到工具表（content_format 定义在 TOOL_REGISTRY 之后，运行时补注册）
TOOL_REGISTRY["content.format"] = content_format


def _resolve_prompt(value: Any) -> str:
    """roles 的值：像文件路径就读文件内容，否则当 inline 提示词原样返回。"""
    if not isinstance(value, str):
        return ""
    looks_like_path = value.endswith(".md") or "/" in value or "\\" in value
    if looks_like_path:
        path = value if os.path.isabs(value) else os.path.join(_BASE, value)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception as e:  # noqa: BLE001
            return f"（提示词文件读取失败：{value} — {e}）"
    return value


# ───────────────────── 写作风格（运行时按 style 叠加角色提示词）─────────────────────


def resolve_role_prompt(role: str, style: str = "") -> str:
    """按写作风格解析角色 system prompt（公众号 content_pipeline 语境）。

    风格叠加：``styles/<style>/<role>.md`` 优先，没有则回退基础 ``prompts/content/<role>.md``。
    这样一个风格只需覆盖它关心的角色（如 viral 只覆盖 planner），其余沿用默认。

    注意：本函数 base 目录硬编码 ``prompts/content/``（公众号）。其它平台（如小红书
    ``prompts/xhs/``）的 role 提示词由 workflow 加载时已解析进 role_prompts，**不该被
    公众号专属 style 覆盖**——多平台请用 ``resolve_role_prompt_for`` 传 workflow 隔离。
    """
    if not role:
        return ""
    if style:
        styled = os.path.join(_STYLES_DIR, style, f"{role}.md")
        if os.path.isfile(styled):
            try:
                with open(styled, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:  # noqa: BLE001
                pass
    base = os.path.join(_PROMPTS_DIR, f"{role}.md")
    if os.path.isfile(base):
        try:
            with open(styled, "r", encoding="utf-8") as f:
                return f.read().strip()
        except Exception:  # noqa: BLE001
            pass
    return ""


def resolve_role_prompt_for(wf, role: str, style: str = "") -> str:
    """按写作风格解析角色 system prompt（workflow 感知，多平台安全）。

    与 ``resolve_role_prompt`` 的区别：style 仅对 ``content_pipeline``（公众号）生效——
    因为现有 styles/ 全是为公众号设计的，其 planner/finalizer 等是公众号语境。
    其它平台（如小红书 xhs_pipeline）的 role 提示词在 workflow 加载时已按平台目录
    解析（prompts/xhs/），共享同名 role（如 planner）但内容不同，公众号 style 不该
    串台覆盖。

    回退顺序：style 覆盖文件（仅 content_pipeline）→ workflow 已解析的 role_prompts → 空。
    """
    if not role:
        return ""
    # style 现只为公众号 content_pipeline 设计；其它平台直接用 workflow 加载的本平台提示词
    if style and getattr(wf, "id", "") == "content_pipeline":
        styled = os.path.join(_STYLES_DIR, style, f"{role}.md")
        if os.path.isfile(styled):
            try:
                with open(styled, "r", encoding="utf-8") as f:
                    return f.read().strip()
            except Exception:  # noqa: BLE001
                pass
    # 否则沿用 workflow 加载时解析的本平台提示词（如 prompts/xhs/planner.md）
    return (wf.role_prompts.get(role, "") if wf else "") or ""


def list_styles() -> List[Dict[str, Any]]:
    """扫 styles/ 列可用写作风格。

    overrides = 该风格目录下实际存在的 ``<role>.md``（去 .md）——即这个风格真正覆盖了
    哪些角色。前端据此标注「每一步是否受当前风格影响」，避免"以为全程都套了风格"的误导。
    """
    out: List[Dict[str, Any]] = []
    if not os.path.isdir(_STYLES_DIR):
        return out
    for name in sorted(os.listdir(_STYLES_DIR)):
        d = os.path.join(_STYLES_DIR, name)
        if not os.path.isdir(d):
            continue
        meta: Dict[str, Any] = {}
        mp = os.path.join(d, "_meta.json")
        if os.path.isfile(mp):
            try:
                with open(mp, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except Exception:  # noqa: BLE001
                meta = {}
        overrides = sorted(fn[:-3] for fn in os.listdir(d) if fn.endswith(".md"))
        out.append({
            "id": name,
            "name": str(meta.get("name", name)),
            "desc": str(meta.get("desc", "")),
            "overrides": overrides,
        })
    return out


def list_role_prompts(style: str = "") -> List[Dict[str, Any]]:
    """列默认角色清单（prompts/content/*.md）的提示词，按 style 解析并标注是否被覆盖。

    供「提示词编辑器」展示：选一个基础风格做起点，看到每个角色当前生效的提示词。
    """
    out: List[Dict[str, Any]] = []
    if not os.path.isdir(_PROMPTS_DIR):
        return out
    for fn in sorted(os.listdir(_PROMPTS_DIR)):
        if not fn.endswith(".md"):
            continue
        role = fn[:-3]
        out.append({
            "role": role,
            "text": resolve_role_prompt(role, style),
            "overridden": bool(style) and os.path.isfile(os.path.join(_STYLES_DIR, style, fn)),
        })
    return out


def save_style(name: str, prompts: Dict[str, str]) -> Dict[str, Any]:
    """保存自定义写作风格：styles/<slug>/<role>.md（仅写非空角色）+ _meta.json。

    slug 用 ascii 自动生成（避免中文目录名在子进程/路径里的坑）；显示名存 _meta.name。
    返回 {slug, name, overrides}。
    """
    import time as _t
    label = (name or "").strip() or "自定义风格"
    slug = "custom_" + _t.strftime("%m%d%H%M%S")
    d = os.path.join(_STYLES_DIR, slug)
    os.makedirs(d, exist_ok=True)
    written: List[str] = []
    for role, text in (prompts or {}).items():
        if isinstance(text, str) and text.strip():
            with open(os.path.join(d, f"{role}.md"), "w", encoding="utf-8") as f:
                f.write(text.strip() + "\n")
            written.append(role)
    meta = {"name": label, "desc": "自定义风格", "overrides": sorted(written)}
    with open(os.path.join(d, "_meta.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)
    return {"slug": slug, "name": label, "overrides": sorted(written)}


def _parse_node(raw: dict) -> Node:
    return Node(
        id=raw["id"],
        type=raw["type"],
        role=raw.get("role"),
        reads=list(raw.get("reads") or []),
        writes=raw.get("writes"),
        tool=raw.get("tool"),
        params=dict(raw.get("params") or {}),
        body=[_parse_node(n) for n in (raw.get("body") or [])],
    )


def load_workflow(path: str) -> WorkflowDef:
    """读一份 YAML → WorkflowDef（roles 文件引用就地展开成 system prompt）。"""
    with open(path, "r", encoding="utf-8") as f:
        spec = yaml.safe_load(f) or {}
    roles = {rid: _resolve_prompt(val) for rid, val in (spec.get("roles") or {}).items()}
    nodes = [_parse_node(n) for n in (spec.get("nodes") or [])]
    return WorkflowDef(
        id=spec["id"],
        name=spec.get("name", spec["id"]),
        inputs=list(spec.get("inputs") or []),
        role_prompts=roles,
        nodes=nodes,
    )


def _tools_for(wf: WorkflowDef) -> Dict[str, Any]:
    """收集该工作流所有节点（含 loop body）用到的工具，按名字从 TOOL_REGISTRY 取。"""
    tools: Dict[str, Any] = {}

    def walk(nodes: List[Node]) -> None:
        for n in nodes:
            if n.tool and n.tool in TOOL_REGISTRY:
                tools[n.tool] = TOOL_REGISTRY[n.tool]
            if n.body:
                walk(n.body)

    walk(wf.nodes)
    return tools


def build_registry() -> Dict[str, Tuple[WorkflowDef, Dict[str, Any]]]:
    """扫 flows/ 下所有 .yaml → {id: (WorkflowDef, tools)}（对齐旧 definitions.REGISTRY）。"""
    registry: Dict[str, Tuple[WorkflowDef, Dict[str, Any]]] = {}
    if not os.path.isdir(_FLOWS_DIR):
        return registry
    for fn in sorted(os.listdir(_FLOWS_DIR)):
        if not fn.endswith((".yaml", ".yml")):
            continue
        wf = load_workflow(os.path.join(_FLOWS_DIR, fn))
        registry[wf.id] = (wf, _tools_for(wf))
    return registry


REGISTRY = build_registry()
