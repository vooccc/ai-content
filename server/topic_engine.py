# -*- coding: utf-8 -*-
"""智能选题引擎：Query Expansion + 预匹配 + 多源共振 + is_real 过滤 + 高打开率标题翻写 + 数据复盘。"""
from __future__ import annotations

import csv
import difflib
import io
import json
import re
import time
from collections import defaultdict
from typing import Any, Dict, List, Optional

from . import db, llm_bridge, search_gather, sources
from .paths import data_dir

_NICHE_KEYWORDS = [
    ("ai", 12), ("agent", 14), ("llm", 10), ("claude", 14), ("cursor", 12),
    ("mcp", 14), ("deepseek", 12), ("openai", 10), ("自动化", 12), ("工作流", 12),
    ("一人公司", 16), ("独立开发", 14), ("副业", 10), ("变现", 10), ("效率", 10),
    ("实操", 12), ("开源", 10), ("prompt", 10), ("提示词", 10), ("python", 8),
    ("workflow", 10), ("rag", 10), ("skill", 10), ("solo", 10), ("indie", 10),
]

_FALLBACK_EXPANSIONS: Dict[str, List[str]] = {
    "ai工具实操": ["AI工具", "AI workflow", "AI automation", "MCP", "AI coding"],
    "一人公司": ["一人公司", "solo founder", "indie hacker", "one-person business", "独立开发"],
    "claude code": ["Claude Code", "claude-code", "Anthropic CLI", "Claude编程"],
    "ai agent": ["AI Agent", "autonomous agent", "multi-agent", "LangGraph", "Agentic"],
    "独立开发": ["独立开发", "indie dev", "side project", "SaaS", "micro-SaaS"],
}

_GENERIC_STOPWORDS = {
    "ai", "人工智能", "科技", "技术", "互联网", "工具", "软件", "视频", "教程",
    "python", "typescript", "github", "open", "source", "new", "app", "web",
}

_EXPANSION_CACHE_TTL = 7 * 86400


def _expansion_cache_path():
    return data_dir() / "query_expansions.json"


def _load_expansion_cache() -> Dict[str, Any]:
    p = _expansion_cache_path()
    if not p.exists():
        return {}
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_expansion_cache(cache: Dict[str, Any]) -> None:
    p = _expansion_cache_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")


def expand_keywords(keywords: List[str], account: Dict[str, Any] | None = None) -> List[str]:
    """Query Expansion：把种子关键词扩展成中英文变体/工具名（带 7 天本地缓存），禁止泛化词。"""
    seeds = [str(k).strip() for k in (keywords or []) if str(k).strip()]
    if not seeds:
        return []

    cache = _load_expansion_cache()
    now = time.time()
    all_terms: List[str] = []
    missing: List[str] = []

    for s in seeds:
        all_terms.append(s)
        entry = cache.get(s)
        if isinstance(entry, dict) and (now - float(entry.get("ts") or 0)) < _EXPANSION_CACHE_TTL:
            for t in entry.get("terms") or []:
                if str(t).strip() and str(t).strip().lower() not in _GENERIC_STOPWORDS:
                    all_terms.append(str(t).strip())
        else:
            missing.append(s)

    if missing:
        llm_map: Dict[str, List[str]] = {}
        try:
            prompt = (
                "请将以下自媒体选题种子词扩展为检索用的具体变体（大小写、英文原名、缩写、常见工具/框架别名），"
                "严禁输出“人工智能”“科技”“软件”“工具”等过于宽泛的词。\n"
                f"种子词：{json.dumps(missing, ensure_ascii=False)}\n"
                '只返回 JSON 对象，例如：{"Claude Code": ["claude-code", "Anthropic CLI", "Claude编程"]}'
            )
            raw = llm_bridge.chat_completion(
                [{"role": "user", "content": prompt}],
                temperature=0.2,
                max_tokens=1500,
                timeout=20,
                prefer_fast=True,
            )
            m = re.search(r"(\{[\s\S]*\})", raw)
            if m:
                parsed = json.loads(m.group(1))
                if isinstance(parsed, dict):
                    llm_map = parsed
        except Exception:
            llm_map = {}

        for s in missing:
            variants = llm_map.get(s) or _FALLBACK_EXPANSIONS.get(s.lower(), [])
            clean_vars = [
                str(v).strip()
                for v in variants
                if str(v).strip() and str(v).strip().lower() not in _GENERIC_STOPWORDS
            ][:8]
            cache[s] = {"ts": now, "terms": clean_vars}
            all_terms.extend(clean_vars)
        try:
            _save_expansion_cache(cache)
        except Exception:
            pass

    return list(dict.fromkeys(all_terms))


