# -*- coding: utf-8 -*-
"""选题池、账号定位与数据复盘 API。"""
from __future__ import annotations

import json
import time
import uuid
from datetime import date, timedelta
from typing import Any, Dict, List, Optional

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from . import db, gzh_themes, intel_engine, llm_bridge, settings_store, topic_engine, wechat_mp
from .paths import content_config_path, project_root, studio_dir

router = APIRouter()


@router.get("/themes")
def list_themes():
    return {"themes": gzh_themes.list_themes()}


@router.get("/accounts/primary")
def get_primary_account():
    return {"ok": True, "account": db.get_primary_account()}


class UpdateAccountRequest(BaseModel):
    name: Optional[str] = None
    niche: Optional[str] = None
    audience: Optional[str] = None
    cadence: Optional[str] = None
    title_formulas: Optional[List[str]] = None
    banned_words: Optional[List[str]] = None
    default_style: Optional[str] = None
    default_theme: Optional[str] = None
    wechat_account_id: Optional[str] = None
    footer_template: Optional[str] = None
    sources_config: Optional[Dict[str, Any]] = None


@router.put("/accounts/primary")
def update_primary_account(req: UpdateAccountRequest):
    patch = {k: v for k, v in req.model_dump().items() if v is not None}
    updated = db.update_primary_account(patch)
    return {"ok": True, "account": updated}


@router.get("/topics")
def list_topics(status: str = "", source_type: str = "", filter: str = "", limit: int = 80):
    items = db.list_topics(status=status, source_type=source_type, filter_mode=filter, limit=limit)
    counts = db.topic_funnel_counts()
    in_progress: List[Dict[str, Any]] = []
    try:
        for p in studio_dir().glob("*.json"):
            try:
                d = json.loads(p.read_text(encoding="utf-8"))
            except Exception:
                continue
            if d.get("workflow") != "content_pipeline":
                continue
            if d.get("draft_media_id"):
                continue
            nodes = d.get("nodes") or []
            done = d.get("done") or []
            done_cnt = sum(1 for x in done if x)
            if nodes and done_cnt >= len(nodes):
                continue
            next_idx = next((i for i, x in enumerate(done) if not x), len(nodes) - 1 if nodes else 0)
            next_step = nodes[next_idx].get("id") if 0 <= next_idx < len(nodes) else "继续推进"
            in_progress.append({
                "id": d.get("id", p.stem),
                "title": d.get("title") or "未命名创作",
                "done_count": done_cnt,
                "total_count": len(nodes),
                "next_step": next_step,
                "updated": float(d.get("updated") or d.get("created") or 0),
            })
        in_progress.sort(key=lambda x: x["updated"])
    except Exception:
        in_progress = []
    return {
        "ok": True,
        "topics": items,
        "counts": counts,
        "source_counts": db.topic_source_counts(),
        "in_progress_projects": in_progress[:5],
    }


@router.get("/topics/sources")
def get_topic_sources():
    acc = db.get_primary_account()
    sc = acc.get("sources_config") or {}
    return {
        "ok": True,
        "sources_config": sc,
        "pool_counts": db.topic_source_counts(),
        "last_fetch_stats": sc.get("last_fetch_stats") or {},
        "last_rss_stats": sc.get("last_rss_stats") or {},
        "last_fetch_errors": sc.get("last_fetch_errors") or [],
        "last_fetch_at": sc.get("last_fetch_at") or 0,
    }


class TestRssRequest(BaseModel):
    url: str = ""
    name: str = ""


@router.post("/topics/sources/test-rss")
def test_rss_source(req: TestRssRequest):
    url = (req.url or "").strip()
    if not url.startswith(("http://", "https://")):
        return JSONResponse({"ok": False, "error": "请输入以 http:// 或 https:// 开头的 RSS/Atom 地址"}, status_code=400)
    from . import sources
    items, errs, _ = sources.fetch_rss_feeds([{"name": req.name.strip() or url, "url": url, "enabled": True}], limit_per_feed=5)
    if errs and not items:
        return JSONResponse({"ok": False, "error": errs[0]}, status_code=400)
    return {
        "ok": True,
        "count": len(items),
        "samples": [{"title": it["raw_title"], "url": it["source_url"]} for it in items[:3]],
    }


@router.post("/topics/sources/apply-presets")
def apply_official_rss_presets():
    """一键合并实测可用的一线 AI 官方博客 RSS 预设包（按 URL 去重，不覆盖已有源）。"""
    from . import sources
    acc = db.get_primary_account()
    sc = dict(acc.get("sources_config") or {})
    cur_feeds = list(sc.get("rss_feeds") or [])
    existing_urls = {str(f.get("url") or "").strip() for f in cur_feeds if isinstance(f, dict)}
    added = 0
    for preset in sources.OFFICIAL_AI_RSS_PRESETS:
        if preset["url"] not in existing_urls:
            cur_feeds.append(dict(preset))
            existing_urls.add(preset["url"])
            added += 1
    sc["rss_feeds"] = cur_feeds
    updated = db.update_primary_account({"sources_config": sc})
    return {
        "ok": True,
        "added": added,
        "total": len(cur_feeds),
        "sources_config": updated.get("sources_config") or sc,
    }


