# -*- coding: utf-8 -*-
"""Canvas 新版创作台 API（左画布实时编辑/微信预览 + 右侧多模态 Copilot + 快捷出版工具）。"""
from __future__ import annotations

import asyncio
import base64
import json
import mimetypes
import os
import re
import threading
import time
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, File, Form, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import db, gzh_themes, image_gen, llm_bridge, search_gather, settings_store, wechat_mp
from .canvas_llm import stream_multimodal_chat
from .paths import data_dir, project_root, studio_dir

router = APIRouter()

_MAX_VERSIONS = 25

# ─── 路径与持久化 ─────────────────────────────────────────────────────────────

def _canvas_dir() -> Path:
    d = data_dir() / "canvas"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _uploads_dir(pid: str) -> Path:
    d = _canvas_dir() / "uploads" / pid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _project_path(pid: str) -> Path:
    return _canvas_dir() / f"{pid}.json"


def _my_style_path() -> Path:
    return _canvas_dir() / "my_style.md"


def _load(pid: str) -> Optional[Dict[str, Any]]:
    p = _project_path(pid)
    if not p.exists():
        return None
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except Exception:
        return None


def _save(proj: Dict[str, Any]) -> None:
    proj["updated"] = time.time()
    _project_path(proj["id"]).write_text(json.dumps(proj, ensure_ascii=False, indent=2), encoding="utf-8")


def _push_version(proj: Dict[str, Any], label: str, title: Optional[str] = None, content: Optional[str] = None) -> Dict[str, Any]:
    versions = proj.setdefault("versions", [])
    cur_title = proj.get("title", "") if title is None else title
    cur_content = proj.get("content", "") if content is None else content
    if versions:
        last = versions[-1]
        if last.get("content") == cur_content and last.get("title") == cur_title:
            return last
    vid = f"v{len(versions) + 1}_{uuid.uuid4().hex[:4]}"
    snap = {
        "id": vid,
        "label": label,
        "title": cur_title,
        "content": cur_content,
        "ts": time.time(),
    }
    versions.append(snap)
    if len(versions) > _MAX_VERSIONS:
        proj["versions"] = versions[-_MAX_VERSIONS:]
    return snap


def _summary(proj: Dict[str, Any]) -> Dict[str, Any]:
    content = str(proj.get("content") or "")
    return {
        "id": proj["id"],
        "title": proj.get("title") or "未命名文章",
        "word_count": len(re.sub(r"\s+", "", content)),
        "version_count": len(proj.get("versions") or []),
        "source_count": len(proj.get("sources") or []),
        "theme": proj.get("theme") or "moyu_green",
        "style": proj.get("style") or "",
        "draft_media_id": proj.get("draft_media_id") or "",
        "source_studio_id": proj.get("source_studio_id") or "",
        "updated": proj.get("updated") or 0,
    }


def _read_my_style() -> str:
    p = _my_style_path()
    if not p.exists():
        return ""
    try:
        return p.read_text(encoding="utf-8-sig").strip()
    except Exception:
        return ""


def _load_style_guide(style_slug: str) -> str:
    slug = (style_slug or "").strip()
    prompts_dir = project_root() / "prompts" / "content"
    parts: List[str] = []
    if slug:
        sdir = prompts_dir / "styles" / slug
        for fn in ("writer.md", "style_editor.md", "finalizer.md"):
            fp = sdir / fn
            if fp.exists():
                try:
                    txt = fp.read_text(encoding="utf-8-sig").strip()
                    if txt:
                        parts.append(f"### 参考风格片段 ({fn})\n{txt}")
                except Exception:
                    pass
    if not parts:
        for fn in ("writer.md", "style_editor.md"):
            fp = prompts_dir / fn
            if fp.exists():
                try:
                    txt = fp.read_text(encoding="utf-8-sig").strip()
                    if txt:
                        parts.append(txt)
                except Exception:
                    pass
    return "\n\n".join(parts)


# ─── 项目管理 CRUD + 导入旧项目 ──────────────────────────────────────────────

class CreateCanvasRequest(BaseModel):
    title: str = "未命名文章"
    content: str = ""
    theme: str = "moyu_green"
    style: str = ""
    model: str = ""


class SaveCanvasRequest(BaseModel):
    title: Optional[str] = None
    content: Optional[str] = None
    theme: Optional[str] = None
    style: Optional[str] = None
    model: Optional[str] = None
    use_my_style: Optional[bool] = None
    cover_url: Optional[str] = None
    push_version: bool = False
    version_label: str = "手动保存"


class RestoreVersionRequest(BaseModel):
    version_id: str


@router.get("/canvas/projects")
def list_canvas_projects():
    items: List[Dict[str, Any]] = []
    for p in _canvas_dir().glob("*.json"):
        try:
            proj = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(proj, dict) and proj.get("id"):
                items.append(_summary(proj))
        except Exception:
            continue
    items.sort(key=lambda x: x.get("updated") or 0, reverse=True)
    return {"projects": items}


