# -*- coding: utf-8 -*-
"""分步创作工作台 API（独立自包含版，运行于 ai-content 自身服务内）。"""
from __future__ import annotations

import asyncio
import json
import mimetypes
import os
import sys
import tempfile
import time
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from . import db, gzh_themes, image_gen, llm_bridge, search_gather, settings_store
from .paths import project_root, studio_dir
from .wechat_search import search_wechat
from .xhs.pipeline import regen_single_page, run_image_batch_step

router = APIRouter()


def _project_path(pid: str) -> Path:
    return studio_dir() / f"{pid}.json"


def _load(pid: str):
    p = _project_path(pid)
    if not p.exists():
        return None
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None


def _save(proj: dict):
    proj["updated"] = time.time()
    _project_path(proj["id"]).write_text(json.dumps(proj, ensure_ascii=False), encoding="utf-8")


def _write_catalog_file(selected_model: str = "") -> str:
    cat = llm_bridge.build_model_catalog(selected_model)
    fd, path = tempfile.mkstemp(suffix=".json", prefix="llm_catalog_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(cat, f, ensure_ascii=False)
    return path


async def _call_studio(args: list) -> dict:
    env = dict(os.environ)
    env["PYTHONUTF8"] = "1"
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [sys.executable, "-m", "studio_json", *args]
    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            cwd=str(project_root()),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
            env=env,
            limit=64 * 1024 * 1024,
        )
        out, _ = await proc.communicate()
    except Exception as e:
        return {"type": "error", "msg": str(e)}
    text = out.decode("utf-8", errors="replace")
    result = None
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                result = json.loads(line)
            except Exception:
                pass
    return result or {"type": "error", "msg": "studio 子进程无有效输出：" + text[-400:]}


def _summary(proj: dict) -> dict:
    nodes = proj.get("nodes", [])
    done = proj.get("done", [])
    return {
        "id": proj["id"],
        "title": proj.get("title", ""),
        "workflow": proj.get("workflow", ""),
        "name": proj.get("name", ""),
        "current": proj.get("current", 0),
        "total": len(nodes),
        "done_count": sum(1 for d in done if d),
        "updated": proj.get("updated", 0),
    }


@router.get("/studio/browse-dirs")
def browse_dirs(path: str = ""):
    """Web 端本地目录浏览（替代桌面壳原生目录弹窗）。"""
    target = Path(path).expanduser() if path.strip() else Path.home()
    if not target.exists() or not target.is_dir():
        target = Path.home()
    try:
        target = target.resolve()
        dirs = []
        for entry in sorted(target.iterdir(), key=lambda p: p.name.lower()):
            if entry.is_dir() and not entry.name.startswith("."):
                dirs.append({"name": entry.name, "path": str(entry)})
    except Exception as e:
        return {"ok": False, "error": str(e), "current": str(target), "parent": str(target.parent), "dirs": []}
    parent = str(target.parent) if target.parent != target else ""
    return {"ok": True, "current": str(target), "parent": parent, "dirs": dirs[:200]}


@router.get("/studio/projects")
def list_projects():
    items = []
    for f in studio_dir().glob("*.json"):
        try:
            items.append(_summary(json.loads(f.read_text(encoding="utf-8"))))
        except Exception:
            pass
    items.sort(key=lambda x: x.get("updated", 0), reverse=True)
    return {"projects": items}


class NewProjectRequest(BaseModel):
    workflow: str = "content_pipeline"
    inputs: dict = {}
    title: str = ""


