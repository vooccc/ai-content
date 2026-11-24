# -*- coding: utf-8 -*-
"""实时 AI 情报快讯引擎：多源采集 -> 事件聚簇 -> 可信度分级 -> 中文快讯提炼 -> 一键转选题。"""
from __future__ import annotations

import hashlib
import json
import re
import time
from typing import Any, Dict, List

from . import db, llm_bridge, sources, topic_engine

_OFFICIAL_FEED_NAMES = {
    "openai news",
    "anthropic news",
    "anthropic engineering",
    "google deepmind",
    "hugging face blog",
    "arxiv cs.ai",
}


def classify_credibility(item: Dict[str, Any]) -> str:
    """按信源属性与多源交叉印证情况判定可信度等级。"""
    st = str(item.get("source_type") or "")
    sn = str(item.get("source_name") or "").lower()
    sigs = item.get("raw_signals") or []
    res_srcs = item.get("resonance_sources") or []

    if st in ("hf_papers", "github_trending") or sn in _OFFICIAL_FEED_NAMES:
        return "一手官方"
    for s in sigs:
        sst = str(s.get("source_type") or "")
        ssn = str(s.get("source_name") or "").lower()
        if sst in ("hf_papers", "github_trending") or ssn in _OFFICIAL_FEED_NAMES:
            return "一手官方"
    if len(res_srcs) >= 2 or len({str(s.get("source_type") or "") for s in sigs if s.get("source_type")}) >= 2:
        return "多源印证"
    if st in ("hackernews", "bilibili", "reddit", "bluesky", "x", "xiaohongshu") or any(
        k in sn for k in ("simon willison", "latent space", "少数派", "阮一峰")
    ):
        return "社区热议"
    return "快讯转述"


def _make_cluster_key(item: Dict[str, Any]) -> str:
    url = str(item.get("source_url") or "").strip().split("#")[0]
    if url:
        return "u_" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:16]
    norm = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "", str(item.get("raw_title") or "").lower())[:80]
    return "t_" + hashlib.sha1(norm.encode("utf-8")).hexdigest()[:16]


def _guess_category(title: str, source_type: str) -> str:
    low = title.lower()
    if source_type == "hf_papers" or any(k in low for k in ("paper", "arxiv", "benchmark", "论文")):
        return "论文研究"
    if any(k in low for k in ("agent", "mcp", "claude code", "cursor", "workflow", "技能", "实操")):
        return "Agent与工具"
    if source_type == "github_trending" or any(k in low for k in ("open source", "github", "开源", "repo")):
        return "开源项目"
    if any(k in low for k in ("gpt", "claude", "gemini", "llm", "model", "发布", "模型")):
        return "大模型动态"
    return "AI快讯"


def _has_cjk(text: str) -> bool:
    return bool(re.search(r"[\u4e00-\u9fff]", text or ""))


def _summarize_chunk(items: List[Dict[str, Any]], offset: int) -> Dict[int, Dict[str, Any]]:
    if not items:
        return {}
    brief = [
        {
            "idx": offset + i,
            "source": it.get("source_name") or it.get("source_type"),
            "title": (it.get("raw_title") or "")[:140],
            "summary": (it.get("raw_summary") or "")[:240],
        }
        for i, it in enumerate(items)
    ]
    prompt = (
        "你是资深 AI 情报编辑。请把下面每条一手动态全部提炼成流畅、高信息密度的中文快讯。\n"
        "要求：\n"
        "1. title：20-38字中文快讯标题，直击核心亮点；英文标题必须译成地道中文（专有项目/模型名如 Claude Code、Gemini 4 可保留英文词，但整句必须是中文）；\n"
        "2. summary：60-120字纯中文摘要，说清功能、关键数字或结论；\n"
        "3. category：从「大模型动态 / Agent与工具 / 开源项目 / 论文研究 / 行业趋势」选一个；\n"
        "4. tags：2-3个简短标签（如 [\"Claude\", \"开源\"]）。\n"
        f"素材：\n{json.dumps(brief, ensure_ascii=False)}\n"
        "只返回 JSON 数组：[{\"idx\":0,\"title\":\"...\",\"summary\":\"...\",\"category\":\"...\",\"tags\":[\"...\"]}]"
    )
    try:
        raw = llm_bridge.chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
            max_tokens=3600,
            timeout=45,
            prefer_fast=True,
        )
        m = re.search(r"(\[[\s\S]*\])", raw)
        if not m:
            return {}
        rows = json.loads(m.group(1))
        out: Dict[int, Dict[str, Any]] = {}
        for row in rows:
            if isinstance(row, dict) and "idx" in row:
                out[int(row["idx"])] = row
        return out
    except Exception:
        return {}