@router.post("/canvas/projects")
def create_canvas_project(req: CreateCanvasRequest):
    pid = "c_" + uuid.uuid4().hex[:10]
    now = time.time()
    proj: Dict[str, Any] = {
        "id": pid,
        "title": (req.title or "未命名文章").strip() or "未命名文章",
        "content": req.content or "",
        "initial_ai_draft": "",
        "cover_url": "",
        "model": req.model.strip(),
        "style": req.style.strip(),
        "use_my_style": True,
        "theme": (req.theme or "moyu_green").strip() or "moyu_green",
        "sources": [],
        "messages": [],
        "versions": [],
        "draft_media_id": "",
        "source_studio_id": "",
        "created": now,
        "updated": now,
    }
    if proj["content"].strip():
        _push_version(proj, "初始文稿")
    _save(proj)
    return {"ok": True, "project": proj}


@router.post("/canvas/projects/import-studio/{studio_pid}")
def import_from_studio(studio_pid: str):
    """从旧创作台只读导入一份副本到新版 Canvas，绝不改动原 studio 项目。"""
    sp = studio_dir() / f"{studio_pid}.json"
    if not sp.exists():
        return JSONResponse({"ok": False, "error": "原创作台项目不存在"}, status_code=404)
    try:
        old = json.loads(sp.read_text(encoding="utf-8"))
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"读取原项目失败：{e}"}, status_code=500)

    st = old.get("state") or {}
    layout = st.get("layout") if isinstance(st.get("layout"), dict) else {}
    body = str(
        st.get("final")
        or st.get("styled")
        or st.get("draft")
        or layout.get("markdown")
        or st.get("outline")
        or ""
    ).strip()

    sources: List[Dict[str, Any]] = []
    data_obj = st.get("data") if isinstance(st.get("data"), dict) else {}
    mat = str(data_obj.get("material") or "").strip()
    if mat:
        sources.append({
            "id": "s_" + uuid.uuid4().hex[:8],
            "kind": "text",
            "title": "原创作台收集素材",
            "content": mat[:15000],
            "added_at": time.time(),
        })
    for img in (st.get("images") or []):
        if isinstance(img, dict) and img.get("path") and os.path.isfile(str(img["path"])):
            sources.append({
                "id": "s_" + uuid.uuid4().hex[:8],
                "kind": "image",
                "title": str(img.get("name") or Path(str(img["path"])).name),
                "path": str(img["path"]),
                "url": "",
                "added_at": time.time(),
            })

    pid = "c_" + uuid.uuid4().hex[:10]
    now = time.time()
    proj: Dict[str, Any] = {
        "id": pid,
        "title": str(old.get("title") or "导入文稿").strip(),
        "content": body,
        "initial_ai_draft": body,
        "cover_url": str(st.get("_cover") or ""),
        "model": str(old.get("model") or ""),
        "style": str(old.get("style") or ""),
        "use_my_style": True,
        "theme": str(old.get("theme") or "moyu_green"),
        "sources": sources,
        "messages": [],
        "versions": [],
        "draft_media_id": "",
        "source_studio_id": studio_pid,
        "created": now,
        "updated": now,
    }
    if body:
        _push_version(proj, "从旧创作台导入")
    _save(proj)
    return {"ok": True, "project": proj}


@router.get("/canvas/projects/{pid}")
def get_canvas_project(pid: str):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    return {"ok": True, "project": proj}


@router.post("/canvas/projects/{pid}/save")
def save_canvas_project(pid: str, req: SaveCanvasRequest):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    if req.title is not None:
        proj["title"] = req.title.strip() or "未命名文章"
    if req.content is not None:
        proj["content"] = req.content
    if req.theme is not None:
        proj["theme"] = req.theme.strip() or "moyu_green"
    if req.style is not None:
        proj["style"] = req.style.strip()
    if req.model is not None:
        proj["model"] = req.model.strip()
    if req.use_my_style is not None:
        proj["use_my_style"] = bool(req.use_my_style)
    if req.cover_url is not None:
        proj["cover_url"] = req.cover_url.strip()
    if req.push_version:
        _push_version(proj, req.version_label or "手动快照")
    _save(proj)
    return {"ok": True, "project": proj}


@router.post("/canvas/projects/{pid}/restore-version")
def restore_canvas_version(pid: str, req: RestoreVersionRequest):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    versions = proj.get("versions") or []
    target = next((v for v in versions if v.get("id") == req.version_id), None)
    if target is None:
        return JSONResponse({"ok": False, "error": "版本快照不存在"}, status_code=404)
    if (proj.get("content") or "").strip():
        _push_version(proj, "恢复前备份")
    proj["title"] = target.get("title") or proj.get("title") or "未命名文章"
    proj["content"] = target.get("content") or ""
    _save(proj)
    return {"ok": True, "project": proj}