@router.post("/studio/projects")
async def new_project(req: NewProjectRequest):
    res = await _call_studio(["--wf", req.workflow, "--inputs", json.dumps(req.inputs, ensure_ascii=False)])
    if res.get("type") != "init":
        return JSONResponse({"ok": False, "error": res.get("msg", "初始化失败")}, status_code=400)
    pid = uuid.uuid4().hex[:12]
    title = req.title.strip() or (req.inputs.get("topic") or res.get("name", "新创作"))
    acc = db.get_primary_account() if req.workflow == "content_pipeline" else None
    state = res.get("state", {})
    if acc:
        state.setdefault("data", {})
        if not (state["data"].get("material") or "").strip():
            banned = "、".join(acc.get("banned_words") or [])
            guide = (
                f"【账号定位】{acc.get('niche')}\n"
                f"【目标读者】{acc.get('audience')}\n"
                + (f"【禁用词（严格避开 AI 套话）】{banned}\n" if banned else "")
                + (f"【文末互动引导】{acc.get('footer_template')}" if acc.get("footer_template") else "")
            ).strip()
            if guide:
                state["data"]["material"] = guide
    proj = {
        "id": pid,
        "title": title[:60],
        "workflow": req.workflow,
        "name": res.get("name", ""),
        "inputs": req.inputs,
        "nodes": res.get("nodes", []),
        "state": state,
        "style": (acc.get("default_style") if acc else "") or "",
        "theme": (acc.get("default_theme") if acc else "") or "moyu_green",
        "account_id": acc["id"] if acc else "",
        "current": 0,
        "done": [False] * len(res.get("nodes", [])),
        "created": time.time(),
        "updated": time.time(),
    }
    _save(proj)
    return {"ok": True, "project": proj}


@router.get("/studio/projects/{pid}")
def get_project(pid: str):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    return {"ok": True, "project": proj}


@router.delete("/studio/projects/{pid}")
def delete_project(pid: str):
    p = _project_path(pid)
    if p.exists():
        try:
            p.unlink()
        except Exception:
            pass
    return {"ok": True}


class RenameRequest(BaseModel):
    title: str = ""


@router.post("/studio/projects/{pid}/rename")
def rename_project(pid: str, req: RenameRequest):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    t = req.title.strip()
    if not t:
        return JSONResponse({"ok": False, "error": "标题不能为空"}, status_code=400)
    proj["title"] = t[:60]
    proj.setdefault("inputs", {})["topic"] = t[:60]
    _save(proj)
    return {"ok": True, "title": proj["title"]}


class StudioSettingsRequest(BaseModel):
    model: str = ""
    style: str = ""
    theme: str = ""
    step_models: dict = {}


@router.post("/studio/projects/{pid}/settings")
def update_studio_settings(pid: str, req: StudioSettingsRequest):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    proj["model"] = req.model.strip()
    proj["style"] = req.style.strip()
    if req.theme.strip():
        proj["theme"] = req.theme.strip()
    proj["step_models"] = req.step_models or {}
    _save(proj)
    return {"ok": True}


class RenderThemeRequest(BaseModel):
    theme: str = "moyu_green"
    author: str = ""
    include_footer: bool = True


@router.post("/studio/projects/{pid}/render-theme")
def render_project_theme(pid: str, req: RenderThemeRequest):
    """秒级切换公众号排版主题并更新 state.layout.html（无需重跑 LLM）。"""
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    st = proj.setdefault("state", {})
    md_text = str(st.get("final") or st.get("styled") or st.get("draft") or "").strip()
    if not md_text:
        return JSONResponse({"ok": False, "error": "暂无可排版正文，请先完成撰稿/定稿步"}, status_code=400)
    theme_id = req.theme.strip() or proj.get("theme") or "moyu_green"
    acc = db.get_primary_account()
    footer = acc.get("footer_template", "") if req.include_footer else ""
    if theme_id in gzh_themes.THEME_SPECS:
        html_out = gzh_themes.render_wechat_theme_html(md_text, theme_id=theme_id, author=req.author.strip(), footer=footer)
    else:
        from . import wechat_mp
        html_out = wechat_mp.markdown_to_wechat_html(md_text, style=theme_id, author=req.author.strip(), footer=footer)
    layout = st.get("layout") if isinstance(st.get("layout"), dict) else {}
    layout = dict(layout)
    layout["html"] = html_out
    layout["markdown"] = md_text
    layout["theme"] = theme_id
    st["layout"] = layout
    proj["theme"] = theme_id
    nodes = proj.get("nodes") or []
    for idx, nd in enumerate(nodes):
        if nd.get("id") == "format" or nd.get("tool") == "content.format":
            done = proj.get("done") or [False] * len(nodes)
            if idx < len(done):
                done[idx] = True
            proj["done"] = done
            if proj.get("current", 0) <= idx:
                proj["current"] = idx + 1
            break
    _save(proj)
    return {"ok": True, "theme": theme_id, "html": html_out, "layout": layout}


