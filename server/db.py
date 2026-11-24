# -*- coding: utf-8 -*-
"""ai-content SQLite 数据底座：账号定位 / 选题池 / 文章归档 / 数据表现。"""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from contextlib import contextmanager
from typing import Any, Dict, Iterator, List, Optional

from .paths import db_path

_INIT_LOCK = threading.Lock()
_INITIALIZED_PATHS: set[str] = set()

DEFAULT_ACCOUNT_ID = "primary"

DEFAULT_ACCOUNT_SEED: Dict[str, Any] = {
    "id": DEFAULT_ACCOUNT_ID,
    "name": "AI 工具实操 + 一人公司",
    "niche": "AI 工具实操 + 一人公司真实经验",
    "audience": "想用 AI 提效的独立开发者、自由职业者、副业探索者与小团队负责人",
    "cadence": "周二实操教程（1500-2000字） / 周四轻量互动问答（800-1200字） / 周六深度复盘思考（2000-2500字）",
    "title_formulas": [
        "数字具象：我用 XX 把原本 3 小时的流程压到了 10 分钟（附完整步骤）",
        "反常识避坑：别再盲目追 XX 了，真正卡住你的其实是这一步",
        "实测对比：实测 5 个 AI 工具后，我只留下了这一个",
    ],
    "banned_words": [
        "总而言之",
        "综上所述",
        "值得注意的是",
        "在这个快速发展的时代",
        "让我们一起来",
        "赋能",
        "抓手",
        "闭环",
        "不言而喻",
        "毫无疑问",
    ],
    "default_style": "khazix",
    "default_theme": "moyu_green",
    "wechat_account_id": "",
    "footer_template": "你最近在用哪个 AI 工具？欢迎在评论区聊聊你的真实体验。",
    "sources_config": {
        "github_trending": True,
        "github_languages": ["python", "typescript", ""],
        "hackernews": True,
        "hf_papers": True,
        "reddit": True,
        "reddit_subreddits": ["LocalLLaMA", "ClaudeAI", "MachineLearning"],
        "bluesky": True,
        "bluesky_accounts": [
            "karpathy.bsky.social",
            "simonwillison.net",
            "hardmaru.bsky.social",
            "emollick.bsky.social",
            "swyx.io",
        ],
        "x": True,
        "x_mode": "following",
        "x_list_id": "",
        "x_search_enabled": True,
        "x_search_keywords": ["AI Agent", "Claude Code", "OpenAI", "LLM"],
        "x_min_faves": 100,
        "xiaohongshu": True,
        "xhs_mode": "xhshow",
        "xhs_category": "homefeed.career_v3",
        "xhs_keywords": ["AI工具", "AI Agent", "一人公司"],
        "bilibili": True,
        "bilibili_accounts": [],
        "weibo_hot": True,
        "wechat_search": True,
        "wechat_keywords": ["AI工具实操", "一人公司", "Claude Code", "AI Agent", "独立开发"],
        "rss_feeds": [
            {"name": "阮一峰的网络日志", "url": "https://www.ruanyifeng.com/blog/atom.xml"},
            {"name": "少数派", "url": "https://sspai.com/feed"},
        ],
        "daily_fetch_enabled": True,
        "daily_fetch_time": "08:00",
        "daily_metrics_sync_enabled": True,
        "daily_metrics_sync_time": "09:30",
    },
}


