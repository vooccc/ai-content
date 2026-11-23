# -*- coding: utf-8 -*-
"""多平台发布 API（导航 + 账号目录 + 公众号直推）。"""
import json
import os
import re
import tempfile
from urllib.parse import parse_qs, urlparse

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel

from . import db, wechat_mp
from .paths import content_config_path, studio_dir

router = APIRouter()

DEFAULT_PLATFORMS = [
    {"key": "wechat_mp", "name": "微信公众号", "emoji": "💬",
     "icon": "/media-icons/wechat_mp.svg",
     "home": "https://mp.weixin.qq.com/", "accounts": []},
    {"key": "xiaohongshu", "name": "小红书", "emoji": "📕",
     "icon": "/media-icons/xiaohongshu.svg",
     "home": "https://creator.xiaohongshu.com/", "accounts": []},
    {"key": "zhihu", "name": "知乎", "emoji": "🔵",
     "icon": "/media-icons/zhihu.svg",
     "home": "https://zhuanlan.zhihu.com/write", "accounts": []},
    {"key": "bilibili", "name": "B站", "emoji": "📺",
     "icon": "/media-icons/bilibili.svg",
     "home": "https://member.bilibili.com/", "accounts": []},
    {"key": "douyin", "name": "抖音", "emoji": "🎵",
     "icon": "/media-icons/douyin.svg",
     "home": "https://creator.douyin.com/", "accounts": []},
]


@router.get("/content/config")
def get_config():
    p = content_config_path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("platforms"), list):
                return data
        except Exception:
            pass
    return {"platforms": DEFAULT_PLATFORMS}


class MediaConfig(BaseModel):
    platforms: list = []


@router.post("/content/config")
def save_config(cfg: MediaConfig):
    content_config_path().write_text(
        json.dumps({"platforms": cfg.platforms}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return {"ok": True, "count": len(cfg.platforms)}


class WeChatDispatchRequest(BaseModel):
    title: str
    content: str
    appid: str = ""
    secret: str = ""
    thumb_media_id: str = ""
    cover_url: str = ""
    author: str = ""
    digest: str = ""
    source_url: str = ""
    style: str = ""
    theme: str = ""
    project_id: str = ""
    topic_id: str = ""
    account_id: str = ""
    word_count: int = 0


def _resolve_studio_proxy_images(html_or_md: str) -> str:
    """把工作台本地代理路径 /studio/projects/{pid}/image?path=... 还原为真实本地文件路径，便于上传微信图床。"""
    if not html_or_md or "/studio/projects/" not in html_or_md:
        return html_or_md

    def _repl(m: re.Match) -> str:
        raw_url = m.group(0)
        try:
            parsed = urlparse(raw_url)
            qs = parse_qs(parsed.query)
            p = (qs.get("path") or [""])[0].strip()
            if p and os.path.isfile(p):
                return p
        except Exception:
            pass
        return raw_url

    return re.sub(r"(?:https?://[^/\s\"']+)?/studio/projects/[^/\s\"']+/image\?[^\"'\s)]+", _repl, html_or_md)


@router.post("/content/upload-thumb")
async def upload_thumb(file: UploadFile = File(...), appid: str = Form(""), secret: str = Form("")):
    try:
        suffix = os.path.splitext(file.filename or "")[1] or ".jpg"
        fd, tmp = tempfile.mkstemp(suffix=suffix, prefix="wxthumb_")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(await file.read())
            media_id = wechat_mp.upload_image_material(tmp, "image", appid.strip(), secret.strip())
            return {"ok": True, "media_id": media_id}
        finally:
            try:
                os.remove(tmp)
            except Exception:
                pass
    except wechat_mp.WeChatError as e:
        return {"ok": False, "error": e.message, "errcode": e.errcode}
    except Exception as e:
        return {"ok": False, "error": f"上传失败：{e}", "errcode": None}


@router.post("/content/dispatch/wechat")
def dispatch_wechat(req: WeChatDispatchRequest):
    try:
        thumb = req.thumb_media_id.strip() or None
        if req.cover_url.strip():
            cover_src = _resolve_studio_proxy_images(req.cover_url.strip())
            if os.path.isfile(cover_src):
                thumb = wechat_mp.upload_image_material(cover_src, "image", req.appid.strip(), req.secret.strip())
            else:
                thumb = wechat_mp.upload_image_from_url(cover_src, req.appid.strip(), req.secret.strip())
        resolved_content = _resolve_studio_proxy_images(req.content)
        eff_style = req.theme.strip() or req.style.strip()
        result = wechat_mp.add_draft(
            title=req.title, content=resolved_content,
            author=req.author, digest=req.digest, source_url=req.source_url,
            thumb_media_id=thumb,
            appid=req.appid.strip(), secret=req.secret.strip(),
            style=eff_style,
        )
        media_id = result["media_id"]
        # 自动归档进 articles 表并回写项目草稿 ID
        plain_len = req.word_count or len(re.sub(r"<[^>]+>", "", resolved_content))
        topic_id = req.topic_id.strip()
        account_id = req.account_id.strip() or "primary"
        if req.project_id.strip():
            proj_path = studio_dir() / f"{req.project_id.strip()}.json"
            if proj_path.exists():
                try:
                    proj = json.loads(proj_path.read_text(encoding="utf-8"))
                    proj["draft_media_id"] = media_id
                    if not topic_id:
                        topic_id = str(proj.get("topic_id") or "")
                    if proj.get("account_id"):
                        account_id = str(proj["account_id"])
                    if not eff_style:
                        eff_style = str(proj.get("theme") or proj.get("style") or "")
                    proj_path.write_text(json.dumps(proj, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
        art = db.record_article({
            "account_id": account_id,
            "topic_id": topic_id,
            "project_id": req.project_id.strip(),
            "title": req.title.strip(),
            "style": req.style.strip(),
            "theme": eff_style,
            "word_count": plain_len,
            "draft_media_id": media_id,
            "status": "draft",
        })
        return {
            "ok": True,
            "media_id": media_id,
            "article_id": art.get("id", ""),
            "uploaded_images": result.get("uploaded_images", 0),
            "image_warnings": result.get("image_warnings", []),
        }
    except wechat_mp.WeChatError as e:
        return {"ok": False, "error": e.message, "errcode": e.errcode}
    except Exception as e:
        return {"ok": False, "error": f"未知错误：{e}", "errcode": None}