def pre_match_keywords(item: Dict[str, Any], expanded_terms: List[str]) -> List[str]:
    """零成本本地文本预匹配，返回命中的扩展词列表。"""
    text = f"{item.get('raw_title', '')} {item.get('raw_summary', '')}".lower()
    hits: List[str] = []
    for term in expanded_terms:
        t = term.strip()
        if len(t) < 2:
            continue
        if t.lower() in text:
            hits.append(t)
    return list(dict.fromkeys(hits))


def _extract_entities(item: Dict[str, Any]) -> List[str]:
    """提取用于跨源共振检测的关键实体（仓库名 / 英文产品名 / 核心中文短语）。"""
    title = str(item.get("raw_title") or "")
    url = str(item.get("source_url") or "")
    entities: List[str] = []

    gh_m = re.search(r"github\.com/([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)", url, re.I)
    if gh_m:
        repo = gh_m.group(1).lower()
        entities.append(repo)
        entities.append(repo.split("/")[-1])

    for tok in re.findall(r"[A-Za-z][A-Za-z0-9_.-]{2,24}", title):
        low = tok.lower()
        if low not in _GENERIC_STOPWORDS and not low.startswith("http"):
            entities.append(low)

    for zh in ("一人公司", "独立开发", "claude code", "deepseek", "openclaw", "mcp"):
        if zh in title.lower():
            entities.append(zh)
    return list(dict.fromkeys(entities))


def _cluster_tokens(text: str) -> set[str]:
    """提取用于事件聚类的中英文混合 token（英文词 + 中文 2-gram + 单字）。"""
    s = (text or "").lower()
    tokens: set[str] = set()
    for w in re.findall(r"[a-z0-9][a-z0-9_.-]{1,24}", s):
        if w not in _GENERIC_STOPWORDS:
            tokens.add(w)
    zh_chars = re.findall(r"[\u4e00-\u9fff]", s)
    for ch in zh_chars:
        tokens.add(ch)
    for i in range(len(zh_chars) - 1):
        tokens.add(zh_chars[i] + zh_chars[i + 1])
    return tokens


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    inter = len(a & b)
    if inter == 0:
        return 0.0
    return inter / len(a | b)


def compute_viral_badge(plays: int, followers: int) -> tuple[str, int]:
    """计算低粉爆款倍数与评分加成（吸收小浣熊倍数信号）。"""
    if plays <= 0 or followers <= 0:
        return "", 0
    mult = plays / followers
    if followers < 10000 and mult >= 10:
        return f"低粉爆款 ×{int(mult)}", 14
    if mult >= 100:
        return f"异常爆款 ×{int(mult)}", 14
    if mult >= 10:
        return f"×{int(mult)}爆款", 8
    return "", 0


def cluster_candidates(items: List[Dict[str, Any]], threshold: float = 0.24) -> List[Dict[str, Any]]:
    """中英文事件聚类：把讨论同一事件/工具的多源素材聚成 1 张主卡，保留全部原始信源。"""
    clusters: List[Dict[str, Any]] = []
    source_labels = {
        "github_trending": "GitHub",
        "hackernews": "HN",
        "hf_papers": "HF论文",
        "reddit": "Reddit",
        "bluesky": "Bluesky",
        "bilibili": "B站",
        "weibo_hot": "微博热搜",
        "wechat_search": "公众号",
        "rss": "RSS",
        "import": "导入",
        "manual": "灵感",
    }

    for it in items:
        toks = _cluster_tokens(str(it.get("raw_title") or ""))
        ents = set(_extract_entities(it))
        placed = False
        for cl in clusters:
            sim = _jaccard(toks, cl["tokens"])
            overlap = ents & cl["entities"]
            shared_id = any(("/" in e or "-" in e or "_" in e) and len(e) >= 5 for e in overlap)
            if sim >= threshold or shared_id:
                cl["items"].append(it)
                cl["tokens"] |= toks
                cl["entities"] |= ents
                placed = True
                break
        if not placed:
            clusters.append({"items": [it], "tokens": set(toks), "entities": set(ents)})

    merged_out: List[Dict[str, Any]] = []
    for cl in clusters:
        group = cl["items"]
        # 挑综合信号最强的一条作主卡代表
        group.sort(
            key=lambda x: (
                bool(x.get("metrics_badge")),
                len(x.get("matched_terms") or []) > 0,
                int(x.get("popularity") or 0),
            ),
            reverse=True,
        )
        lead = dict(group[0])
        signals: List[Dict[str, Any]] = []
        seen_sig: set[str] = set()
        res_srcs: set[str] = set(lead.get("resonance_sources") or [])
        extra_summaries: List[str] = []
        best_badge = str(lead.get("metrics_badge") or "")
        best_bonus = int(lead.get("_viral_bonus") or 0)

        for g in group:
            st = str(g.get("source_type") or "")
            if st:
                res_srcs.add(source_labels.get(st, st))
            if int(g.get("_viral_bonus") or 0) > best_bonus:
                best_bonus = int(g.get("_viral_bonus") or 0)
                best_badge = str(g.get("metrics_badge") or best_badge)
            sig_key = f"{g.get('source_url') or ''}|{g.get('raw_title') or ''}"
            if sig_key not in seen_sig:
                seen_sig.add(sig_key)
                signals.append({
                    "source_type": st,
                    "source_name": str(g.get("source_name") or st),
                    "title": str(g.get("raw_title") or ""),
                    "url": str(g.get("source_url") or ""),
                    "popularity": int(g.get("popularity") or 0),
                    "badge": str(g.get("metrics_badge") or ""),
                })
            s_txt = str(g.get("raw_summary") or "").strip()
            if s_txt and s_txt not in extra_summaries and len(extra_summaries) < 3:
                extra_summaries.append(s_txt[:220])

        lead["raw_signals"] = signals
        lead["metrics_badge"] = best_badge
        lead["_viral_bonus"] = best_bonus
        if len(res_srcs) >= 2:
            lead["resonance_sources"] = sorted(res_srcs)
        if len(extra_summaries) > 1:
            lead["raw_summary"] = " || ".join(extra_summaries)[:800]
        merged_out.append(lead)
    return merged_out


