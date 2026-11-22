# -*- coding: utf-8 -*-
"""小红书图组成片管线（封面先行 → 内容页用封面作参考图 → SSE 流式回传）。"""
import asyncio
import base64
import logging
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, Callable, Dict, Optional, Tuple

from fastapi.responses import StreamingResponse

from server.image_gen import generate_image
from server.paths import studio_dir
from .page_planner import parse_pages, page_label, extract_labels
from .prompts import build_image_prompt

logger = logging.getLogger(__name__)

_MAX_CONCURRENT = 6
_DEFAULT_SIZE = "1024x1024"


def _project_asset_dir(pid: str) -> Path:
    d = studio_dir() / pid
    d.mkdir(parents=True, exist_ok=True)
    return d


def _img_url(pid: str, path: str) -> str:
    return f"/studio/projects/{pid}/image?path={urllib.request.quote(path, safe='')}"


def _save_generated_image(img_src: str, asset_dir: Path, filename: str) -> str:
    target = asset_dir / filename
    if img_src.startswith("data:"):
        _, b64 = img_src.split(",", 1)
        target.write_bytes(base64.b64decode(b64))
    else:
        with urllib.request.urlopen(img_src, timeout=60) as r:
            target.write_bytes(r.read())
    return str(target)


def _gen_one(page: dict, topic: str, model: str, provider: str, reference_path: str = "",
             palette: str = "warm", asset_dir: Optional[Path] = None, pid: str = "") -> Tuple[Optional[str], Optional[str]]:
    prompt = build_image_prompt(page, topic, palette=palette)
    if asset_dir is not None:
        try:
            (asset_dir / f"xhs_{page['index']}_prompt.md").write_text(
                f"<!-- 页 {page['index']} ({page.get('type', 'content')}) 生图 prompt，可改后单页重生 -->\n{prompt}",
                encoding="utf-8")
        except Exception:
            pass
    try:
        result = generate_image(
            prompt=prompt,
            model=model or "",
            provider_selector=provider or "",
            size=_DEFAULT_SIZE,
            image_path=reference_path,
        )
    except Exception as e:
        logger.exception("生图调用异常 page=%s", page.get("index"))
        return None, f"生图调用异常：{e}"
    if "error" in result:
        return None, result["error"]
    images = result.get("images") or []
    if not images:
        return None, "生图返回无图片"
    item = images[0]
    img = item.get("url") or item.get("data_uri")
    if not img:
        return None, "生图返回无图片数据"
    return img, None


def _gen_and_save(page: dict, topic: str, model: str, provider: str,
                  reference_path: str, asset_dir: Path, filename: str,
                  palette: str = "warm", pid: str = "") -> Tuple[Optional[str], Optional[str]]:
    img_src, err = _gen_one(page, topic, model, provider, reference_path,
                            palette=palette, asset_dir=asset_dir, pid=pid)
    if err:
        return None, err
    try:
        return _save_generated_image(img_src, asset_dir, filename), None
    except Exception as e:
        return None, f"落盘失败：{e}"


def _upsert_image(images_state: list, existing_paths: set, page: dict, path: str):
    if path in existing_paths:
        for i in images_state:
            if isinstance(i, dict) and i.get("path") == path:
                i["page_index"] = page["index"]
                i["kind"] = page["type"]
                break
        return
    images_state.append({"name": page_label(page), "path": path,
                         "page_index": page["index"], "kind": page["type"]})
    existing_paths.add(path)


