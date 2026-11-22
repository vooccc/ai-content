# -*- coding: utf-8 -*-
"""发布能力 API：把内容流水线终稿推送到微信公众号草稿箱。"""
from fastapi import APIRouter
from pydantic import BaseModel

from . import wechat_mp

router = APIRouter()


@router.get("/publish/wechat/status")
def wechat_status():
    return {"configured": wechat_mp.is_configured()}


class WeChatDraftRequest(BaseModel):
    title: str
    content: str
    author: str = ""
    digest: str = ""
    source_url: str = ""
    thumb_media_id: str = ""
    style: str = ""


@router.post("/publish/wechat/draft")
def wechat_draft(req: WeChatDraftRequest):
    try:
        result = wechat_mp.add_draft(
            title=req.title,
            content=req.content,
            author=req.author,
            digest=req.digest,
            source_url=req.source_url,
            thumb_media_id=req.thumb_media_id or None,
            style=req.style,
        )
        return {"ok": True, "media_id": result["media_id"]}
    except wechat_mp.WeChatError as e:
        return {"ok": False, "error": e.message, "errcode": e.errcode}
    except Exception as e:
        return {"ok": False, "error": f"未知错误：{e}", "errcode": None}