def annotate_cross_source_resonance(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """检测跨多个独立数据源同时出现的热点实体（多源共振提权）。"""
    entity_sources: Dict[str, set[str]] = defaultdict(set)
    item_entities: List[List[str]] = []
    for it in items:
        ents = _extract_entities(it)
        item_entities.append(ents)
        st = str(it.get("source_type") or "")
        for e in ents:
            if st:
                entity_sources[e].add(st)

    source_labels = {
        "github_trending": "GitHub",
        "hackernews": "HN",
        "bilibili": "B站",
        "weibo_hot": "微博热搜",
        "wechat_search": "公众号",
        "rss": "RSS",
    }
    out: List[Dict[str, Any]] = []
    for it, ents in zip(items, item_entities):
        best_sources: set[str] = set()
        for e in ents:
            srcs = entity_sources.get(e, set())
            if len(srcs) > len(best_sources):
                best_sources = srcs
        res_list = sorted(source_labels.get(s, s) for s in best_sources) if len(best_sources) >= 2 else []
        out.append({**it, "resonance_sources": res_list})
    return out


def _norm_title(title: str) -> str:
    return re.sub(r"[\s\W_]+", "", (title or "").lower())


def _is_similar(a: str, b: str, threshold: float = 0.72) -> bool:
    na, nb = _norm_title(a), _norm_title(b)
    if not na or not nb:
        return False
    if na == nb or (len(na) >= 6 and (na in nb or nb in na)):
        return True
    return difflib.SequenceMatcher(None, na, nb).ratio() >= threshold


def dedupe_candidates(
    items: List[Dict[str, Any]],
    existing_urls: set[str],
    existing_titles: List[str],
) -> List[Dict[str, Any]]:
    kept: List[Dict[str, Any]] = []
    seen_urls = set(existing_urls)
    seen_titles = list(existing_titles)

    for item in items:
        url = str(item.get("source_url") or "").strip()
        title = str(item.get("raw_title") or "").strip()
        if not title:
            continue
        if url and url in seen_urls:
            continue
        if any(_is_similar(title, prev) for prev in seen_titles):
            continue
        if url:
            seen_urls.add(url)
        seen_titles.append(title)
        kept.append(item)
    return kept


def _heuristic_score_item(item: Dict[str, Any], account: Dict[str, Any]) -> Dict[str, Any]:
    text = f"{item.get('raw_title', '')} {item.get('raw_summary', '')}".lower()
    score = 50
    hits: List[str] = list(item.get("matched_terms") or [])
    for kw, pts in _NICHE_KEYWORDS:
        if kw in text:
            score += pts
            if kw not in hits:
                hits.append(kw)

    st = item.get("source_type")
    pop = int(item.get("popularity") or 0)
    if st == "github_trending":
        score += 12 if pop >= 200 else 6
    elif st == "hackernews":
        score += 12 if pop >= 100 else 6
    elif st == "bilibili":
        score += 10 if pop >= 5000 else 5
    elif st == "weibo_hot":
        score += 10

    res_sources = item.get("resonance_sources") or []
    if len(res_sources) >= 2:
        score += 10
    score += int(item.get("_viral_bonus") or 0)

    score = max(35, min(98, score))

    raw_title = str(item.get("raw_title") or "").strip()
    short_name = raw_title.split("：")[0].split(":")[0].strip()[:26]
    if st == "github_trending":
        cat = "周二实操"
        titles = [
            f"实测 {short_name}：我用它把重复操作压缩到了 5 分钟（附上手步骤）",
            f"GitHub 今日飙升的 {short_name}，到底值不值得一人公司接入？",
            f"别再手动折腾了！开源项目 {short_name} 的真实用法与避坑清单",
        ]
        angle = f"聚焦 {short_name} 的真实安装、跑通效果与一人公司提效场景"
    elif st == "bilibili":
        cat = "周二实操"
        titles = [
            f"把「{short_name}」拆成图文实操笔记：5 分钟看懂最核心做法",
            f"B 站热议的 {short_name}，我替你实测了一遍真实效果",
            f"围绕 {short_name}，新手最容易踩的 3 个坑都在这了",
        ]
        angle = f"把视频实操拆解成步骤清晰的图文教程与踩坑总结"
    elif st == "weibo_hot":
        cat = "周六深度"
        titles = [
            f"「{short_name}」冲上热搜，但真正与一人公司有关的其实是这件事",
            f"热搜背后的冷思考：{short_name} 会怎样改写我们的工作流？",
            f"别只看热闹：从「{short_name}」看接下来半年的真实机会",
        ]
        angle = f"借大众热搜破圈流量切入，落回一人公司与 AI 提效本质"
    elif st == "wechat_search":
        cat = "周六深度"
        titles = [
            f"都在聊「{short_name}」，真正能落地变现的其实只有这一步",
            f"拆解 {short_name}：独立开发者该怎么借力而不被概念割韭菜？",
            f"关于 {short_name}，我实测一周后的 3 条真实结论",
        ]
        angle = f"用个人真实实测与一人公司视角拆解「{short_name}」"
    else:
        cat = "周二实操"
        titles = [
            f"{short_name} 火了，我按教程跑了一遍，这 3 个坑先替你踩了",
            f"把 {short_name} 接进日常工作流：成本、效果与替代方案实测",
            f"一人公司怎么用好 {short_name}？一份不吹牛的实操笔记",
        ]
        angle = "提炼核心可复用做法，写成带步骤的实操测评"

    reason_parts: List[str] = []
    if len(res_sources) >= 2:
        reason_parts.append(f"多源共振（{'+'.join(res_sources)}同时热议）")
    if hits:
        reason_parts.append(f"命中关键词（{', '.join(hits[:4])}）")
    if not reason_parts:
        reason_parts.append("可结合账号的 AI 提效与一人公司视角做实测拆解")

    return {
        **item,
        "score": score,
        "suggested_titles": titles,
        "angle": angle,
        "reason": "；".join(reason_parts),
        "category": cat,
    }


def _extract_json_array(text: str) -> Optional[List[Dict[str, Any]]]:
    s = (text or "").strip()
    m = re.search(r"```(?:json)?\s*(\[[\s\S]*\])\s*```", s)
    if m:
        s = m.group(1)
    else:
        m2 = re.search(r"(\[[\s\S]*\])", s)
        if m2:
            s = m2.group(1)
    try:
        data = json.loads(s)
        return data if isinstance(data, list) else None
    except Exception:
        return None


def _score_and_rewrite_with_llm(
    candidates: List[Dict[str, Any]],
    account: Dict[str, Any],
    top_n: int = 10,
) -> Optional[List[Dict[str, Any]]]:
    if not candidates:
        return []
    brief_list = []
    for idx, it in enumerate(candidates[:18]):
        brief_list.append({
            "idx": idx,
            "source": it.get("source_name"),
            "title": it.get("raw_title"),
            "summary": str(it.get("raw_summary") or "")[:220],
            "matched_terms": it.get("matched_terms") or [],
            "resonance_sources": it.get("resonance_sources") or [],
            "popularity": int(it.get("popularity") or 0),
        })

    top_metrics = sorted(db.list_metrics(limit=30), key=lambda m: int(m.get("read_user") or 0), reverse=True)[:5]
    top_titles = [m["title"] for m in top_metrics if m.get("title")]

    sys_prompt = (
        "你是一位资深公众号主编，专门服务「AI 工具实操 + 一人公司真实经验」账号。\n"
        "你的任务是从候选素材中剔除假消息/营销洗稿水文，筛选最容易拿高打开率、高收藏率的真实选题，并翻写成让人想点开的公众号标题。\n"
        "输出必须是严格 JSON 数组，不要任何多余解释。"
    )
    user_prompt = (
        f"【账号定位】\n"
        f"- 赛道：{account.get('niche')}\n"
        f"- 目标读者：{account.get('audience')}\n"
        f"- 栏目节奏：{account.get('cadence')}\n"
        f"- 高打开率标题公式：\n  " + "\n  ".join(account.get("title_formulas") or []) + "\n"
        + (f"- 近期高阅读历史标题参考：{json.dumps(top_titles, ensure_ascii=False)}\n" if top_titles else "")
        + f"\n【候选素材（共 {len(brief_list)} 条）】\n"
        + json.dumps(brief_list, ensure_ascii=False, indent=2)
        + f"\n\n【筛选规则】\n"
        "1. 必须评估 is_real：遇到无实质内容的标题党、SEO 内容农场洗稿、纯情绪焦虑贩卖或无来源传闻，设 is_real=false 直接淘汰。\n"
        "2. 优先保留有客观热度（popularity 高）、命中 matched_terms 或跨多源共振（resonance_sources 非空）且能写实操步骤/避坑/测评的选题。\n"
        f"3. 挑选最契合的最多 {top_n} 条，每条返回 JSON 对象：\n"
        "[\n"
        "  {\n"
        '    "idx": 0,\n'
        '    "is_real": true,\n'
        '    "score": 88,\n'
        '    "category": "周二实操 | 周四互动 | 周六深度",\n'
        '    "suggested_titles": ["标题1(数字实操型)", "标题2(反常识避坑型)", "标题3(对比测评型)"],\n'
        '    "angle": "切入角度（一句话说明怎么写更有干货和活人感）",\n'
        '    "reason": "推荐理由（为什么真实有价值且容易拿高打开率）"\n'
        "  }\n"
        "]"
    )
    try:
        raw = llm_bridge.chat_completion(
            [{"role": "system", "content": sys_prompt}, {"role": "user", "content": user_prompt}],
            temperature=0.4,
            max_tokens=4096,
            timeout=40,
            prefer_fast=True,
        )
    except Exception:
        return None

    parsed = _extract_json_array(raw)
    if not parsed:
        return None

    out: List[Dict[str, Any]] = []
    for row in parsed:
        if not isinstance(row, dict):
            continue
        if row.get("is_real") is False:
            continue
        idx = row.get("idx")
        if not isinstance(idx, int) or idx < 0 or idx >= len(candidates):
            continue
        base = candidates[idx]
        score = int(row.get("score") or 70)
        res_sources = base.get("resonance_sources") or []
        if len(res_sources) >= 2:
            score = min(99, score + 5)
        if base.get("_viral_bonus"):
            score = min(99, score + min(8, int(base["_viral_bonus"])))
        matched = base.get("matched_terms") or []
        if not matched and score < 65 and base.get("source_type") not in ("github_trending", "manual", "import"):
            continue
        if score < 55:
            continue
        titles = [str(t).strip() for t in (row.get("suggested_titles") or []) if str(t).strip()]
        if not titles:
            titles = [base["raw_title"]]
        reason = str(row.get("reason") or "").strip()
        if len(res_sources) >= 2 and "共振" not in reason:
            reason = f"多源共振（{'+'.join(res_sources)}）；{reason}" if reason else f"多源共振（{'+'.join(res_sources)}）"
        out.append({
            **base,
            "score": max(0, min(100, score)),
            "category": str(row.get("category") or "周二实操").strip(),
            "suggested_titles": titles[:3],
            "angle": str(row.get("angle") or "").strip(),
            "reason": reason,
        })
    out.sort(key=lambda x: x["score"], reverse=True)
    return out[:top_n]


def refresh_topics(max_new: int = 8) -> Dict[str, Any]:
    """Query Expansion -> 多源抓取 -> 去重与预匹配 -> 多源共振 -> LLM(is_real+打分+翻写) -> 入库。"""
    account = db.get_primary_account()
    sc = account.get("sources_config") or {}
    seed_keywords = list(sc.get("wechat_keywords") or ["AI工具实操", "一人公司", "Claude Code", "AI Agent"])
    expanded_terms = expand_keywords(seed_keywords, account)

    gathered = sources.gather_all_sources(sc, search_terms=expanded_terms)
    raw_items = gathered["items"]
    existing_urls, existing_titles = db.recent_topic_keys(days=30)
    candidates = dedupe_candidates(raw_items, existing_urls, existing_titles)

    if not candidates:
        return {
            "ok": True,
            "fetched": len(raw_items),
            "deduped": 0,
            "added": 0,
            "mode": "none",
            "expanded_terms": expanded_terms,
            "stats": gathered["stats"],
            "errors": gathered["errors"],
        }

    # 预匹配 + 低粉爆款计算 + 多源共振标注 + 同事件聚类合并
    annotated: List[Dict[str, Any]] = []
    for it in candidates:
        matched = pre_match_keywords(it, expanded_terms)
        badge, v_bonus = compute_viral_badge(int(it.get("plays") or 0), int(it.get("followers") or 0))
        annotated.append({
            **it,
            "matched_terms": matched,
            "metrics_badge": badge or str(it.get("metrics_badge") or ""),
            "_viral_bonus": v_bonus,
        })
    annotated = annotate_cross_source_resonance(annotated)
    annotated = cluster_candidates(annotated)
    # 优先把低粉爆款、跨源共振、命中关键词、高热度候选排在前面送入模型
    annotated.sort(
        key=lambda x: (
            bool(x.get("metrics_badge")),
            len(x.get("resonance_sources") or []) >= 2,
            len(x.get("matched_terms") or []) > 0,
            int(x.get("popularity") or 0),
        ),
        reverse=True,
    )

    scored = _score_and_rewrite_with_llm(annotated, account, top_n=max_new)
    mode = "llm"
    if scored is None:
        mode = "heuristic"
        scored = [_heuristic_score_item(it, account) for it in annotated]
        scored.sort(key=lambda x: x["score"], reverse=True)
        scored = scored[:max_new]

    inserted: List[Dict[str, Any]] = []
    for item in scored:
        tp = db.insert_topic({
            "account_id": account["id"],
            "source_type": item.get("source_type") or "rss",
            "source_name": item.get("source_name") or "",
            "source_url": item.get("source_url") or "",
            "raw_title": item.get("raw_title") or "",
            "raw_summary": item.get("raw_summary") or "",
            "suggested_titles": item.get("suggested_titles") or [],
            "raw_signals": item.get("raw_signals") or [],
            "metrics_badge": item.get("metrics_badge") or "",
            "angle": item.get("angle") or "",
            "reason": item.get("reason") or "",
            "category": item.get("category") or "周二实操",
            "score": int(item.get("score") or 70),
            "status": "new",
        })
        inserted.append(tp)

    # 持久化本次抓取战果，让选题池随时能看见每个源抓回了多少条及报错
    try:
        sc_now = dict(account.get("sources_config") or {})
        sc_now["last_fetch_stats"] = gathered.get("stats") or {}
        sc_now["last_rss_stats"] = gathered.get("rss_detail") or {}
        sc_now["last_fetch_errors"] = (gathered.get("errors") or [])[:10]
        sc_now["last_fetch_at"] = time.time()
        db.update_primary_account({"sources_config": sc_now})
    except Exception:
        pass

    return {
        "ok": True,
        "fetched": len(raw_items),
        "deduped": len(candidates),
        "added": len(inserted),
        "mode": mode,
        "expanded_terms": expanded_terms,
        "stats": gathered["stats"],
        "rss_detail": gathered.get("rss_detail") or {},
        "errors": gathered["errors"],
        "topics": inserted,
    }


def create_manual_topic(idea: str, source_url: str = "") -> Dict[str, Any]:
    """手动投喂灵感或 URL：自动抓摘要 + 生成 3 个高打开率标题并入选题池。"""
    account = db.get_primary_account()
    raw_title = (idea or "").strip()
    raw_summary = ""
    url = (source_url or "").strip()
    if url and not raw_title:
        raw_title = url

    if url.startswith("http://") or url.startswith("https://"):
        try:
            fetched = search_gather.fetch_url_text(url)
            if fetched.get("ok"):
                if not raw_title or raw_title == url:
                    raw_title = str(fetched.get("title") or url).strip()
                raw_summary = str(fetched.get("content") or "")[:1200]
        except Exception:
            pass

    if not raw_summary:
        raw_summary = raw_title

    candidate = {
        "source_type": "manual",
        "source_name": "灵感投喂",
        "source_url": url,
        "raw_title": raw_title[:120],
        "raw_summary": raw_summary,
        "popularity": 0,
        "matched_terms": [raw_title[:20]],
        "resonance_sources": [],
    }
    scored = _score_and_rewrite_with_llm([candidate], account, top_n=1)
    item = scored[0] if scored else _heuristic_score_item(candidate, account)
    item["score"] = max(80, int(item.get("score") or 80))
    return db.insert_topic({
        "account_id": account["id"],
        "source_type": "manual",
        "source_name": "灵感投喂",
        "source_url": url,
        "raw_title": item["raw_title"],
        "raw_summary": raw_summary,
        "suggested_titles": item.get("suggested_titles") or [raw_title],
        "angle": item.get("angle") or "",
        "reason": item.get("reason") or "手动投喂灵感，优先排入待写队列",
        "category": item.get("category") or "周二实操",
        "score": item["score"],
        "status": "new",
    })


def review_metrics_with_ai() -> Dict[str, Any]:
    """结合文章列表与数据表现做本周复盘，并给出可一键采纳的策略建议。"""
    account = db.get_primary_account()
    metrics = db.list_metrics(limit=40)
    articles = db.list_articles(limit=40)
    if not metrics:
        return {
            "ok": True,
            "summary": "暂无文章数据记录。先推送几篇文章并点击「同步公众号数据」或手动补录阅读/收藏数据后，即可生成复盘分析。",
            "highlights": [],
            "suggested_title_formulas": [],
            "suggested_banned_words": [],
        }

    rows_brief = [
        {
            "date": m.get("ref_date"),
            "title": m.get("title"),
            "target_user": m.get("target_user"),
            "read_user": m.get("read_user"),
            "share_count": m.get("share_count"),
            "fav_count": m.get("fav_count"),
            "like_count": m.get("like_count"),
            "notes": m.get("notes"),
        }
        for m in metrics[:20]
    ]
    prompt = (
        f"你是公众号运营分析师。请分析这个「{account.get('niche')}」账号最近的文章表现：\n"
        f"{json.dumps(rows_brief, ensure_ascii=False, indent=2)}\n\n"
        f"当前已记录文章数：{len(articles)}。\n"
        "请返回严格 JSON 对象：\n"
        "{\n"
        '  "summary": "200字以内直奔本质的复盘结论（哪类标题/题材打开率高、哪类收藏分享高、接下来一周重点写什么）",\n'
        '  "highlights": ["洞察1", "洞察2", "洞察3"],\n'
        '  "suggested_title_formulas": ["可补充进账号的标题公式1", "标题公式2"],\n'
        '  "suggested_banned_words": ["建议屏蔽的低效套话词"]\n'
        "}"
    )
    try:
        raw = llm_bridge.chat_completion(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
            max_tokens=1200,
            timeout=35,
            prefer_fast=True,
        )
        m = re.search(r"(\{[\s\S]*\})", raw)
        if m:
            parsed = json.loads(m.group(1))
            if isinstance(parsed, dict) and parsed.get("summary"):
                return {
                    "ok": True,
                    "summary": str(parsed.get("summary") or ""),
                    "highlights": [str(x) for x in (parsed.get("highlights") or [])],
                    "suggested_title_formulas": [str(x) for x in (parsed.get("suggested_title_formulas") or [])],
                    "suggested_banned_words": [str(x) for x in (parsed.get("suggested_banned_words") or [])],
                }
    except Exception:
        pass

    total_reads = sum(int(m.get("read_user") or 0) for m in metrics)
    total_favs = sum(int(m.get("fav_count") or 0) for m in metrics)
    best = max(metrics, key=lambda m: int(m.get("read_user") or 0))
    return {
        "ok": True,
        "summary": (
            f"近期共统计 {len(metrics)} 条数据，累计阅读人数 {total_reads}、收藏 {total_favs}。"
            f"目前表现最好的是《{best.get('title')}》（阅读 {best.get('read_user')} / 收藏 {best.get('fav_count')}），"
            "建议继续放大同类实操/具体案例题材。"
        ),
        "highlights": [
            f"最高阅读：《{best.get('title')}》",
            f"累计收藏：{total_favs}（收藏高通常代表教程/清单类干货更受认可）",
        ],
        "suggested_title_formulas": [],
        "suggested_banned_words": [],
    }


def _parse_cn_num(val: Any) -> int:
    s = str(val or "").strip().lower().replace(",", "").replace("+", "")
    if not s:
        return 0
    m = re.match(r"^(\d+(?:\.\d+)?)\s*([万w千k])?$", s)
    if not m:
        digits = re.sub(r"[^\d.]", "", s)
        try:
            return int(float(digits)) if digits else 0
        except Exception:
            return 0
    num = float(m.group(1))
    unit = m.group(2)
    if unit in ("万", "w"):
        num *= 10000
    elif unit in ("千", "k"):
        num *= 1000
    return int(num)


_IMPORT_ALIAS = {
    "title": ("标题", "title", "主题", "作品", "名称"),
    "author": ("作者", "author", "账号", "昵称", "博主", "up主"),
    "followers": ("粉丝", "粉丝数", "followers", "关注"),
    "plays": ("播放", "播放量", "plays", "views", "阅读", "阅读量"),
    "likes": ("点赞", "点赞数", "likes", "赞", "赞藏"),
    "platform": ("平台", "platform", "来源平台"),
    "link": ("链接", "link", "url", "来源链接"),
    "source": ("来源", "source", "信源"),
}


def parse_import_text(text: str) -> Dict[str, Any]:
    """解析粘贴的 CSV / 制表符表格 / JSON 爆款清单（支持中文表头与 5万 简写）。"""
    t = (text or "").strip()
    if not t:
        return {"items": [], "error": "内容为空"}

    records: List[Dict[str, str]] = []
    if t[0] in ("[", "{"):
        try:
            obj = json.loads(t)
        except Exception as e:
            return {"items": [], "error": f"JSON 解析失败：{e}"}
        arr = obj if isinstance(obj, list) else (obj.get("items") or obj.get("works") or obj.get("signals") if isinstance(obj, dict) else None)
        if not isinstance(arr, list):
            return {"items": [], "error": "JSON 需要是数组，或包含 items/works/signals 数组"}
        for it in arr:
            if not isinstance(it, dict):
                continue
            rec: Dict[str, str] = {}
            for k, aliases in _IMPORT_ALIAS.items():
                for a in aliases:
                    if it.get(a) is not None:
                        rec[k] = str(it[a])
                        break
            records.append(rec)
    else:
        # 自动识别制表符（从 Excel/飞书直接复制）或逗号分隔
        first_line = t.splitlines()[0] if t.splitlines() else ""
        delimiter = "\t" if ("\t" in first_line and "," not in first_line) else ","
        rows = list(csv.reader(io.StringIO(t), delimiter=delimiter))
        rows = [r for r in rows if any(str(c).strip() for c in r)]
        if not rows:
            return {"items": [], "error": "没有解析到有效行"}
        head = [str(c).strip().lower() for c in rows[0]]
        has_header = any(h in _IMPORT_ALIAS["title"] or h in _IMPORT_ALIAS["source"] for h in head)
        idx_map: Dict[str, int] = {"title": 0, "author": 1, "followers": 2, "plays": 3, "likes": 4, "platform": 5, "link": 6, "source": 7}
        if has_header:
            idx_map = {}
            for k, aliases in _IMPORT_ALIAS.items():
                idx_map[k] = next((i for i, h in enumerate(head) if h in aliases), -1)
            if idx_map.get("title", -1) < 0:
                return {"items": [], "error": "表头里找不到「标题 / title」列"}
            rows = rows[1:]
        for r in rows:
            rec = {}
            for k, col_i in idx_map.items():
                if col_i >= 0 and col_i < len(r):
                    rec[k] = str(r[col_i]).strip()
            records.append(rec)

    items: List[Dict[str, Any]] = []
    skipped_empty = 0
    for rec in records:
        title = (rec.get("title") or "").strip()
        if not title:
            skipped_empty += 1
            continue
        author = (rec.get("author") or "").strip()
        platform = (rec.get("platform") or rec.get("source") or "外部爆款").strip()
        followers = _parse_cn_num(rec.get("followers"))
        plays = _parse_cn_num(rec.get("plays"))
        likes = _parse_cn_num(rec.get("likes"))
        link = (rec.get("link") or "").strip()
        badge, v_bonus = compute_viral_badge(plays, followers)
        src_label = f"{platform}·{author}" if author and author not in platform else platform
        summary_bits = []
        if plays:
            summary_bits.append(f"播放/阅读 {plays:,}")
        if followers:
            summary_bits.append(f"粉丝 {followers:,}")
        if likes:
            summary_bits.append(f"点赞 {likes:,}")
        if badge:
            summary_bits.append(badge)
        items.append({
            "source_type": "import",
            "source_name": src_label,
            "source_url": link,
            "raw_title": title,
            "raw_summary": " | ".join(summary_bits) if summary_bits else title,
            "plays": plays,
            "followers": followers,
            "likes": likes,
            "popularity": plays + likes * 10,
            "metrics_badge": badge,
            "_viral_bonus": v_bonus,
        })
    if not items:
        return {"items": [], "error": "没有解析到有效选题行（标题为空）"}
    return {"items": items, "skipped_empty": skipped_empty}


def import_topics_from_text(text: str, dry_run: bool = False) -> Dict[str, Any]:
    """解析并导入爆款/信号清单，支持预览去重与低粉爆款倍数计算。"""
    parsed = parse_import_text(text)
    if parsed.get("error"):
        return {"ok": False, "error": parsed["error"]}

    raw_items = parsed["items"]
    existing_urls, existing_titles = db.recent_topic_keys(days=30)
    candidates = dedupe_candidates(raw_items, existing_urls, existing_titles)
    dup_count = len(raw_items) - len(candidates)
    low_fan_count = sum(1 for it in candidates if "低粉爆款" in (it.get("metrics_badge") or ""))

    if dry_run:
        return {
            "ok": True,
            "dry_run": True,
            "total": len(raw_items),
            "new_count": len(candidates),
            "dup_count": dup_count,
            "low_fan_count": low_fan_count,
            "preview": [
                {
                    "title": it["raw_title"],
                    "source_name": it["source_name"],
                    "metrics_badge": it.get("metrics_badge") or "",
                    "summary": it["raw_summary"],
                }
                for it in candidates[:5]
            ],
        }

    account = db.get_primary_account()
    inserted: List[Dict[str, Any]] = []
    for it in candidates:
        scored = _heuristic_score_item(it, account)
        tp = db.insert_topic({
            "account_id": account["id"],
            "source_type": "import",
            "source_name": it["source_name"],
            "source_url": it.get("source_url") or "",
            "raw_title": it["raw_title"],
            "raw_summary": it["raw_summary"],
            "suggested_titles": scored.get("suggested_titles") or [it["raw_title"]],
            "raw_signals": [{
                "source_type": "import",
                "source_name": it["source_name"],
                "title": it["raw_title"],
                "url": it.get("source_url") or "",
                "popularity": int(it.get("popularity") or 0),
                "badge": it.get("metrics_badge") or "",
            }],
            "metrics_badge": it.get("metrics_badge") or "",
            "angle": scored.get("angle") or "",
            "reason": (f"{it['metrics_badge']}；" if it.get("metrics_badge") else "") + (scored.get("reason") or "导入爆款清单"),
            "category": scored.get("category") or "周二实操",
            "score": int(scored.get("score") or 75),
            "status": "new",
        })
        inserted.append(tp)

    return {
        "ok": True,
        "dry_run": False,
        "total": len(raw_items),
        "added": len(inserted),
        "dup_count": dup_count,
        "low_fan_count": low_fan_count,
        "topics": inserted,
    }