class ImportLocalRequest(BaseModel):
    dir: str = ""


@router.post("/studio/projects/{pid}/import-local")
def import_local(pid: str, req: ImportLocalRequest):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    d = req.dir.strip()
    if not d or not os.path.isdir(d):
        return JSONResponse({"ok": False, "error": "目录不存在或不可访问"}, status_code=400)
    images = proj.setdefault("state", {}).setdefault("images", [])
    existing_img = {i.get("path") for i in images if isinstance(i, dict)}
    blocks, files, imgs_added = search_gather.read_local_dir(d, existing_img)
    if not blocks and not imgs_added:
        return JSONResponse({"ok": False, "error": "目录里没读到文章(txt/md/pdf/docx/pptx)或图片"}, status_code=400)
    if imgs_added:
        images.extend(imgs_added)
    if blocks:
        local_block = "【本地素材】\n\n" + "\n\n".join(blocks)
        data = proj.setdefault("state", {}).setdefault("data", {})
        existing = (data.get("material") or "").strip()
        data["material"] = (existing + "\n\n" + local_block) if existing else local_block
        done = proj.get("done") or [False] * len(proj.get("nodes", []))
        if done:
            done[0] = True
        proj["done"] = done
        if proj.get("current", 0) < 1:
            proj["current"] = 1
    _save(proj)
    return {
        "ok": True,
        "files": files,
        "count": len(files),
        "images": [i["name"] for i in imgs_added],
        "image_count": len(imgs_added),
    }


class ImportUrlsRequest(BaseModel):
    urls: str = ""


@router.post("/studio/projects/{pid}/import-urls")
async def import_urls(pid: str, req: ImportUrlsRequest):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    urls_text = (req.urls or "").strip()
    if not urls_text:
        return JSONResponse({"ok": False, "error": "请粘贴至少一个 http(s) 链接"}, status_code=400)
    res = await _call_studio(["--fetch", json.dumps({"urls": urls_text}, ensure_ascii=False)])
    if res.get("type") != "fetch":
        return JSONResponse({"ok": False, "error": res.get("msg", "抓取失败")}, status_code=500)
    material = res.get("material", "")
    if not material:
        return JSONResponse({"ok": False, "error": "未能抓取到任何内容"}, status_code=500)
    data = proj.setdefault("state", {}).setdefault("data", {})
    existing = (data.get("material") or "").strip()
    block = "【网络素材】\n\n" + material
    data["material"] = (existing + "\n\n" + block) if existing else block
    done = proj.get("done") or [False] * len(proj.get("nodes", []))
    if done:
        done[0] = True
    proj["done"] = done
    if proj.get("current", 0) < 1:
        proj["current"] = 1
    _save(proj)
    return {"ok": True, "count": res.get("count", 0), "failed": res.get("failed", 0), "total": res.get("total", 0)}


@router.get("/studio/projects/{pid}/images")
def list_studio_images(pid: str):
    proj = _load(pid)
    if proj is None:
        return {"images": []}
    imgs = [i for i in (proj.get("state", {}).get("images") or []) if isinstance(i, dict)]
    return {"images": [{"name": i.get("name", ""), "path": i.get("path", "")} for i in imgs]}


@router.get("/studio/projects/{pid}/image")
def get_studio_image(pid: str, path: str):
    proj = _load(pid)
    if proj is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    allowed = {i.get("path") for i in (proj.get("state", {}).get("images") or []) if isinstance(i, dict)}
    if path not in allowed:
        raise HTTPException(status_code=403, detail="图片不在项目素材库")
    p = Path(path)
    if not p.is_file():
        raise HTTPException(status_code=404, detail="图片不存在")
    mime, _ = mimetypes.guess_type(str(p))
    return FileResponse(p, media_type=mime or "image/png")