def _connect() -> sqlite3.Connection:
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(p), timeout=15, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_db() -> None:
    p_str = str(db_path().resolve())
    if p_str in _INITIALIZED_PATHS:
        return
    with _INIT_LOCK:
        if p_str in _INITIALIZED_PATHS:
            return
        conn = _connect()
        try:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS accounts (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    niche TEXT NOT NULL DEFAULT '',
                    audience TEXT NOT NULL DEFAULT '',
                    cadence TEXT NOT NULL DEFAULT '',
                    title_formulas_json TEXT NOT NULL DEFAULT '[]',
                    banned_words_json TEXT NOT NULL DEFAULT '[]',
                    default_style TEXT NOT NULL DEFAULT 'khazix',
                    default_theme TEXT NOT NULL DEFAULT 'moyu_green',
                    wechat_account_id TEXT NOT NULL DEFAULT '',
                    footer_template TEXT NOT NULL DEFAULT '',
                    sources_config_json TEXT NOT NULL DEFAULT '{}',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE TABLE IF NOT EXISTS topics (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL DEFAULT 'primary',
                    source_type TEXT NOT NULL DEFAULT 'manual',
                    source_name TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    raw_title TEXT NOT NULL,
                    raw_summary TEXT NOT NULL DEFAULT '',
                    suggested_titles_json TEXT NOT NULL DEFAULT '[]',
                    angle TEXT NOT NULL DEFAULT '',
                    reason TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT '实操教程',
                    score INTEGER NOT NULL DEFAULT 60,
                    status TEXT NOT NULL DEFAULT 'new',
                    project_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_topics_status_score
                    ON topics(status, score DESC, created_at DESC);
                CREATE INDEX IF NOT EXISTS idx_topics_source_url
                    ON topics(source_url);

                CREATE TABLE IF NOT EXISTS articles (
                    id TEXT PRIMARY KEY,
                    account_id TEXT NOT NULL DEFAULT 'primary',
                    topic_id TEXT NOT NULL DEFAULT '',
                    project_id TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL,
                    style TEXT NOT NULL DEFAULT '',
                    theme TEXT NOT NULL DEFAULT '',
                    word_count INTEGER NOT NULL DEFAULT 0,
                    draft_media_id TEXT NOT NULL DEFAULT '',
                    msgid TEXT NOT NULL DEFAULT '',
                    status TEXT NOT NULL DEFAULT 'draft',
                    published_at TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_articles_created
                    ON articles(created_at DESC);

                CREATE TABLE IF NOT EXISTS metrics (
                    id TEXT PRIMARY KEY,
                    article_id TEXT NOT NULL DEFAULT '',
                    account_id TEXT NOT NULL DEFAULT 'primary',
                    ref_date TEXT NOT NULL,
                    msgid TEXT NOT NULL DEFAULT '',
                    title TEXT NOT NULL DEFAULT '',
                    target_user INTEGER NOT NULL DEFAULT 0,
                    read_user INTEGER NOT NULL DEFAULT 0,
                    read_count INTEGER NOT NULL DEFAULT 0,
                    ori_read_user INTEGER NOT NULL DEFAULT 0,
                    share_count INTEGER NOT NULL DEFAULT 0,
                    fav_count INTEGER NOT NULL DEFAULT 0,
                    like_count INTEGER NOT NULL DEFAULT 0,
                    source TEXT NOT NULL DEFAULT 'manual',
                    notes TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_metrics_date
                    ON metrics(ref_date DESC, updated_at DESC);

                CREATE TABLE IF NOT EXISTS intel_items (
                    id TEXT PRIMARY KEY,
                    cluster_key TEXT NOT NULL UNIQUE,
                    title TEXT NOT NULL,
                    summary TEXT NOT NULL DEFAULT '',
                    raw_title TEXT NOT NULL DEFAULT '',
                    source_type TEXT NOT NULL DEFAULT '',
                    source_name TEXT NOT NULL DEFAULT '',
                    source_url TEXT NOT NULL DEFAULT '',
                    signals_json TEXT NOT NULL DEFAULT '[]',
                    credibility TEXT NOT NULL DEFAULT '社区热议',
                    metrics_badge TEXT NOT NULL DEFAULT '',
                    category TEXT NOT NULL DEFAULT 'AI快讯',
                    tags_json TEXT NOT NULL DEFAULT '[]',
                    popularity INTEGER NOT NULL DEFAULT 0,
                    promoted_topic_id TEXT NOT NULL DEFAULT '',
                    created_at REAL NOT NULL,
                    updated_at REAL NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_intel_updated
                    ON intel_items(updated_at DESC, popularity DESC);
                """
            )
            existing_cols = {r["name"] for r in conn.execute("PRAGMA table_info(topics)").fetchall()}
            if "raw_signals_json" not in existing_cols:
                conn.execute("ALTER TABLE topics ADD COLUMN raw_signals_json TEXT NOT NULL DEFAULT '[]'")
            if "metrics_badge" not in existing_cols:
                conn.execute("ALTER TABLE topics ADD COLUMN metrics_badge TEXT NOT NULL DEFAULT ''")
            if "engagement_badge" not in existing_cols:
                conn.execute("ALTER TABLE topics ADD COLUMN engagement_badge TEXT NOT NULL DEFAULT ''")
            if "engagement_json" not in existing_cols:
                conn.execute("ALTER TABLE topics ADD COLUMN engagement_json TEXT NOT NULL DEFAULT '{}'")
            intel_cols = {r["name"] for r in conn.execute("PRAGMA table_info(intel_items)").fetchall()}
            if "engagement_badge" not in intel_cols:
                conn.execute("ALTER TABLE intel_items ADD COLUMN engagement_badge TEXT NOT NULL DEFAULT ''")
            if "engagement_json" not in intel_cols:
                conn.execute("ALTER TABLE intel_items ADD COLUMN engagement_json TEXT NOT NULL DEFAULT '{}'")
            now = time.time()
            cur = conn.execute("SELECT id FROM accounts WHERE id = ?", (DEFAULT_ACCOUNT_ID,))
            if not cur.fetchone():
                s = DEFAULT_ACCOUNT_SEED
                conn.execute(
                    """
                    INSERT INTO accounts (
                        id, name, niche, audience, cadence,
                        title_formulas_json, banned_words_json,
                        default_style, default_theme, wechat_account_id,
                        footer_template, sources_config_json, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        s["id"],
                        s["name"],
                        s["niche"],
                        s["audience"],
                        s["cadence"],
                        json.dumps(s["title_formulas"], ensure_ascii=False),
                        json.dumps(s["banned_words"], ensure_ascii=False),
                        s["default_style"],
                        s["default_theme"],
                        s["wechat_account_id"],
                        s["footer_template"],
                        json.dumps(s["sources_config"], ensure_ascii=False),
                        now,
                        now,
                    ),
                )
            conn.commit()
            _INITIALIZED_PATHS.add(p_str)
        finally:
            conn.close()


@contextmanager
def get_conn() -> Iterator[sqlite3.Connection]:
    ensure_db()
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def _parse_json(raw: Any, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except Exception:
        return fallback


def _row_to_account(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    sc = _parse_json(d.get("sources_config_json"), {})
    if not isinstance(sc, dict):
        sc = {}
    default_sc = DEFAULT_ACCOUNT_SEED["sources_config"]
    for k, v in default_sc.items():
        sc.setdefault(k, v)
    if isinstance(sc.get("rss_feeds"), list):
        sc["rss_feeds"] = [f for f in sc["rss_feeds"] if "hnrss.org" not in str((f or {}).get("url") or "")]
    return {
        "id": d["id"],
        "name": d["name"],
        "niche": d["niche"],
        "audience": d["audience"],
        "cadence": d["cadence"],
        "title_formulas": _parse_json(d.get("title_formulas_json"), []),
        "banned_words": _parse_json(d.get("banned_words_json"), []),
        "default_style": d.get("default_style") or "khazix",
        "default_theme": d.get("default_theme") or "moyu_green",
        "wechat_account_id": d.get("wechat_account_id") or "",
        "footer_template": d.get("footer_template") or "",
        "sources_config": sc,
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
    }


def get_primary_account() -> Dict[str, Any]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM accounts WHERE id = ?", (DEFAULT_ACCOUNT_ID,)).fetchone()
        if row:
            return _row_to_account(row)
        row = conn.execute("SELECT * FROM accounts ORDER BY created_at ASC LIMIT 1").fetchone()
        if row:
            return _row_to_account(row)
    return dict(DEFAULT_ACCOUNT_SEED)


def update_primary_account(patch: Dict[str, Any]) -> Dict[str, Any]:
    cur = get_primary_account()
    merged = {
        "name": str(patch.get("name", cur["name"])).strip() or cur["name"],
        "niche": str(patch.get("niche", cur["niche"])).strip(),
        "audience": str(patch.get("audience", cur["audience"])).strip(),
        "cadence": str(patch.get("cadence", cur["cadence"])).strip(),
        "title_formulas": patch.get("title_formulas", cur["title_formulas"]),
        "banned_words": patch.get("banned_words", cur["banned_words"]),
        "default_style": str(patch.get("default_style", cur["default_style"])).strip() or "khazix",
        "default_theme": str(patch.get("default_theme", cur["default_theme"])).strip() or "moyu_green",
        "wechat_account_id": str(patch.get("wechat_account_id", cur["wechat_account_id"])).strip(),
        "footer_template": str(patch.get("footer_template", cur["footer_template"])).strip(),
        "sources_config": patch.get("sources_config", cur["sources_config"]),
    }
    now = time.time()
    with get_conn() as conn:
        conn.execute(
            """
            UPDATE accounts SET
                name = ?, niche = ?, audience = ?, cadence = ?,
                title_formulas_json = ?, banned_words_json = ?,
                default_style = ?, default_theme = ?, wechat_account_id = ?,
                footer_template = ?, sources_config_json = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                merged["name"],
                merged["niche"],
                merged["audience"],
                merged["cadence"],
                json.dumps(merged["title_formulas"], ensure_ascii=False),
                json.dumps(merged["banned_words"], ensure_ascii=False),
                merged["default_style"],
                merged["default_theme"],
                merged["wechat_account_id"],
                merged["footer_template"],
                json.dumps(merged["sources_config"], ensure_ascii=False),
                now,
                cur["id"],
            ),
        )
    return get_primary_account()


def _row_to_topic(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    return {
        "id": d["id"],
        "account_id": d["account_id"],
        "source_type": d["source_type"],
        "source_name": d["source_name"],
        "source_url": d["source_url"],
        "raw_title": d["raw_title"],
        "raw_summary": d["raw_summary"],
        "suggested_titles": _parse_json(d.get("suggested_titles_json"), []),
        "raw_signals": _parse_json(d.get("raw_signals_json"), []),
        "metrics_badge": d.get("metrics_badge") or "",
        "engagement_badge": d.get("engagement_badge") or "",
        "engagement": _parse_json(d.get("engagement_json"), {}),
        "angle": d["angle"],
        "reason": d["reason"],
        "category": d["category"],
        "score": int(d["score"] or 0),
        "status": d["status"],
        "project_id": d["project_id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
    }


def list_topics(
    status: str = "",
    source_type: str = "",
    filter_mode: str = "",
    limit: int = 80,
) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    params: List[Any] = []
    if filter_mode == "today_new":
        clauses.append("status = 'new'")
        clauses.append("created_at >= ?")
        params.append(time.time() - 86400)
    elif filter_mode == "resonance":
        clauses.append("status != 'ignored'")
        clauses.append("(metrics_badge != '' OR reason LIKE '%多源共振%' OR length(raw_signals_json) > 80)")
    elif filter_mode in ("new", "drafted", "ignored"):
        clauses.append("status = ?")
        params.append(filter_mode)
    elif status:
        clauses.append("status = ?")
        params.append(status)
    if source_type:
        clauses.append("(source_type = ? OR raw_signals_json LIKE ? OR raw_signals_json LIKE ?)")
        params.extend([
            source_type,
            f'%"source_type": "{source_type}"%',
            f'%"source_type":"{source_type}"%',
        ])
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM topics {where} ORDER BY score DESC, created_at DESC LIMIT ?"
    params.append(max(1, min(limit, 300)))
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_topic(r) for r in rows]


def topic_funnel_counts() -> Dict[str, int]:
    cutoff = time.time() - 86400
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT status, created_at, metrics_badge, reason, raw_signals_json FROM topics"
        ).fetchall()
    counts = {"new": 0, "today_new": 0, "resonance": 0, "drafted": 0, "ignored": 0, "all": len(rows)}
    for r in rows:
        st = r["status"]
        if st in counts:
            counts[st] += 1
        if st == "new" and float(r["created_at"] or 0) >= cutoff:
            counts["today_new"] += 1
        if st != "ignored":
            sigs = _parse_json(r["raw_signals_json"], [])
            if (r["metrics_badge"] or "") or ("多源共振" in (r["reason"] or "")) or len(sigs) >= 2:
                counts["resonance"] += 1
    return counts


def topic_source_counts() -> Dict[str, int]:
    """统计选题池内各 source_type 有效条目数（含聚簇折叠信号，不含已忽略）。"""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT source_type, raw_signals_json FROM topics WHERE status != 'ignored'"
        ).fetchall()
    counts: Dict[str, int] = {}
    for r in rows:
        seen = set()
        st = str(r["source_type"] or "").strip()
        if st:
            seen.add(st)
        for s in _parse_json(r["raw_signals_json"], []):
            if isinstance(s, dict):
                sst = str(s.get("source_type") or "").strip()
                if sst:
                    seen.add(sst)
        for k in seen:
            counts[k] = counts.get(k, 0) + 1
    return counts


def get_topic(topic_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM topics WHERE id = ?", (topic_id,)).fetchone()
    return _row_to_topic(row) if row else None


def insert_topic(item: Dict[str, Any]) -> Dict[str, Any]:
    tid = str(item.get("id") or f"tp_{uuid.uuid4().hex[:10]}")
    now = time.time()
    titles = item.get("suggested_titles") or []
    if not isinstance(titles, list):
        titles = [str(titles)]
    signals = item.get("raw_signals") or []
    if not isinstance(signals, list):
        signals = []
    engagement = item.get("engagement") or {}
    if not isinstance(engagement, dict):
        engagement = {}
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO topics (
                id, account_id, source_type, source_name, source_url,
                raw_title, raw_summary, suggested_titles_json,
                raw_signals_json, metrics_badge, engagement_badge, engagement_json,
                angle, reason, category, score, status, project_id,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                tid,
                str(item.get("account_id") or DEFAULT_ACCOUNT_ID),
                str(item.get("source_type") or "manual"),
                str(item.get("source_name") or ""),
                str(item.get("source_url") or ""),
                str(item.get("raw_title") or "").strip(),
                str(item.get("raw_summary") or "").strip(),
                json.dumps(titles, ensure_ascii=False),
                json.dumps(signals, ensure_ascii=False),
                str(item.get("metrics_badge") or "").strip(),
                str(item.get("engagement_badge") or "").strip(),
                json.dumps(engagement, ensure_ascii=False),
                str(item.get("angle") or "").strip(),
                str(item.get("reason") or "").strip(),
                str(item.get("category") or "实操教程").strip(),
                int(item.get("score") or 60),
                str(item.get("status") or "new"),
                str(item.get("project_id") or ""),
                now,
                now,
            ),
        )
    return get_topic(tid) or {}


def update_topic(topic_id: str, **fields: Any) -> Optional[Dict[str, Any]]:
    allowed = {"status", "project_id", "score", "angle", "reason", "category", "raw_summary", "engagement_badge"}
    updates: List[str] = []
    params: List[Any] = []
    for k, v in fields.items():
        if k in allowed:
            updates.append(f"{k} = ?")
            params.append(v)
    if "suggested_titles" in fields:
        updates.append("suggested_titles_json = ?")
        params.append(json.dumps(fields["suggested_titles"], ensure_ascii=False))
    if "engagement" in fields:
        updates.append("engagement_json = ?")
        params.append(json.dumps(fields["engagement"] or {}, ensure_ascii=False))
    if not updates:
        return get_topic(topic_id)
    updates.append("updated_at = ?")
    params.append(time.time())
    params.append(topic_id)
    with get_conn() as conn:
        conn.execute(f"UPDATE topics SET {', '.join(updates)} WHERE id = ?", params)
    return get_topic(topic_id)


def recent_topic_keys(days: int = 30) -> tuple[set[str], List[str]]:
    cutoff = time.time() - days * 86400
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT source_url, raw_title FROM topics WHERE created_at >= ?",
            (cutoff,),
        ).fetchall()
        art_rows = conn.execute(
            "SELECT title FROM articles WHERE created_at >= ?",
            (cutoff,),
        ).fetchall()
    urls = {str(r["source_url"]).strip() for r in rows if r["source_url"]}
    titles = [str(r["raw_title"]).strip() for r in rows if r["raw_title"]]
    titles.extend(str(r["title"]).strip() for r in art_rows if r["title"])
    return urls, titles


def record_article(item: Dict[str, Any]) -> Dict[str, Any]:
    aid = str(item.get("id") or f"art_{uuid.uuid4().hex[:10]}")
    now = time.time()
    with get_conn() as conn:
        conn.execute(
            """
            INSERT INTO articles (
                id, account_id, topic_id, project_id, title,
                style, theme, word_count, draft_media_id, msgid,
                status, published_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                aid,
                str(item.get("account_id") or DEFAULT_ACCOUNT_ID),
                str(item.get("topic_id") or ""),
                str(item.get("project_id") or ""),
                str(item.get("title") or "无标题").strip(),
                str(item.get("style") or ""),
                str(item.get("theme") or ""),
                int(item.get("word_count") or 0),
                str(item.get("draft_media_id") or ""),
                str(item.get("msgid") or ""),
                str(item.get("status") or "draft"),
                str(item.get("published_at") or ""),
                now,
                now,
            ),
        )
        row = conn.execute("SELECT * FROM articles WHERE id = ?", (aid,)).fetchone()
    return dict(row) if row else {}


def list_articles(limit: int = 100) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM articles ORDER BY created_at DESC LIMIT ?",
            (max(1, min(limit, 300)),),
        ).fetchall()
    return [dict(r) for r in rows]


def upsert_metric(item: Dict[str, Any]) -> Dict[str, Any]:
    now = time.time()
    ref_date = str(item.get("ref_date") or "").strip()
    msgid = str(item.get("msgid") or "").strip()
    title = str(item.get("title") or "").strip()
    article_id = str(item.get("article_id") or "").strip()

    with get_conn() as conn:
        existing = None
        if msgid:
            existing = conn.execute(
                "SELECT * FROM metrics WHERE msgid = ? AND ref_date = ?",
                (msgid, ref_date),
            ).fetchone()
        if not existing and title and ref_date:
            existing = conn.execute(
                "SELECT * FROM metrics WHERE title = ? AND ref_date = ?",
                (title, ref_date),
            ).fetchone()
        if not article_id and title:
            art = conn.execute(
                "SELECT id FROM articles WHERE title = ? ORDER BY created_at DESC LIMIT 1",
                (title,),
            ).fetchone()
            if art:
                article_id = art["id"]

        if existing:
            mid = existing["id"]
            conn.execute(
                """
                UPDATE metrics SET
                    article_id = ?, title = ?, target_user = ?,
                    read_user = ?, read_count = ?, ori_read_user = ?,
                    share_count = ?, fav_count = ?, like_count = ?,
                    source = ?, notes = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    article_id or existing["article_id"],
                    title or existing["title"],
                    int(item.get("target_user") or 0),
                    int(item.get("read_user") or 0),
                    int(item.get("read_count") or 0),
                    int(item.get("ori_read_user") or 0),
                    int(item.get("share_count") or 0),
                    int(item.get("fav_count") or 0),
                    int(item.get("like_count") or 0),
                    str(item.get("source") or existing["source"]),
                    str(item.get("notes") if item.get("notes") is not None else existing["notes"]),
                    now,
                    mid,
                ),
            )
        else:
            mid = str(item.get("id") or f"met_{uuid.uuid4().hex[:10]}")
            conn.execute(
                """
                INSERT INTO metrics (
                    id, article_id, account_id, ref_date, msgid, title,
                    target_user, read_user, read_count, ori_read_user,
                    share_count, fav_count, like_count, source, notes,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    mid,
                    article_id,
                    str(item.get("account_id") or DEFAULT_ACCOUNT_ID),
                    ref_date,
                    msgid,
                    title,
                    int(item.get("target_user") or 0),
                    int(item.get("read_user") or 0),
                    int(item.get("read_count") or 0),
                    int(item.get("ori_read_user") or 0),
                    int(item.get("share_count") or 0),
                    int(item.get("fav_count") or 0),
                    int(item.get("like_count") or 0),
                    str(item.get("source") or "manual"),
                    str(item.get("notes") or ""),
                    now,
                    now,
                ),
            )
        row = conn.execute("SELECT * FROM metrics WHERE id = ?", (mid,)).fetchone()
    return dict(row) if row else {}


def list_metrics(limit: int = 100) -> List[Dict[str, Any]]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM metrics ORDER BY ref_date DESC, updated_at DESC LIMIT ?",
            (max(1, min(limit, 300)),),
        ).fetchall()
    return [dict(r) for r in rows]


def _row_to_intel(row: sqlite3.Row) -> Dict[str, Any]:
    d = dict(row)
    return {
        "id": d["id"],
        "cluster_key": d["cluster_key"],
        "title": d["title"],
        "summary": d["summary"],
        "raw_title": d["raw_title"],
        "source_type": d["source_type"],
        "source_name": d["source_name"],
        "source_url": d["source_url"],
        "signals": _parse_json(d.get("signals_json"), []),
        "credibility": d["credibility"],
        "metrics_badge": d["metrics_badge"],
        "engagement_badge": d.get("engagement_badge") or "",
        "engagement": _parse_json(d.get("engagement_json"), {}),
        "category": d["category"],
        "tags": _parse_json(d.get("tags_json"), []),
        "popularity": int(d["popularity"] or 0),
        "promoted_topic_id": d["promoted_topic_id"],
        "created_at": d["created_at"],
        "updated_at": d["updated_at"],
    }


def upsert_intel_items(items: List[Dict[str, Any]]) -> Dict[str, int]:
    now = time.time()
    added = 0
    updated = 0
    with get_conn() as conn:
        for it in items:
            ckey = str(it.get("cluster_key") or "").strip()
            title = str(it.get("title") or "").strip()
            if not ckey or not title:
                continue
            existing = conn.execute("SELECT * FROM intel_items WHERE cluster_key = ?", (ckey,)).fetchone()
            sigs = it.get("signals") or []
            tags = it.get("tags") or []
            eng_obj = it.get("engagement") if isinstance(it.get("engagement"), dict) else {}
            eng_badge = str(it.get("engagement_badge") or "").strip()
            if existing:
                old_sigs = _parse_json(existing["signals_json"], [])
                seen_urls = {(s.get("url") or "", s.get("title") or "") for s in old_sigs}
                merged_sigs = list(old_sigs)
                for s in sigs:
                    k = (s.get("url") or "", s.get("title") or "")
                    if k not in seen_urls:
                        seen_urls.add(k)
                        merged_sigs.append(s)
                old_eng = _parse_json(existing["engagement_json"] if "engagement_json" in existing.keys() else "{}", {})
                merged_eng = eng_obj if eng_obj else old_eng
                merged_eng_badge = eng_badge or str(existing["engagement_badge"] if "engagement_badge" in existing.keys() else "")
                conn.execute(
                    """
                    UPDATE intel_items SET
                        title = ?, summary = ?, signals_json = ?,
                        credibility = ?, metrics_badge = ?, engagement_badge = ?, engagement_json = ?,
                        category = ?, tags_json = ?, popularity = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        title,
                        str(it.get("summary") or existing["summary"]),
                        json.dumps(merged_sigs, ensure_ascii=False),
                        str(it.get("credibility") or existing["credibility"]),
                        str(it.get("metrics_badge") or existing["metrics_badge"]),
                        merged_eng_badge,
                        json.dumps(merged_eng, ensure_ascii=False),
                        str(it.get("category") or existing["category"]),
                        json.dumps(tags or _parse_json(existing["tags_json"], []), ensure_ascii=False),
                        max(int(it.get("popularity") or 0), int(existing["popularity"] or 0)),
                        now,
                        existing["id"],
                    ),
                )
                updated += 1
            else:
                iid = str(it.get("id") or f"in_{uuid.uuid4().hex[:10]}")
                conn.execute(
                    """
                    INSERT INTO intel_items (
                        id, cluster_key, title, summary, raw_title,
                        source_type, source_name, source_url, signals_json,
                        credibility, metrics_badge, engagement_badge, engagement_json,
                        category, tags_json, popularity, promoted_topic_id, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        iid,
                        ckey,
                        title,
                        str(it.get("summary") or ""),
                        str(it.get("raw_title") or title),
                        str(it.get("source_type") or ""),
                        str(it.get("source_name") or ""),
                        str(it.get("source_url") or ""),
                        json.dumps(sigs, ensure_ascii=False),
                        str(it.get("credibility") or "社区热议"),
                        str(it.get("metrics_badge") or ""),
                        eng_badge,
                        json.dumps(eng_obj, ensure_ascii=False),
                        str(it.get("category") or "AI快讯"),
                        json.dumps(tags, ensure_ascii=False),
                        int(it.get("popularity") or 0),
                        "",
                        now,
                        now,
                    ),
                )
                added += 1
    return {"added": added, "updated": updated}


def list_intel_items(
    credibility: str = "",
    source_type: str = "",
    q: str = "",
    limit: int = 80,
) -> List[Dict[str, Any]]:
    clauses: List[str] = []
    params: List[Any] = []
    if credibility and credibility != "all":
        clauses.append("credibility = ?")
        params.append(credibility)
    if source_type:
        clauses.append("(source_type = ? OR signals_json LIKE ? OR signals_json LIKE ?)")
        params.extend([
            source_type,
            f'%"source_type": "{source_type}"%',
            f'%"source_type":"{source_type}"%',
        ])
    if q.strip():
        like = f"%{q.strip()}%"
        clauses.append("(title LIKE ? OR summary LIKE ? OR raw_title LIKE ? OR tags_json LIKE ?)")
        params.extend([like, like, like, like])
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    sql = f"SELECT * FROM intel_items {where} ORDER BY updated_at DESC, popularity DESC LIMIT ?"
    params.append(max(1, min(limit, 200)))
    with get_conn() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [_row_to_intel(r) for r in rows]


def get_intel_item(intel_id: str) -> Optional[Dict[str, Any]]:
    with get_conn() as conn:
        row = conn.execute("SELECT * FROM intel_items WHERE id = ?", (intel_id,)).fetchone()
    return _row_to_intel(row) if row else None


def mark_intel_promoted(intel_id: str, topic_id: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "UPDATE intel_items SET promoted_topic_id = ?, updated_at = ? WHERE id = ?",
            (topic_id, time.time(), intel_id),
        )


def intel_counts() -> Dict[str, int]:
    with get_conn() as conn:
        rows = conn.execute("SELECT credibility FROM intel_items").fetchall()
    counts = {"all": len(rows), "一手官方": 0, "多源印证": 0, "社区热议": 0, "快讯转述": 0}
    for r in rows:
        c = str(r["credibility"] or "")
        if c in counts:
            counts[c] += 1
    return counts


def intel_source_counts() -> Dict[str, int]:
    with get_conn() as conn:
        rows = conn.execute("SELECT source_type, signals_json FROM intel_items").fetchall()
    counts: Dict[str, int] = {}
    for r in rows:
        seen = set()
        st = str(r["source_type"] or "").strip()
        if st:
            seen.add(st)
        try:
            sigs = json.loads(r["signals_json"] or "[]")
            if isinstance(sigs, list):
                for s in sigs:
                    if isinstance(s, dict):
                        sst = str(s.get("source_type") or "").strip()
                        if sst:
                            seen.add(sst)
        except Exception:
            pass
        for k in seen:
            counts[k] = counts.get(k, 0) + 1
    return counts