@router.get("/intel")
def list_intel(credibility: str = "", source_type: str = "", q: str = "", limit: int = 80):
    items = db.list_intel_items(credibility=credibility, source_type=source_type, q=q, limit=limit)
    return {
        "ok": True,
        "items": items,
        "counts": db.intel_counts(),
    }


class RefreshIntelRequest(BaseModel):
    limit: int = 36


@router.post("/intel/refresh")
def refresh_intel(req: RefreshIntelRequest):
    try:
        return intel_engine.refresh_intel_stream(limit=max(5, min(req.limit, 50)))
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"快讯刷新失败：{e}"}, status_code=500)


class PromoteIntelRequest(BaseModel):
    start_project: bool = False


@router.post("/intel/{intel_id}/promote")
def promote_intel(intel_id: str, req: PromoteIntelRequest):
    try:
        res = intel_engine.promote_intel_to_topic(intel_id)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"转选题失败：{e}"}, status_code=500)

    tp = res["topic"]
    if req.start_project:
        proj_res = _create_project_from_topic(tp["id"], selected_title="")
        return {"ok": True, "topic": db.get_topic(tp["id"]) or tp, "project": proj_res["project"]}
    return {"ok": True, "topic": tp, "already_existed": res["already_existed"]}


class ImportTopicsRequest(BaseModel):
    text: str = ""
    dry_run: bool = False


@router.post("/topics/import")
def import_topics(req: ImportTopicsRequest):
    if not req.text.strip():
        return JSONResponse({"ok": False, "error": "请粘贴 CSV / 表格文本或 JSON 数据"}, status_code=400)
    try:
        return topic_engine.import_topics_from_text(req.text, dry_run=req.dry_run)
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"导入解析失败：{e}"}, status_code=500)


class RefreshTopicsRequest(BaseModel):
    max_new: int = 8


@router.post("/topics/refresh")
def refresh_topics(req: RefreshTopicsRequest):
    try:
        return topic_engine.refresh_topics(max_new=max(1, min(req.max_new, 20)))
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"抓取异常：{e}"}, status_code=500)


class ManualTopicRequest(BaseModel):
    idea: str = ""
    source_url: str = ""


@router.post("/topics/manual")
def add_manual_topic(req: ManualTopicRequest):
    if not req.idea.strip() and not req.source_url.strip():
        return JSONResponse({"ok": False, "error": "请输入灵感内容或参考链接"}, status_code=400)
    try:
        tp = topic_engine.create_manual_topic(req.idea, req.source_url)
        return {"ok": True, "topic": tp}
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"提炼失败：{e}"}, status_code=500)


class PatchTopicRequest(BaseModel):
    status: Optional[str] = None


@router.patch("/topics/{topic_id}")
def patch_topic(topic_id: str, req: PatchTopicRequest):
    tp = db.get_topic(topic_id)
    if not tp:
        return JSONResponse({"ok": False, "error": "选题不存在"}, status_code=404)
    updated = db.update_topic(topic_id, status=req.status) if req.status else tp
    return {"ok": True, "topic": updated}


class StartTopicRequest(BaseModel):
    selected_title: str = ""


def _build_account_constraint_note(account: Dict[str, Any], tp: Dict[str, Any]) -> str:
    banned = "、".join(account.get("banned_words") or [])
    parts = [
        f"【账号定位】{account.get('niche')}",
        f"【目标读者】{account.get('audience')}",
        f"【建议栏目】{tp.get('category') or '实操教程'}",
    ]
    if tp.get("angle"):
        parts.append(f"【切入角度】{tp['angle']}")
    if banned:
        parts.append(f"【禁用词（严格避开 AI 套话）】{banned}")
    if account.get("footer_template"):
        parts.append(f"【文末低门槛互动引导】{account['footer_template']}")
    return "\n".join(parts)