class RemoveImageRequest(BaseModel):
    path: str = ""


@router.post("/studio/projects/{pid}/remove-image")
def remove_studio_image(pid: str, req: RemoveImageRequest):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    imgs = [i for i in (proj.get("state", {}).get("images") or []) if isinstance(i, dict)]
    proj.setdefault("state", {})["images"] = [i for i in imgs if i.get("path") != req.path]
    _save(proj)
    return {"ok": True, "images": proj["state"]["images"]}


class StepRequest(BaseModel):
    index: int = -1
    feedback: str = ""
    model: str = ""
    style: str = ""
    node_model: str = ""


@router.post("/studio/projects/{pid}/step")
async def run_step(pid: str, req: StepRequest):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    if req.model.strip():
        proj["model"] = req.model.strip()
    proj["style"] = req.style.strip()
    _save(proj)
    nodes = proj.get("nodes", [])
    index = req.index if req.index >= 0 else proj.get("current", 0)
    if index < 0 or index >= len(nodes):
        return JSONResponse({"ok": False, "error": "步骤越界"}, status_code=400)
    node = nodes[index]
    proj.setdefault("step_models", {})[node.get("id", str(index))] = req.node_model.strip()
    _save(proj)
    _effective_model = req.node_model.strip() or proj.get("model", "")

    def _sse(obj):
        return f"data: {json.dumps(obj, ensure_ascii=False)}\n\n"

    def _mark_done():
        done = proj.get("done", [False] * len(nodes))
        if index < len(done):
            done[index] = True
        proj["done"] = done
        if index >= proj.get("current", 0):
            proj["current"] = index + 1
        _save(proj)

    _tool = (node.get("tool") or "").strip()
    _nid = (node.get("id") or "").strip()
    _writes = (node.get("writes") or _nid).strip()
    is_gather_data = (
        node.get("type") == "data"
        and (
            _nid == "collect"
            or _writes == "data"
            or _tool in ("content.gather", "gather")
            or _tool.endswith(".gather")
        )
    )
    if is_gather_data:
        async def gen_data():
            yield _sse({"type": "begin", "index": index, "node": node.get("id"), "writes": "data"})
            material = await search_gather.gather_material((proj.get("inputs") or {}).get("topic", ""))
            proj.setdefault("state", {}).setdefault("data", {})["material"] = material
            _mark_done()
            yield _sse({"type": "step", "index": index, "writes": "data", "output": material,
                        "current": proj["current"], "done": proj["done"]})
            yield _sse({"type": "done"})
        return StreamingResponse(gen_data(), media_type="text/event-stream")

    if node.get("type") == "image_batch":
        pick = req.node_model.strip()
        if not pick:
            _st = proj.get("state") or {}
            if _st.get("_cover_model"):
                pick = f"{_st['_cover_model']}|{_st.get('_cover_provider', '')}"
        if not pick:
            pick = str(settings_store.load_settings().get("default_image_model") or "").strip()
        if not pick:
            return JSONResponse({"ok": False,
                "error": "请先在右侧选择一个配图模型（或在「账号与设置」配置默认生图模型）"},
                status_code=400)
        _m, _p = ((pick.split("|", 1) + [""])[:2]) if pick else ("", "")
        return await run_image_batch_step(proj, node, index, _m, _p, _save, _mark_done, _sse)

    state_payload = dict(proj.get("state") or {})
    if proj.get("theme"):
        state_payload["_theme"] = proj["theme"]
    if proj.get("style"):
        state_payload["_style"] = proj["style"]
    fd, tmp = tempfile.mkstemp(suffix=".json", prefix="studio_state_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(state_payload, f, ensure_ascii=False)

    async def gen_agent():
        env = dict(os.environ)
        env["PYTHONUTF8"] = "1"
        env["PYTHONIOENCODING"] = "utf-8"
        catalog_path = _write_catalog_file(_effective_model)
        env["LLM_CATALOG_FILE"] = catalog_path
        cmd = [sys.executable, "-m", "studio_json", "--step", "--state", tmp, "--index", str(index), "--stream"]
        if req.feedback.strip():
            cmd += ["--feedback", req.feedback.strip()]
        _style = (req.style or proj.get("style") or "").strip()
        if _style:
            cmd += ["--style", _style]

        def _cleanup():
            for _p in (tmp, catalog_path):
                try:
                    os.remove(_p)
                except Exception:
                    pass

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(project_root()),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.STDOUT,
                env=env,
                limit=64 * 1024 * 1024,
            )
        except Exception as e:
            yield _sse({"type": "error", "msg": str(e)})
            _cleanup()
            return
        assert proc.stdout is not None
        try:
            async for raw in proc.stdout:
                line = raw.decode("utf-8", errors="replace").strip()
                if not line or not line.startswith("{"):
                    continue
                try:
                    obj = json.loads(line)
                except Exception:
                    continue
                if obj.get("type") == "step":
                    proj["state"] = obj.get("state", proj.get("state"))
                    _mark_done()
                    light = {k: v for k, v in obj.items() if k != "state"}
                    light["current"] = proj["current"]
                    light["done"] = proj["done"]
                    yield _sse(light)
                else:
                    yield _sse(obj)
            await proc.wait()
        finally:
            _cleanup()
        yield _sse({"type": "done"})

    return StreamingResponse(gen_agent(), media_type="text/event-stream")