def _summarize_batch_with_llm(items: List[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    if not items:
        return {}
    from concurrent.futures import ThreadPoolExecutor
    chunk_size = 6
    chunks = [(i, items[i : i + chunk_size]) for i in range(0, len(items), chunk_size)]
    merged: Dict[int, Dict[str, Any]] = {}
    with ThreadPoolExecutor(max_workers=min(2, len(chunks))) as pool:
        futs = [pool.submit(_summarize_chunk, ch, off) for off, ch in chunks]
        for fut in futs:
            try:
                merged.update(fut.result())
            except Exception:
                pass

    # 补翻兜底：若有分片偶发失败或返回仍无中文标题，对漏网条目再补翻一轮
    missing_indices = [
        i for i in range(len(items))
        if not _has_cjk(str((merged.get(i) or {}).get("title") or ""))
        and not _has_cjk(str(items[i].get("raw_title") or ""))
    ]
    if missing_indices and llm_bridge.active_source():
        retry_items = [items[i] for i in missing_indices[:16]]
        retry_chunks = [(k, retry_items[k : k + 8]) for k in range(0, len(retry_items), 8)]
        with ThreadPoolExecutor(max_workers=min(2, len(retry_chunks))) as pool:
            futs = [pool.submit(_summarize_chunk, ch, off) for off, ch in retry_chunks]
            for fut in futs:
                try:
                    res = fut.result()
                    for local_idx, val in res.items():
                        if 0 <= local_idx < len(missing_indices):
                            merged[missing_indices[local_idx]] = val
                except Exception:
                    pass
    return merged


def _select_balanced_clusters(clustered: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    """按信源分桶轮询采样，防止单一高热度源（如 GitHub/arXiv）挤占全部名额。"""
    def _bucket_key(x: Dict[str, Any]) -> str:
        st = str(x.get("source_type") or "")
        sn = str(x.get("source_name") or "")
        if st == "rss":
            return f"rss:{sn}"
        if st == "xiaohongshu":
            return "xiaohongshu:hot" if sn.startswith("小红书热搜") else "xiaohongshu:feed"
        return st or sn or "other"

    buckets: Dict[str, List[Dict[str, Any]]] = {}
    for it in clustered:
        bk = _bucket_key(it)
        buckets.setdefault(bk, []).append(it)

    # 桶内按爆款/多源/热度排序
    for bk, arr in buckets.items():
        arr.sort(
            key=lambda x: (
                bool(x.get("metrics_badge")),
                len(x.get("raw_signals") or []),
                int(x.get("popularity") or 0),
            ),
            reverse=True,
        )

    # 优先桶序：官方博客 & 多源/高信号源在前，arXiv 限流最多 2 条避免学术刷屏
    priority_order = [
        "rss:OpenAI News",
        "rss:Anthropic News",
        "rss:Anthropic Engineering",
        "rss:Google DeepMind",
        "rss:Hugging Face Blog",
        "rss:Latent Space (AINews)",
        "rss:Simon Willison",
        "x",
        "xiaohongshu:hot",
        "github_trending",
        "hf_papers",
        "hackernews",
        "reddit",
        "bluesky",
        "bilibili",
        "xiaohongshu:feed",
        "wechat_search",
        "rss:少数派",
        "rss:阮一峰的网络日志",
        "weibo_hot",
    ]
    ordered_keys = [k for k in priority_order if k in buckets] + [k for k in buckets if k not in priority_order]

    picked: List[Dict[str, Any]] = []
    idx_map = {k: 0 for k in ordered_keys}
    max_per_bucket = {"rss:arXiv cs.AI": 2}
    while len(picked) < limit:
        progressed = False
        for k in ordered_keys:
            if len(picked) >= limit:
                break
            arr = buckets[k]
            cur_i = idx_map[k]
            cap = max_per_bucket.get(k, len(arr))
            if cur_i < len(arr) and cur_i < cap:
                picked.append(arr[cur_i])
                idx_map[k] = cur_i + 1
                progressed = True
        if not progressed:
            break
    return picked


def refresh_intel_stream(limit: int = 36) -> Dict[str, Any]:
    """全量采集启用源 -> 聚类合并 -> 均衡采样 -> 可信度分级 -> 批处理中文快讯提炼 -> 入库。"""
    acc = db.get_primary_account()
    sc = dict(acc.get("sources_config") or {})
    gathered = sources.gather_all_sources(sc, search_terms=sc.get("wechat_keywords") or [])
    raw_items = gathered.get("items") or []

    # 持久化最新抓取统计到账号配置，方便信息源面板展示
    sc["last_fetch_stats"] = gathered.get("stats") or {}
    sc["last_rss_stats"] = gathered.get("rss_detail") or {}
    sc["last_fetch_errors"] = gathered.get("errors") or []
    sc["last_fetch_at"] = time.time()
    db.update_primary_account({"sources_config": sc})

    # 算低粉爆款 + 多源共振 + 同事件聚类
    annotated: List[Dict[str, Any]] = []
    for it in raw_items:
        badge, v_bonus = topic_engine.compute_viral_badge(int(it.get("plays") or 0), int(it.get("followers") or 0))
        annotated.append({
            **it,
            "metrics_badge": badge or str(it.get("metrics_badge") or ""),
            "_viral_bonus": v_bonus,
        })
    annotated = topic_engine.annotate_cross_source_resonance(annotated)
    clustered = topic_engine.cluster_candidates(annotated)

    picked = _select_balanced_clusters(clustered, max(1, min(limit, 50)))
    try:
        sources.enrich_xiaohongshu_items(picked, mode=str(sc.get("xhs_mode") or "auto"), max_items=5)
    except Exception:
        pass

    llm_map = _summarize_batch_with_llm(picked)
    mode = "llm" if llm_map else "rules"

    records: List[Dict[str, Any]] = []
    for i, it in enumerate(picked):
        cred = classify_credibility(it)
        ai_row = llm_map.get(i) or {}
        raw_title = str(it.get("raw_title") or "").strip()
        raw_summary = str(it.get("raw_summary") or "").strip()
        title = str(ai_row.get("title") or raw_title).strip()
        summary = str(ai_row.get("summary") or raw_summary[:240]).strip()
        cat = str(ai_row.get("category") or _guess_category(raw_title, str(it.get("source_type") or ""))).strip()
        tags = ai_row.get("tags") if isinstance(ai_row.get("tags"), list) else []
        if not tags:
            tags = [str(it.get("source_name") or it.get("source_type") or "AI")]
        records.append({
            "cluster_key": _make_cluster_key(it),
            "title": title,
            "summary": summary,
            "raw_title": raw_title,
            "source_type": str(it.get("source_type") or ""),
            "source_name": str(it.get("source_name") or ""),
            "source_url": str(it.get("source_url") or ""),
            "signals": it.get("raw_signals") or [],
            "credibility": cred,
            "metrics_badge": str(it.get("metrics_badge") or ""),
            "engagement_badge": str(it.get("engagement_badge") or ""),
            "engagement": it.get("engagement") if isinstance(it.get("engagement"), dict) else {},
            "category": cat,
            "tags": tags[:4],
            "popularity": int(it.get("popularity") or 0),
        })

    stat = db.upsert_intel_items(records)
    return {
        "ok": True,
        "mode": mode,
        "fetched": len(raw_items),
        "clustered": len(clustered),
        "added": stat["added"],
        "updated": stat["updated"],
        "source_stats": gathered.get("stats") or {},
        "rss_detail": gathered.get("rss_detail") or {},
        "errors": gathered.get("errors") or [],
        "counts": db.intel_counts(),
    }


def promote_intel_to_topic(intel_id: str) -> Dict[str, Any]:
    """把一条实时快讯升格进选题池（幂等去重，自动套账号标题公式）。"""
    item = db.get_intel_item(intel_id)
    if not item:
        raise ValueError("快讯条目不存在")

    existing_tid = str(item.get("promoted_topic_id") or "").strip()
    if existing_tid:
        existing_tp = db.get_topic(existing_tid)
        if existing_tp:
            return {"topic": existing_tp, "already_existed": True}

    acc = db.get_primary_account()
    formulas = acc.get("title_formulas") or []
    base_title = item["title"]
    suggested = [base_title]
    if formulas:
        suggested.append(f"实测拆解：{base_title}")
        suggested.append(f"别错过：{base_title}，背后关键变化在这里")

    sigs = item.get("signals") or []
    angle = f"从「{item['credibility']}」切入，用实操视角拆解：{item['summary'][:80]}"
    reason = f"来自实时快讯（{item['credibility']} · {len(sigs) or 1} 个信源）"
    if item.get("metrics_badge"):
        reason += f" · {item['metrics_badge']}"

    tp = db.insert_topic({
        "account_id": acc["id"],
        "source_type": item["source_type"] or "rss",
        "source_name": item["source_name"] or "实时快讯",
        "source_url": item["source_url"],
        "raw_title": item["raw_title"] or item["title"],
        "raw_summary": item["summary"],
        "suggested_titles": suggested[:3],
        "raw_signals": sigs,
        "metrics_badge": item.get("metrics_badge") or "",
        "engagement_badge": item.get("engagement_badge") or "",
        "engagement": item.get("engagement") if isinstance(item.get("engagement"), dict) else {},
        "angle": angle,
        "reason": reason,
        "category": item.get("category") or "AI快讯",
        "score": 82 if item["credibility"] in ("一手官方", "多源印证") else 74,
        "status": "new",
    })
    db.mark_intel_promoted(intel_id, tp["id"])
    return {"topic": tp, "already_existed": False}


def translate_pending_intel(limit: int = 16) -> Dict[str, Any]:
    """把库里尚未翻译成中文的存量英文快讯批量译成中文标题与摘要。"""
    all_rows = db.list_intel_items(limit=200)
    pending = [r for r in all_rows if not _has_cjk(r.get("title") or "")][:limit]
    if not pending:
        return {"ok": True, "translated": 0, "remaining": 0}
    fake_items = [
        {
            "source_name": r.get("source_name") or r.get("source_type"),
            "source_type": r.get("source_type") or "",
            "raw_title": r.get("raw_title") or r.get("title") or "",
            "raw_summary": r.get("summary") or "",
        }
        for r in pending
    ]
    llm_map = _summarize_batch_with_llm(fake_items)
    updates: List[Dict[str, Any]] = []
    for i, r in enumerate(pending):
        ai_row = llm_map.get(i) or {}
        zh_title = str(ai_row.get("title") or "").strip()
        if not zh_title or not _has_cjk(zh_title):
            continue
        updates.append({
            "cluster_key": r["cluster_key"],
            "title": zh_title,
            "summary": str(ai_row.get("summary") or r.get("summary") or "").strip(),
            "raw_title": r.get("raw_title") or r.get("title") or "",
            "source_type": r.get("source_type") or "",
            "source_name": r.get("source_name") or "",
            "source_url": r.get("source_url") or "",
            "signals": r.get("signals") or [],
            "credibility": r.get("credibility") or "社区热议",
            "metrics_badge": r.get("metrics_badge") or "",
            "category": str(ai_row.get("category") or r.get("category") or "AI快讯").strip(),
            "tags": ai_row.get("tags") if isinstance(ai_row.get("tags"), list) else (r.get("tags") or []),
            "popularity": int(r.get("popularity") or 0),
        })
    if updates:
        db.upsert_intel_items(updates)
    after = db.list_intel_items(limit=200)
    remaining = sum(1 for r in after if not _has_cjk(r.get("title") or ""))
    return {"ok": True, "translated": len(updates), "remaining": remaining}