def _create_project_from_topic(topic_id: str, selected_title: str = "") -> Dict[str, Any]:
    """从选题记录创建预填好素材与账号约束的公众号创作项目。"""
    tp = db.get_topic(topic_id)
    if not tp:
        raise ValueError("选题不存在")

    account = db.get_primary_account()
    chosen_title = (
        selected_title.strip()
        or (tp.get("suggested_titles") or [""])[0]
        or tp.get("raw_title")
        or "新公众号选题"
    )

    import yaml
    wf_path = project_root() / "flows" / "content_pipeline.yaml"
    wf_raw = yaml.safe_load(wf_path.read_text(encoding="utf-8"))
    nodes = [
        {"id": n["id"], "type": n["type"], "role": n.get("role", ""), "reads": n.get("reads", []), "writes": n.get("writes", "")}
        for n in (wf_raw.get("nodes") or [])
    ]

    material_blocks = [_build_account_constraint_note(account, tp)]
    if tp.get("metrics_badge"):
        material_blocks.append(f"【爆款信号】{tp['metrics_badge']}")
    if tp.get("raw_summary"):
        material_blocks.append(f"【选题原始素材（{tp.get('source_name') or tp.get('source_type')}）】\n{tp['raw_summary']}")
    sigs = tp.get("raw_signals") or []
    if sigs:
        sig_lines = []
        for s in sigs[:6]:
            line = f"- [{s.get('source_name') or s.get('source_type')}] {s.get('title')}"
            if s.get("url"):
                line += f" ({s['url']})"
            sig_lines.append(line)
        material_blocks.append("【聚类关联信源】\n" + "\n".join(sig_lines))
    elif tp.get("source_url"):
        material_blocks.append(f"【参考链接】{tp['source_url']}")
    material_text = "\n\n".join(material_blocks)

    pid = uuid.uuid4().hex[:12]
    inputs = {
        "topic": chosen_title,
        "platform": "微信公众号",
        "sources": tp.get("source_url") or "",
    }
    src_records = [
        {"url": s["url"], "title": s.get("title") or "", "ok": True}
        for s in sigs
        if s.get("url")
    ]
    if not src_records and tp.get("source_url"):
        src_records = [{"url": tp["source_url"], "title": tp["raw_title"], "ok": True}]
    state = {
        "inputs": inputs,
        "topic": chosen_title,
        "platform": "微信公众号",
        "sources": tp.get("source_url") or "",
        "data": {
            "material": material_text,
            "sources": src_records,
        },
        "events": [],
        "timings": {},
    }
    proj = {
        "id": pid,
        "title": chosen_title[:60],
        "workflow": "content_pipeline",
        "name": wf_raw.get("name", "自媒体内容流水线"),
        "inputs": inputs,
        "nodes": nodes,
        "state": state,
        "style": account.get("default_style") or "khazix",
        "theme": account.get("default_theme") or "moyu_green",
        "topic_id": tp["id"],
        "account_id": account["id"],
        "current": 1 if nodes else 0,
        "done": [True] + [False] * (len(nodes) - 1) if nodes else [],
        "created": time.time(),
        "updated": time.time(),
    }
    (studio_dir() / f"{pid}.json").write_text(json.dumps(proj, ensure_ascii=False), encoding="utf-8")
    db.update_topic(topic_id, status="drafted", project_id=pid)
    return {"ok": True, "project": proj}


@router.post("/topics/{topic_id}/start")
def start_topic_project(topic_id: str, req: StartTopicRequest):
    """一键从选题池创建预填好素材与账号约束的公众号创作项目。"""
    try:
        return _create_project_from_topic(topic_id, selected_title=req.selected_title)
    except ValueError as e:
        return JSONResponse({"ok": False, "error": str(e)}, status_code=404)


@router.get("/metrics")
def get_metrics(limit: int = 100):
    metrics = db.list_metrics(limit=limit)
    articles = db.list_articles(limit=limit)
    total_read_user = sum(int(m.get("read_user") or 0) for m in metrics)
    total_share = sum(int(m.get("share_count") or 0) for m in metrics)
    total_fav = sum(int(m.get("fav_count") or 0) for m in metrics)
    total_like = sum(int(m.get("like_count") or 0) for m in metrics)
    best = max(metrics, key=lambda m: int(m.get("read_user") or 0)) if metrics else None
    return {
        "ok": True,
        "metrics": metrics,
        "articles": articles,
        "summary": {
            "article_count": len(articles),
            "metric_count": len(metrics),
            "total_read_user": total_read_user,
            "total_share": total_share,
            "total_fav": total_fav,
            "total_like": total_like,
            "best_title": best.get("title", "") if best else "",
            "best_read_user": int(best.get("read_user") or 0) if best else 0,
        },
    }


class ManualMetricRequest(BaseModel):
    ref_date: str = ""
    title: str
    target_user: int = 0
    read_user: int = 0
    read_count: int = 0
    share_count: int = 0
    fav_count: int = 0
    like_count: int = 0
    notes: str = ""


@router.post("/metrics")
def save_manual_metric(req: ManualMetricRequest):
    if not req.title.strip():
        return JSONResponse({"ok": False, "error": "文章标题不能为空"}, status_code=400)
    ref_date = req.ref_date.strip() or date.today().strftime("%Y-%m-%d")
    row = db.upsert_metric({
        "ref_date": ref_date,
        "title": req.title.strip(),
        "target_user": req.target_user,
        "read_user": req.read_user,
        "read_count": req.read_count or req.read_user,
        "share_count": req.share_count,
        "fav_count": req.fav_count,
        "like_count": req.like_count,
        "source": "manual",
        "notes": req.notes.strip(),
    })
    return {"ok": True, "metric": row}