@router.get("/studio/styles")
async def studio_styles():
    res = await _call_studio(["--styles"])
    return {"styles": res.get("styles", []) if res.get("type") == "styles" else []}


@router.get("/studio/search-wechat")
async def studio_search_wechat(q: str = "", n: int = 8):
    return {"articles": await search_wechat(q, n)}


@router.get("/studio/prompts")
async def studio_prompts(style: str = ""):
    args = ["--get-prompts"]
    if style.strip():
        args += ["--style", style.strip()]
    res = await _call_studio(args)
    if res.get("type") == "prompts":
        return {"roles": res.get("roles", []), "styles": res.get("styles", []), "style": res.get("style", "")}
    return {"roles": [], "styles": [], "style": ""}


class SaveStyleRequest(BaseModel):
    name: str = ""
    prompts: dict = {}


@router.post("/studio/save-style")
async def save_custom_style(req: SaveStyleRequest):
    if not req.name.strip():
        return JSONResponse({"ok": False, "error": "请填风格名"}, status_code=400)
    fd, tmp = tempfile.mkstemp(suffix=".json", prefix="style_save_")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump({"name": req.name.strip(), "prompts": req.prompts or {}}, f, ensure_ascii=False)
    try:
        res = await _call_studio(["--save-style", "--file", tmp])
    finally:
        try:
            os.remove(tmp)
        except Exception:
            pass
    if res.get("type") == "saved":
        return {"ok": True, "slug": res.get("slug"), "name": res.get("name"), "overrides": res.get("overrides", [])}
    return JSONResponse({"ok": False, "error": res.get("msg", "保存失败")}, status_code=500)


@router.get("/studio/text-models")
def text_models():
    return {"models": llm_bridge.list_text_models(), "current": llm_bridge.current_model()}


@router.get("/studio/image-models")
def image_models():
    return {"models": llm_bridge.list_image_models()}


class CoverRequest(BaseModel):
    prompt: str
    model: str = ""
    provider: str = ""
    size: str = "1024x1024"