async def run_image_batch_step(proj: dict, node: dict, index: int,
                               img_model: str, img_provider: str,
                               _save: Callable, _mark_done: Callable, _sse: Callable,
                               palette: str = "warm") -> StreamingResponse:
    pid = proj["id"]
    state = proj.setdefault("state", {})
    outline = state.get("outline") or ""
    topic = (proj.get("inputs") or {}).get("topic") or state.get("topic") or ""
    pages = parse_pages(outline)

    async def gen():
        if not pages:
            yield _sse({"type": "error", "msg": "页大纲为空，请先完成「选题大纲」步"})
            return
        yield _sse({"type": "begin", "index": index, "node": node.get("id"), "writes": "images",
                    "total": len(pages)})

        asset_dir = _project_asset_dir(pid)
        images_state = state.setdefault("images", [])
        existing_paths = {i.get("path") for i in images_state if isinstance(i, dict)}
        loop = asyncio.get_event_loop()
        pool = ThreadPoolExecutor(max_workers=_MAX_CONCURRENT)
        results = [{"index": p["index"], "type": p["type"], "status": "pending",
                    "labels": extract_labels(p), "palette": palette} for p in pages]

        def gen_and_save(page, ref_path=""):
            return _gen_and_save(page, topic, img_model, img_provider, ref_path,
                                 asset_dir, f"xhs_{page['index']}.png",
                                 palette=palette, pid=pid)

        try:
            cover_page = next((p for p in pages if p["type"] == "cover"), pages[0])
            yield _sse({"type": "image_progress", "index": cover_page["index"], "phase": "cover",
                        "message": "正在生成封面…"})
            cover_path, err = await loop.run_in_executor(pool, gen_and_save, cover_page, "")
            if err:
                results[cover_page["index"]]["status"] = "error"
                yield _sse({"type": "image_error", "index": cover_page["index"], "phase": "cover", "message": err})
                cover_path = None
            else:
                _upsert_image(images_state, existing_paths, cover_page, cover_path)
                results[cover_page["index"]].update({"status": "done", "path": cover_path})
                _save(proj)
                yield _sse({"type": "image_done", "index": cover_page["index"], "phase": "cover",
                            "image_url": _img_url(pid, cover_path), "path": cover_path,
                            "labels": results[cover_page["index"]]["labels"], "palette": palette})

            other_pages = [p for p in pages if p["index"] != cover_page["index"]]
            if other_pages:
                if cover_path:
                    async def _gen_one_with_page(page, ref):
                        path, e = await loop.run_in_executor(pool, gen_and_save, page, ref)
                        return page, path, e
                    tasks = [asyncio.ensure_future(_gen_one_with_page(p, cover_path)) for p in other_pages]
                    for fut in asyncio.as_completed(tasks):
                        try:
                            p, path, e = await fut
                        except Exception as e:
                            p = next((pg for pg in other_pages if not (results[pg["index"]].get("path") or results[pg["index"]]["status"] in ("done", "error"))), {"index": -1, "type": "content"})
                            path, e = None, str(e)
                        if e:
                            results[p["index"]]["status"] = "error"
                            yield _sse({"type": "image_error", "index": p["index"], "phase": "content", "message": e})
                        else:
                            _upsert_image(images_state, existing_paths, p, path)
                            results[p["index"]].update({"status": "done", "path": path})
                            _save(proj)
                            yield _sse({"type": "image_done", "index": p["index"], "phase": "content",
                                        "image_url": _img_url(pid, path), "path": path,
                                        "labels": results[p["index"]]["labels"], "palette": palette})
                else:
                    yield _sse({"type": "image_progress", "index": -1, "phase": "content",
                                "message": "封面缺失，内容页降级无参考图生成…"})
                    for p in other_pages:
                        path, e = await loop.run_in_executor(pool, gen_and_save, p, "")
                        if e:
                            results[p["index"]]["status"] = "error"
                            yield _sse({"type": "image_error", "index": p["index"], "phase": "content", "message": e})
                        else:
                            _upsert_image(images_state, existing_paths, p, path)
                            results[p["index"]].update({"status": "done", "path": path})
                            _save(proj)
                            yield _sse({"type": "image_done", "index": p["index"], "phase": "content",
                                        "image_url": _img_url(pid, path), "path": path,
                                        "labels": results[p["index"]]["labels"], "palette": palette})

            state["images"] = images_state
            state["images_summary"] = results
            state["_cover_model"] = img_model
            state["_cover_provider"] = img_provider
            _mark_done()
            done_count = sum(1 for r in results if r["status"] == "done")
            yield _sse({"type": "step", "index": index, "writes": "images",
                        "output": f"图组生成完成 {done_count}/{len(pages)}",
                        "current": proj["current"], "done": proj["done"]})
            yield _sse({"type": "batch_finish", "total": len(pages),
                        "completed": done_count, "failed": len(pages) - done_count})
            yield _sse({"type": "done"})
        finally:
            pool.shutdown(wait=False)
            _save(proj)

    return StreamingResponse(gen(), media_type="text/event-stream")


def regen_single_page(proj: dict, page_index: int, img_model: str, img_provider: str,
                      palette: str = "warm") -> Dict[str, Any]:
    pid = proj["id"]
    state = proj.setdefault("state", {})
    pages = parse_pages(state.get("outline") or "")
    page = next((p for p in pages if p["index"] == page_index), None)
    if page is None:
        return {"ok": False, "error": f"找不到第 {page_index} 页"}
    topic = (proj.get("inputs") or {}).get("topic") or state.get("topic") or ""
    asset_dir = _project_asset_dir(pid)
    filename = f"xhs_{page_index}.png"

    reference_path = ""
    if page["type"] != "cover":
        cover_page = next((p for p in pages if p["type"] == "cover"), pages[0] if pages else None)
        if cover_page and cover_page["index"] != page_index:
            cp = asset_dir / f"xhs_{cover_page['index']}.png"
            if cp.exists():
                reference_path = str(cp)

    path, err = _gen_and_save(page, topic, img_model, img_provider, reference_path, asset_dir, filename,
                              palette=palette, pid=pid)
    if err:
        return {"ok": False, "error": err}
    images_state = state.setdefault("images", [])
    existing_paths = {i.get("path") for i in images_state if isinstance(i, dict)}
    _upsert_image(images_state, existing_paths, page, path)
    summary = state.setdefault("images_summary", [])
    slot = next((r for r in summary if r.get("index") == page_index), None)
    keep_labels = slot.get("labels") if isinstance(slot, dict) and slot.get("labels") else extract_labels(page)
    if slot:
        slot.update({"status": "done", "path": path, "labels": keep_labels, "palette": palette})
    return {"ok": True, "image_url": _img_url(pid, path), "path": path,
            "labels": keep_labels, "palette": palette}