@router.delete("/canvas/projects/{pid}")
def delete_canvas_project(pid: str):
    p = _project_path(pid)
    if p.exists():
        p.unlink()
    return {"ok": True}


# ─── 多模态素材投喂（URL / 文档 / 图片 / 文本） ───────────────────────────────

class UrlSourceRequest(BaseModel):
    url: str


class TextSourceRequest(BaseModel):
    title: str = "补充笔记"
    content: str = ""


@router.post("/canvas/projects/{pid}/sources/url")
def add_url_source(pid: str, req: UrlSourceRequest):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    u = (req.url or "").strip()
    if not (u.startswith("http://") or u.startswith("https://")):
        return JSONResponse({"ok": False, "error": "请输入以 http:// 或 https:// 开头的有效网址"}, status_code=400)
    res = search_gather.fetch_url_text(u, max_chars=15000)
    if not res.get("ok"):
        return JSONResponse({"ok": False, "error": f"抓取失败：{res.get('error') or '页面未返回正文'}"}, status_code=400)
    src = {
        "id": "s_" + uuid.uuid4().hex[:8],
        "kind": "url",
        "title": str(res.get("title") or u)[:120],
        "url": u,
        "author": str(res.get("author") or ""),
        "content": str(res.get("content") or ""),
        "added_at": time.time(),
    }
    proj.setdefault("sources", []).append(src)
    _save(proj)
    return {"ok": True, "source": src, "sources": proj["sources"]}


@router.post("/canvas/projects/{pid}/sources/text")
def add_text_source(pid: str, req: TextSourceRequest):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    txt = (req.content or "").strip()
    if not txt:
        return JSONResponse({"ok": False, "error": "素材内容不能为空"}, status_code=400)
    src = {
        "id": "s_" + uuid.uuid4().hex[:8],
        "kind": "text",
        "title": (req.title or "补充事实/笔记").strip()[:80],
        "content": txt[:20000],
        "added_at": time.time(),
    }
    proj.setdefault("sources", []).append(src)
    _save(proj)
    return {"ok": True, "source": src, "sources": proj["sources"]}


@router.post("/canvas/projects/{pid}/sources/upload")
async def upload_source_file(pid: str, file: UploadFile = File(...), purpose: str = Form("source")):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    orig_name = Path(file.filename or "upload.bin").name
    ext = Path(orig_name).suffix.lower()
    raw = await file.read()
    if not raw:
        return JSONResponse({"ok": False, "error": "上传文件为空"}, status_code=400)

    up_dir = _uploads_dir(pid)
    saved_name = f"{uuid.uuid4().hex[:10]}{ext}"
    dst = up_dir / saved_name
    dst.write_bytes(raw)

    if ext in search_gather.LOCAL_IMG_EXTS:
        mime, _ = mimetypes.guess_type(orig_name)
        src = {
            "id": "s_" + uuid.uuid4().hex[:8],
            "kind": "image",
            "title": orig_name,
            "path": str(dst),
            "mime": mime or "image/png",
            "purpose": purpose,
            "added_at": time.time(),
        }
        proj.setdefault("sources", []).append(src)
        _save(proj)
        return {"ok": True, "source": src, "sources": proj["sources"]}

    if ext in search_gather.LOCAL_DOC_EXTS:
        try:
            text = search_gather._read_doc_text(dst, max_chars=15000)
        except Exception as e:
            return JSONResponse({"ok": False, "error": f"文档解析失败：{e}"}, status_code=400)
        if not text:
            return JSONResponse({"ok": False, "error": "未能从文档中提取到有效文本"}, status_code=400)
        src = {
            "id": "s_" + uuid.uuid4().hex[:8],
            "kind": "doc",
            "title": orig_name,
            "path": str(dst),
            "content": text,
            "added_at": time.time(),
        }
        proj.setdefault("sources", []).append(src)
        _save(proj)
        return {"ok": True, "source": src, "sources": proj["sources"]}

    return JSONResponse(
        {"ok": False, "error": f"暂不支持的文件类型 {ext}（支持图片与 txt/md/pdf/docx/pptx）"},
        status_code=400,
    )


@router.delete("/canvas/projects/{pid}/sources/{sid}")
def remove_source(pid: str, sid: str):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    proj["sources"] = [s for s in (proj.get("sources") or []) if s.get("id") != sid]
    _save(proj)
    return {"ok": True, "sources": proj["sources"]}


@router.get("/canvas/projects/{pid}/image")
def serve_canvas_image(pid: str, path: str = ""):
    if not path:
        return JSONResponse({"ok": False, "error": "缺少 path"}, status_code=400)
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    try:
        target = Path(path).resolve()
    except Exception:
        return JSONResponse({"ok": False, "error": "无效路径"}, status_code=400)
    if not target.is_file():
        return JSONResponse({"ok": False, "error": "文件不存在"}, status_code=404)

    allowed_roots = [
        _uploads_dir(pid).resolve(),
    ]
    for s in proj.get("sources") or []:
        if s.get("kind") == "image" and s.get("path"):
            try:
                if Path(str(s["path"])).resolve() == target:
                    allowed_roots.append(target.parent)
            except Exception:
                pass
    if not any(target == r or r in target.parents for r in allowed_roots):
        return JSONResponse({"ok": False, "error": "无权访问该路径"}, status_code=403)
    mime, _ = mimetypes.guess_type(str(target))
    return FileResponse(str(target), media_type=mime or "application/octet-stream")