@router.post("/studio/projects/{pid}/cover")
async def gen_cover(pid: str, req: CoverRequest):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    if not req.prompt.strip():
        return JSONResponse({"ok": False, "error": "配图提示词为空"}, status_code=400)
    eff_img_model = req.model.strip() or str(settings_store.load_settings().get("default_image_model") or "").strip()
    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: image_gen.generate_image(
            prompt=req.prompt.strip(),
            model=eff_img_model,
            provider_selector=req.provider.strip(),
            size=req.size,
        ),
    )
    if not result or "_runtime_block" not in result:
        return {"ok": False, "error": (result or {}).get("error") or "生图无有效输出"}
    images = result.get("images", [])
    url = (images[0].get("url") or images[0].get("data_uri") or "") if images else ""
    if not url:
        return {"ok": False, "error": "生图返回无图片"}
    proj.setdefault("state", {})["_cover"] = url
    if req.model.strip():
        proj.setdefault("state", {})["_cover_model"] = req.model.strip()
    if req.provider.strip():
        proj.setdefault("state", {})["_cover_provider"] = req.provider.strip()
    _save(proj)
    return {"ok": True, "image": url, "model": result.get("model"), "provider": result.get("provider")}


class XhsRegenRequest(BaseModel):
    page_index: int
    model: str = ""
    provider: str = ""


class XhsLabelsRequest(BaseModel):
    page_index: int
    labels: dict
    palette: str = ""


@router.post("/studio/projects/{pid}/xhs-regen")
def xhs_regen(pid: str, req: XhsRegenRequest):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    if proj.get("workflow") != "xhs_pipeline":
        return JSONResponse({"ok": False, "error": "仅小红书项目支持图组重生成"}, status_code=400)
    model = req.model.strip() or (proj.get("state") or {}).get("_cover_model", "")
    provider = req.provider.strip() or (proj.get("state") or {}).get("_cover_provider", "")
    if not model:
        return JSONResponse({"ok": False, "error": "请先在图组步选择一个配图模型（自动检测已禁用）"}, status_code=400)
    result = regen_single_page(proj, req.page_index, model, provider)
    if result.get("ok"):
        _save(proj)
    return result


@router.post("/studio/projects/{pid}/xhs-labels")
def xhs_labels(pid: str, req: XhsLabelsRequest):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    if proj.get("workflow") != "xhs_pipeline":
        return JSONResponse({"ok": False, "error": "仅小红书项目支持编辑图组文字"}, status_code=400)
    labels = req.labels or {}
    clean_labels = {
        "title": str(labels.get("title") or "")[:80],
        "subtitle": str(labels.get("subtitle") or "")[:120],
        "header": str(labels.get("header") or "")[:40],
        "points": [str(x or "")[:120] for x in (labels.get("points") or []) if str(x or "").strip()][:8],
    }
    state = proj.setdefault("state", {})
    summary = state.setdefault("images_summary", [])
    slot = next((r for r in summary if isinstance(r, dict) and r.get("index") == req.page_index), None)
    if slot is None:
        slot = {"index": req.page_index, "type": "content", "status": "pending"}
        summary.append(slot)
    slot["labels"] = clean_labels
    if req.palette.strip():
        slot["palette"] = req.palette.strip()
    _save(proj)
    return {"ok": True, "labels": clean_labels, "palette": slot.get("palette", "")}


class EditRequest(BaseModel):
    index: int
    content: str


@router.post("/studio/projects/{pid}/edit")
def edit_step(pid: str, req: EditRequest):
    proj = _load(pid)
    if proj is None:
        return JSONResponse({"ok": False, "error": "项目不存在"}, status_code=404)
    nodes = proj.get("nodes", [])
    if req.index < 0 or req.index >= len(nodes):
        return JSONResponse({"ok": False, "error": "步骤越界"}, status_code=400)
    nd = nodes[req.index]
    writes = nd.get("writes") or nd.get("id")
    if nd.get("type") == "data" or writes == "data":
        proj.setdefault("state", {}).setdefault("data", {})["material"] = req.content
    else:
        proj.setdefault("state", {})[writes] = req.content
    done = proj.get("done", [False] * len(nodes))
    if req.index < len(done):
        done[req.index] = True
    proj["done"] = done
    if req.index >= proj.get("current", 0):
        proj["current"] = req.index + 1
    _save(proj)
    return {"ok": True}
