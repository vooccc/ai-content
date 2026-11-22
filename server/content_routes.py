# -*- coding: utf-8 -*-
"""多平台发布 API（导航 + 账号目录 + 公众号直推）。"""
import json
import os
import tempfile

from fastapi import APIRouter, File, Form, UploadFile
from pydantic import BaseModel

from . import wechat_mp
from .paths import content_config_path

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
            thumb = wechat_mp.upload_image_from_url(req.cover_url.strip(), req.appid.strip(), req.secret.strip())
        result = wechat_mp.add_draft(
            title=req.title, content=req.content,
            author=req.author, digest=req.digest, source_url=req.source_url,
            thumb_media_id=thumb,
            appid=req.appid.strip(), secret=req.secret.strip(),
        )
        return {"ok": True, "media_id": result["media_id"]}
    except wechat_mp.WeChatError as e:
        return {"ok": False, "error": e.message, "errcode": e.errcode}
    except Exception as e:
        return {"ok": False, "error": f"未知错误：{e}", "errcode": None}