# ─── 微信实时排版预览 ─────────────────────────────────────────────────────────

class RenderWechatRequest(BaseModel):
    markdown: str = ""
    theme: str = "moyu_green"
    author: str = ""
    include_footer: bool = False


@router.post("/canvas/render-wechat")
def render_wechat_preview(req: RenderWechatRequest):
    theme_id = (req.theme or "moyu_green").strip()
    footer = ""
    if req.include_footer:
        acc = db.get_primary_account()
        footer = acc.get("footer_template", "")
    md_text = (req.markdown or "").strip()
    if theme_id in gzh_themes.THEME_SPECS:
        html_out = gzh_themes.render_wechat_theme_html(md_text, theme_id=theme_id, author=req.author.strip(), footer=footer)
    else:
        html_out = wechat_mp.markdown_to_wechat_html(md_text, style=theme_id, author=req.author.strip(), footer=footer)
    return {"ok": True, "html": html_out, "theme": theme_id}


# ─── Copilot 流式对话与画布联动 ────────────────────────────────────────────────

class CanvasChatRequest(BaseModel):
    message: str
    model: str = ""
    style: str = ""
    use_my_style: bool = True
    selection: str = ""
    selection_start: int = -1
    selection_end: int = -1
    image_paths: List[str] = []
    current_title: Optional[str] = None
    current_content: Optional[str] = None


def _encode_image_data_uri(img_path: str) -> Optional[str]:
    try:
        p = Path(img_path)
        if not p.is_file() or p.stat().st_size > 8 * 1024 * 1024:
            return None
        mime, _ = mimetypes.guess_type(str(p))
        mime = mime or "image/png"
        b64 = base64.b64encode(p.read_bytes()).decode("ascii")
        return f"data:{mime};base64,{b64}"
    except Exception:
        return None


