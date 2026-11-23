# -*- coding: utf-8 -*-
"""轻量后台定时调度：每日自动抓取新选题 + 同步公众号数据。"""
from __future__ import annotations

import json
import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Dict

from . import db, topic_engine, wechat_mp
from .paths import data_dir

logger = logging.getLogger(__name__)

_STOP_EVENT = threading.Event()
_THREAD: threading.Thread | None = None


def _state_path():
    return data_dir() / "scheduler_state.json"


def _load_state() -> Dict[str, str]:
    p = _state_path()
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def _save_state(state: Dict[str, str]) -> None:
    try:
        _state_path().write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception:
        pass


def _is_due(now_dt: datetime, target_hhmm: str, last_day: str) -> bool:
    today = now_dt.strftime("%Y-%m-%d")
    if last_day == today:
        return False
    cur_hhmm = now_dt.strftime("%H:%M")
    return cur_hhmm >= (target_hhmm or "08:00")


def run_tick(now_dt: datetime | None = None) -> None:
    now_dt = now_dt or datetime.now()
    today = now_dt.strftime("%Y-%m-%d")
    acc = db.get_primary_account()
    cfg = acc.get("sources_config") or {}
    state = _load_state()
    changed = False

    if cfg.get("daily_fetch_enabled") and _is_due(now_dt, str(cfg.get("daily_fetch_time") or "08:00"), state.get("last_fetch_day", "")):
        try:
            topic_engine.refresh_topics(max_new=8)
            state["last_fetch_day"] = today
            changed = True
        except Exception as e:
            logger.warning("[scheduler] daily topic fetch failed: %s", e)

    if cfg.get("daily_metrics_sync_enabled") and _is_due(now_dt, str(cfg.get("daily_metrics_sync_time") or "09:30"), state.get("last_metrics_day", "")):
        if wechat_mp.is_configured():
            try:
                yday = (now_dt.date() - timedelta(days=1)).strftime("%Y-%m-%d")
                rows = wechat_mp.fetch_article_total(yday, yday)
                for row in rows:
                    db.upsert_metric({**row, "account_id": acc["id"], "source": "datacube"})
                state["last_metrics_day"] = today
                changed = True
            except Exception as e:
                logger.warning("[scheduler] daily metrics sync failed: %s", e)

    if changed:
        _save_state(state)


def _loop() -> None:
    while not _STOP_EVENT.is_set():
        try:
            run_tick()
        except Exception:
            pass
        _STOP_EVENT.wait(60.0)


def start_scheduler() -> None:
    global _THREAD
    if _THREAD and _THREAD.is_alive():
        return
    _STOP_EVENT.clear()
    _THREAD = threading.Thread(target=_loop, name="aicontent-scheduler", daemon=True)
    _THREAD.start()


def stop_scheduler() -> None:
    _STOP_EVENT.set()