class SyncWechatMetricsRequest(BaseModel):
    days: int = 7
    appid: str = ""
    secret: str = ""


def _resolve_wechat_creds(appid: str = "", secret: str = "") -> tuple[str, str]:
    if appid.strip() and secret.strip():
        return appid.strip(), secret.strip()
    acc = db.get_primary_account()
    bound_id = acc.get("wechat_account_id") or ""
    cfg_path = content_config_path()
    if cfg_path.exists():
        try:
            cfg = json.loads(cfg_path.read_text(encoding="utf-8-sig"))
            for p in cfg.get("platforms") or []:
                if p.get("key") != "wechat_mp":
                    continue
                accounts = p.get("accounts") or []
                for a in accounts:
                    if bound_id and a.get("id") == bound_id and a.get("appid") and a.get("secret"):
                        return str(a["appid"]), str(a["secret"])
                for a in accounts:
                    if a.get("appid") and a.get("secret"):
                        return str(a["appid"]), str(a["secret"])
        except Exception:
            pass
    return "", ""


@router.post("/metrics/sync-wechat")
def sync_wechat_metrics(req: SyncWechatMetricsRequest):
    eff_appid, eff_secret = _resolve_wechat_creds(req.appid, req.secret)
    days = max(1, min(req.days, 14))
    end_d = date.today() - timedelta(days=1)
    begin_d = end_d - timedelta(days=days - 1)
    try:
        rows = wechat_mp.fetch_article_total(
            begin_d.strftime("%Y-%m-%d"),
            end_d.strftime("%Y-%m-%d"),
            appid=eff_appid,
            secret=eff_secret,
        )
    except wechat_mp.WeChatError as e:
        return JSONResponse({"ok": False, "error": e.message, "errcode": e.errcode}, status_code=400)
    saved = 0
    for row in rows:
        db.upsert_metric({**row, "source": "datacube"})
        saved += 1
    return {"ok": True, "synced": saved, "begin_date": begin_d.strftime("%Y-%m-%d"), "end_date": end_d.strftime("%Y-%m-%d")}


@router.post("/metrics/review")
def review_metrics():
    return topic_engine.review_metrics_with_ai()


class UpdateModelSettingsRequest(BaseModel):
    mode: Optional[str] = None
    gateway_url: Optional[str] = None
    gateway_token: Optional[str] = None
    clear_gateway_token: Optional[bool] = None
    llm_base_url: Optional[str] = None
    llm_api_key: Optional[str] = None
    clear_llm_api_key: Optional[bool] = None
    default_text_model: Optional[str] = None
    fast_text_model: Optional[str] = None
    image_base_url: Optional[str] = None
    image_api_key: Optional[str] = None
    clear_image_api_key: Optional[bool] = None
    default_image_model: Optional[str] = None
    tavily_api_key: Optional[str] = None
    clear_tavily_api_key: Optional[bool] = None


@router.get("/settings/models")
def get_model_settings():
    return {
        "ok": True,
        "settings": settings_store.get_masked_settings(),
        "active_source": llm_bridge.active_source(),
        "current_model": llm_bridge.current_model(),
        "text_models": llm_bridge.list_text_models(),
        "image_models": llm_bridge.list_image_models(),
    }


@router.put("/settings/models")
def put_model_settings(req: UpdateModelSettingsRequest):
    patch = {k: v for k, v in req.model_dump().items() if v is not None}
    updated = settings_store.update_settings(patch)
    return {
        "ok": True,
        "settings": updated,
        "active_source": llm_bridge.active_source(),
        "current_model": llm_bridge.current_model(),
        "text_models": llm_bridge.list_text_models(),
        "image_models": llm_bridge.list_image_models(),
    }


class TestModelRequest(BaseModel):
    model: str = ""
    prefer_fast: bool = False


@router.post("/settings/models/test")
def test_model_connection(req: TestModelRequest):
    t0 = time.monotonic()
    try:
        reply, used = llm_bridge.chat_completion_with_meta(
            [{"role": "user", "content": "只回复 OK 两个字母"}],
            model=req.model.strip(),
            max_tokens=200,
            timeout=20,
            prefer_fast=req.prefer_fast,
        )
        ms = int((time.monotonic() - t0) * 1000)
        if not reply:
            return JSONResponse({"ok": False, "error": "模型返回空内容"}, status_code=502)
        return {"ok": True, "model": used, "reply": reply[:60], "latency_ms": ms}
    except Exception as e:
        return JSONResponse({"ok": False, "error": f"连通测试失败：{e}"}, status_code=400)