def _build_copilot_messages(proj: Dict[str, Any], req: CanvasChatRequest) -> List[Dict[str, Any]]:
    style_slug = req.style if req.style is not None else str(proj.get("style") or "")
    style_guide = _load_style_guide(style_slug)
    my_style = _read_my_style() if req.use_my_style else ""

    sys_parts = [
        "你是老板的专属文章共创副驾驶（Copilot），在双栏创作台工作：左侧是实时可编辑的公众号 Markdown 画布，右侧是与老板的对话窗口。",
        "你的职责：结合老板投喂的所有图文/链接/文档素材、老板的一手想法、以及左侧当前画布中的最新稿件，帮老板一起把文章写好、改透。",
        "【核心协作协议（务必严格遵守）】：",
        "1. 严禁编造事实、数据、实测结果或不存在的引用；素材与老板没给的细节要如实说明或用待补充标注。",
        "2. 当用户只是提问、讨论思路、要你给选题建议时，直接用简洁清晰的中文回复即可，不要输出文章标签。",
        "3. 当需要生成初稿、重写全文、润色、纠错或调整结构并更新左侧画布时，请先用 1~2 句话简要说明你的改动点，然后紧接着用 <article>...</article> 标签包裹**完整更新后的 Markdown 正文**。",
        "4. 当用户明确只划选了一小段文字要求局部改写（且你只需输出替换片段）时，也可以用 <replace>...</replace> 包裹替换后的局部 Markdown；如果涉及上下文多处调整，直接用 <article>...</article> 输出完整文稿更稳妥。",
        "5. 不要在 <article> 内部重复说明“我已为你修改如下”，直接给干净、可直接发布排版的 Markdown 正文；图片语法请保持原有的 `![说明](url)` 不丢图。",
    ]
    if style_guide:
        sys_parts.append(f"【当前选用的参考风格规范】\n{style_guide}")
    if my_style:
        sys_parts.append(f"【老板沉淀下来的个人写作习惯（最高优先级遵守）】\n{my_style}")

    messages: List[Dict[str, Any]] = [{"role": "system", "content": "\n\n".join(sys_parts)}]

    # 只带最近 8 轮对话历史，避免长上下文膨胀
    history = (proj.get("messages") or [])[-16:]
    for h in history:
        role = h.get("role")
        txt = str(h.get("text") or "").strip()
        if role in ("user", "assistant") and txt:
            messages.append({"role": role, "content": txt})

    # 拼装当前工作区实时快照 + 素材 + 本条用户消息
    cur_title = req.current_title if req.current_title is not None else str(proj.get("title") or "未命名文章")
    cur_content = req.current_content if req.current_content is not None else str(proj.get("content") or "")

    ctx_blocks: List[str] = [f"【当前画布标题】{cur_title}"]
    if cur_content.strip():
        ctx_blocks.append(f"【当前左侧画布最新正文（Markdown）】\n```markdown\n{cur_content[:18000]}\n```")
    else:
        ctx_blocks.append("【当前左侧画布】目前为空白草稿。")

    sources = proj.get("sources") or []
    text_sources = [s for s in sources if s.get("kind") != "image" and str(s.get("content") or "").strip()]
    if text_sources:
        src_lines = []
        for idx, s in enumerate(text_sources[:8], 1):
            meta = f"（来源：{s['url']}）" if s.get("url") else ""
            src_lines.append(f"### 素材 {idx}：{s.get('title', '未命名')}{meta}\n{str(s.get('content') or '')[:5500]}")
        ctx_blocks.append("【已投喂文本/链接/文档素材】\n" + "\n\n".join(src_lines))

    img_sources = [s for s in sources if s.get("kind") == "image"]
    if img_sources:
        img_lines = [f"- {s.get('title', '图片')} -> `/canvas/projects/{proj['id']}/image?path={s.get('path', '')}`" for s in img_sources]
        ctx_blocks.append("【已上传图片素材列表（如需插进正文可用此 Markdown 图片链接）】\n" + "\n".join(img_lines))

    if req.selection.strip():
        ctx_blocks.append(f"【老板划选的重点片段】\n{req.selection.strip()}")

    ctx_blocks.append(f"【老板本轮指令】\n{req.message.strip()}")
    user_text = "\n\n".join(ctx_blocks)

    # 若附带图片（显式随消息发送的，或画布里图片素材不多时一并附上），构建多模态 content
    attached_uris: List[str] = []
    seen_paths: set[str] = set()
    for p in (req.image_paths or []):
        if p and p not in seen_paths:
            seen_paths.add(p)
            uri = _encode_image_data_uri(p)
            if uri:
                attached_uris.append(uri)
    # 如果用户本条没单选图片但素材库里有新图片且消息里提到“图/截图”，附前 3 张素材图
    if not attached_uris and img_sources and any(k in req.message for k in ("图", "截图", "画面", "照片", "看下", "看看")):
        for s in img_sources[-3:]:
            p = str(s.get("path") or "")
            if p and p not in seen_paths:
                seen_paths.add(p)
                uri = _encode_image_data_uri(p)
                if uri:
                    attached_uris.append(uri)

    if attached_uris:
        content_parts: List[Dict[str, Any]] = [{"type": "text", "text": user_text}]
        for uri in attached_uris[:4]:
            content_parts.append({"type": "image_url", "image_url": {"url": uri}})
        messages.append({"role": "user", "content": content_parts})
    else:
        messages.append({"role": "user", "content": user_text})

    return messages


def _split_tagged_output(raw: str) -> Tuple[str, Optional[str], Optional[str]]:
    """从完整模型输出中提取 (chat_text, article_md, replace_md)。"""
    text = (raw or "").strip()
    article_md: Optional[str] = None
    replace_md: Optional[str] = None

    m_art = re.search(r"<article>\s*([\s\S]*?)\s*</article>", text)
    if m_art:
        article_md = m_art.group(1).strip()
        text = (text[:m_art.start()] + text[m_art.end():]).strip()

    m_rep = re.search(r"<replace>\s*([\s\S]*?)\s*</replace>", text)
    if m_rep:
        replace_md = m_rep.group(1).strip()
        text = (text[:m_rep.start()] + text[m_rep.end():]).strip()

    return text, article_md, replace_md


@router.post("/canvas/projects/{pid}/chat")
async def canvas_chat(pid: str, req: CanvasChatRequest):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    if not req.message.strip():
        return JSONResponse({"ok": False, "error": "消息不能为空"}, status_code=400)

    # 先同步前端发来的最新编辑区状态，防止丢未保存的手改
    if req.current_title is not None:
        proj["title"] = req.current_title.strip() or proj.get("title") or "未命名文章"
    if req.current_content is not None:
        proj["content"] = req.current_content
    if req.model:
        proj["model"] = req.model.strip()
    if req.style is not None:
        proj["style"] = req.style.strip()
    proj["use_my_style"] = bool(req.use_my_style)

    messages = _build_copilot_messages(proj, req)
    eff_model = (req.model or proj.get("model") or "").strip()

    def _sse(obj: Dict[str, Any]) -> str:
        return "data: " + json.dumps(obj, ensure_ascii=False) + "\n\n"

    loop = asyncio.get_running_loop()
    q: asyncio.Queue[Optional[Tuple[str, str]]] = asyncio.Queue()

    def _worker() -> None:
        try:
            for item in stream_multimodal_chat(messages, model=eff_model, temperature=0.45, max_tokens=6000, timeout=150):
                loop.call_soon_threadsafe(q.put_nowait, item)
        except Exception as e:
            loop.call_soon_threadsafe(q.put_nowait, ("error", str(e)))
        finally:
            loop.call_soon_threadsafe(q.put_nowait, None)

    threading.Thread(target=_worker, daemon=True).start()

    async def gen():
        raw_full = ""
        used_model = eff_model
        # 简单流式状态机：识别 <article> ... </article> 实时推送左侧画布
        mode = "chat"  # chat | article | replace
        buf = ""
        has_err = False

        def _flush_mode(m: str, chunk: str):
            if not chunk:
                return []
            if m == "article":
                return [_sse({"type": "article_delta", "text": chunk})]
            if m == "chat":
                return [_sse({"type": "chat_delta", "text": chunk})]
            return []

        while True:
            item = await q.get()
            if item is None:
                break
            kind, val = item
            if kind == "model":
                used_model = val
                yield _sse({"type": "model", "model": val})
            elif kind == "reasoning":
                yield _sse({"type": "reasoning", "text": val})
            elif kind == "error":
                has_err = True
                yield _sse({"type": "error", "msg": val})
            elif kind == "content":
                raw_full += val
                buf += val
                while buf:
                    if mode == "chat":
                        idx_a = buf.find("<article>")
                        idx_r = buf.find("<replace>")
                        candidates = [(i, tag) for i, tag in ((idx_a, "article"), (idx_r, "replace")) if i >= 0]
                        if candidates:
                            idx, tag = min(candidates, key=lambda x: x[0])
                            for ev in _flush_mode("chat", buf[:idx]):
                                yield ev
                            buf = buf[idx + len(f"<{tag}>"):]
                            mode = tag
                            if tag == "article":
                                yield _sse({"type": "article_start"})
                        else:
                            # 保留末尾最多 10 个字符以防标签被截断
                            safe = max(0, len(buf) - 10)
                            for ev in _flush_mode("chat", buf[:safe]):
                                yield ev
                            buf = buf[safe:]
                            break
                    elif mode == "article":
                        idx_end = buf.find("</article>")
                        if idx_end >= 0:
                            for ev in _flush_mode("article", buf[:idx_end]):
                                yield ev
                            buf = buf[idx_end + len("</article>"):]
                            mode = "chat"
                        else:
                            safe = max(0, len(buf) - 11)
                            for ev in _flush_mode("article", buf[:safe]):
                                yield ev
                            buf = buf[safe:]
                            break
                    elif mode == "replace":
                        idx_end = buf.find("</replace>")
                        if idx_end >= 0:
                            buf = buf[idx_end + len("</replace>"):]
                            mode = "chat"
                        else:
                            break

        if buf and mode in ("chat", "article"):
            for ev in _flush_mode(mode, buf):
                yield ev

        if has_err and not raw_full.strip():
            return

        chat_text, article_md, replace_md = _split_tagged_output(raw_full)
        applied_version = ""
        now = time.time()

        if article_md is not None:
            if (proj.get("content") or "").strip():
                _push_version(proj, "AI 改写前备份")
            proj["content"] = article_md
            # 若文中第一行是 # 标题，顺手同步标题（仅当原标题还是未命名时）
            m_h1 = re.match(r"^#\s+(.+)$", article_md.lstrip())
            if m_h1 and (not proj.get("title") or proj.get("title") == "未命名文章"):
                proj["title"] = m_h1.group(1).strip()[:80]
            if not proj.get("initial_ai_draft"):
                proj["initial_ai_draft"] = article_md
            snap = _push_version(proj, "Copilot 生成/更新")
            applied_version = snap["id"]
            if not chat_text:
                chat_text = "已将更新后的文稿同步到左侧画布。"
        elif replace_md is not None and req.selection.strip():
            cur = str(proj.get("content") or "")
            new_body = ""
            if (
                0 <= req.selection_start < req.selection_end <= len(cur)
                and cur[req.selection_start:req.selection_end] == req.selection
            ):
                new_body = cur[:req.selection_start] + replace_md + cur[req.selection_end:]
            elif req.selection in cur:
                new_body = cur.replace(req.selection, replace_md, 1)
            if new_body:
                _push_version(proj, "局部改写前备份")
                proj["content"] = new_body
                snap = _push_version(proj, "Copilot 局部改写")
                applied_version = snap["id"]
                yield _sse({"type": "article_full", "content": new_body})
                if not chat_text:
                    chat_text = "已将选定段落的改写同步到左侧画布。"
            else:
                chat_text = (chat_text + "\n\n" if chat_text else "") + replace_md

        # 保存聊天记录（历史只留轻量文本，不重复存整篇 4000 字）
        user_rec = {
            "id": "m_" + uuid.uuid4().hex[:8],
            "role": "user",
            "text": req.message.strip(),
            "selection": req.selection.strip()[:200] if req.selection.strip() else "",
            "images": [os.path.basename(p) for p in (req.image_paths or []) if p],
            "ts": now,
        }
        asst_rec = {
            "id": "m_" + uuid.uuid4().hex[:8],
            "role": "assistant",
            "text": chat_text or "已完成。",
            "applied_version": applied_version,
            "model": used_model,
            "ts": time.time(),
        }
        proj.setdefault("messages", []).extend([user_rec, asst_rec])
        if len(proj["messages"]) > 60:
            proj["messages"] = proj["messages"][-60:]
        _save(proj)

        yield _sse({
            "type": "done",
            "applied_version": applied_version,
            "assistant_text": asst_rec["text"],
            "model": used_model,
            "project": proj,
        })

    return StreamingResponse(gen(), media_type="text/event-stream")


# ─── 违禁词与 AI 味快速检查 ──────────────────────────────────────────────────

_BANNED_RULES = [
    ("high", "绝对化/广告法高危", ["全网首发", "史上最强", "100%有效", "稳赚不赔", "包治百病", "国家级", "绝对第一", "永久免费"]),
    ("warn", "平台限流/引流敏感", ["加微", "加我微信", "扫码领", "私信领取", "白嫖", "破防", "内幕消息", "必看收藏", "不转不是"]),
    ("style", "常见 AI 套话", ["综上所述", "值得注意的是", "不难发现", "不可否认", "总而言之", "换句话说", "让我们来看看", "在当今时代", "随着科技的发展", "首先", "其次", "最后"]),
    ("style", "大厂黑话", ["赋能", "抓手", "闭环", "降维打击", "组合拳", "生态位", "底层逻辑"]),
]


class CheckRequest(BaseModel):
    content: Optional[str] = None


def run_compliance_scan(text: str) -> Dict[str, Any]:
    lines = (text or "").splitlines()
    findings: List[Dict[str, Any]] = []
    for severity, category, words in _BANNED_RULES:
        for w in words:
            hits: List[Dict[str, Any]] = []
            for ln_no, ln in enumerate(lines, 1):
                if w in ln:
                    hits.append({"line": ln_no, "snippet": ln.strip()[:120]})
            if hits:
                findings.append({
                    "severity": severity,
                    "category": category,
                    "word": w,
                    "count": len(hits),
                    "hits": hits[:5],
                })
    # 检查长破折号与连续机械冒号
    dash_cnt = (text or "").count("——")
    if dash_cnt >= 3:
        findings.append({
            "severity": "style",
            "category": "标点习惯",
            "word": "——（破折号偏多）",
            "count": dash_cnt,
            "hits": [],
        })
    score = max(0, 100 - sum(15 if f["severity"] == "high" else (8 if f["severity"] == "warn" else 4) for f in findings))
    return {"ok": True, "score": score, "findings": findings}


@router.post("/canvas/projects/{pid}/check")
def check_canvas_content(pid: str, req: CheckRequest):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    text = req.content if req.content is not None else str(proj.get("content") or "")
    return run_compliance_scan(text)


# ─── 智能配图与生成 ──────────────────────────────────────────────────────────

class SuggestImagesRequest(BaseModel):
    model: str = ""
    content: Optional[str] = None


class GenCanvasImageRequest(BaseModel):
    prompt: str
    kind: str = "inline"  # cover | inline
    model: str = ""
    provider: str = ""
    size: str = "1024x1024"


@router.post("/canvas/projects/{pid}/suggest-images")
def suggest_canvas_images(pid: str, req: SuggestImagesRequest):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    body = (req.content if req.content is not None else str(proj.get("content") or "")).strip()
    if not body:
        return JSONResponse({"ok": False, "error": "画布正文为空，无法建议配图"}, status_code=400)
    prompt = (
        f"请阅读下面这篇文章，给出：\n"
        f"1) 1 个公众号文章封面图生图提示词（英文或中英混合，画面有质感、无文字水印、适合 16:9 横图）；\n"
        f"2) 2 个正文插图建议（指出建议插在哪个小节或段落后，以及对应的生图提示词）。\n"
        f"只返回严格 JSON 格式：\n"
        f'{{"cover": {{"title": "封面图", "prompt": "..."}}, "inlines": [{{"anchor": "插在某句话或小节后", "caption": "图注", "prompt": "..."}}]}}\n\n'
        f"文章标题：{proj.get('title', '')}\n正文：\n{body[:6000]}"
    )
    try:
        raw = llm_bridge.chat_completion(
            [{"role": "user", "content": prompt}],
            model=(req.model or proj.get("model") or "").strip(),
            temperature=0.4,
            max_tokens=1200,
        )
        m = re.search(r"\{[\s\S]*\}", raw or "")
        parsed = json.loads(m.group(0)) if m else {}
        return {"ok": True, "suggestions": parsed}
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"配图建议生成失败：{e}"}, status_code=500)


def _persist_generated_image(pid: str, url_or_data: str) -> Tuple[str, str]:
    """如果返回 data:image/...;base64,... 则落盘为本地文件并返回 (/canvas/.../image?path=..., local_path)。"""
    s = (url_or_data or "").strip()
    m = re.match(r"^data:image/([a-zA-Z0-9+.-]+);base64,(.+)$", s, re.S)
    if not m:
        return s, ""
    ext_raw = m.group(1).lower().split("+")[0]
    ext = ".jpg" if ext_raw == "jpeg" else f".{ext_raw}"
    raw_bytes = base64.b64decode(m.group(2))
    dst = _uploads_dir(pid) / f"gen_{uuid.uuid4().hex[:10]}{ext}"
    dst.write_bytes(raw_bytes)
    return f"/canvas/projects/{pid}/image?path={dst}", str(dst)


@router.post("/canvas/projects/{pid}/gen-image")
async def gen_canvas_image(pid: str, req: GenCanvasImageRequest):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    if not req.prompt.strip():
        return JSONResponse({"ok": False, "error": "生图提示词不能为空"}, status_code=400)
    eff_model = req.model.strip() or str(settings_store.load_settings().get("default_image_model") or "").strip()
    loop = asyncio.get_running_loop()
    result = await loop.run_in_executor(
        None,
        lambda: image_gen.generate_image(
            prompt=req.prompt.strip(),
            model=eff_model,
            provider_selector=req.provider.strip(),
            size=req.size,
        ),
    )
    if not result or "_runtime_block" not in result:
        return JSONResponse({"ok": False, "error": (result or {}).get("error") or "生图无有效输出"}, status_code=400)
    images = result.get("images") or []
    raw_url = (images[0].get("url") or images[0].get("data_uri") or "") if images else ""
    if not raw_url:
        return JSONResponse({"ok": False, "error": "生图返回无图片"}, status_code=400)

    proxy_url, local_path = _persist_generated_image(pid, raw_url)
    if req.kind == "cover":
        proj["cover_url"] = proxy_url
    if local_path:
        proj.setdefault("sources", []).append({
            "id": "s_" + uuid.uuid4().hex[:8],
            "kind": "image",
            "title": "封面图" if req.kind == "cover" else "AI 配图",
            "path": local_path,
            "purpose": req.kind,
            "added_at": time.time(),
        })
    _save(proj)
    return {"ok": True, "url": proxy_url, "local_path": local_path, "kind": req.kind}


# ─── 个人写作习惯（my_style.md）读取、编辑与对比沉淀 ─────────────────────────

class MyStyleUpdateRequest(BaseModel):
    content: str


class LearnStyleRequest(BaseModel):
    model: str = ""
    content: Optional[str] = None


@router.get("/canvas/my-style")
def get_my_style():
    return {"ok": True, "content": _read_my_style()}


@router.put("/canvas/my-style")
def put_my_style(req: MyStyleUpdateRequest):
    _my_style_path().write_text((req.content or "").strip(), encoding="utf-8")
    return {"ok": True, "content": _read_my_style()}


@router.post("/canvas/projects/{pid}/learn-style")
def learn_style_from_project(pid: str, req: LearnStyleRequest):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    final_body = (req.content if req.content is not None else str(proj.get("content") or "")).strip()
    if len(final_body) < 100:
        return JSONResponse({"ok": False, "error": "正文太短，至少需要 100 字才能提炼写作习惯"}, status_code=400)
    ai_draft = str(proj.get("initial_ai_draft") or "").strip()
    existing_style = _read_my_style()

    prompt = (
        "你是一个资深写作风格分析师。请根据老板当前的定稿文章"
        + ("（并对比最早的 AI 初稿，重点挖掘老板亲手改写了什么、删掉了哪些套话、保留了哪种语气与句式）" if ai_draft else "")
        + "，结合已有的个人写作习惯档案，输出一份精炼、可直接作为 System Prompt 注入的《老板个人写作习惯规范》（Markdown 条目式，不超过 600 字）。\n"
        "包含：1) 开头与结尾习惯；2) 句式节奏与口语特征；3) 绝对禁用词与反感表达；4) 真实感与观点表达偏好。\n只输出更新后的完整习惯清单。\n\n"
        f"【现有习惯档案】\n{existing_style or '（暂无）'}\n\n"
        + (f"【最初 AI 初稿（参考对照）】\n{ai_draft[:4000]}\n\n" if ai_draft else "")
        + f"【老板最新定稿】\n{final_body[:5000]}"
    )
    try:
        updated = llm_bridge.chat_completion(
            [{"role": "user", "content": prompt}],
            model=(req.model or proj.get("model") or "").strip(),
            temperature=0.3,
            max_tokens=1500,
        )
        clean = (updated or "").strip()
        if not clean:
            return JSONResponse({"ok": False, "error": "模型未能生成有效习惯总结"}, status_code=500)
        _my_style_path().write_text(clean, encoding="utf-8")
        return {"ok": True, "content": clean}
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"提炼写作习惯失败：{e}"}, status_code=500)
