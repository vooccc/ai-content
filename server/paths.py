# -*- coding: utf-8 -*-
"""ai-content 独立数据路径与平滑兼容层。

数据目录解析优先级：
1. 环境变量 ``AICONTENT_DATA_DIR``
2. 项目根目录下 ``data/``（默认，独立运行零污染）

平滑迁移：当 ``data/`` 下尚无 ``studio/``、``content/config.json`` 或 ``wechat_mp.json``，
但本机存在历史柳如烟数据目录（``LIURUYAN_DATA_DIR`` / ``~/.liuruyan-dev`` / ``~/.liuruyan``）时，
首次访问会安全复制一份到 ``ai-content/data/``（只读拷贝，不删除原文件）。
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Optional


def project_root() -> Path:
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    env = (os.getenv("AICONTENT_DATA_DIR") or "").strip()
    p = Path(env).expanduser() if env else (project_root() / "data")
    p.mkdir(parents=True, exist_ok=True)
    return p


def liuruyan_data_dir() -> Optional[Path]:
    """定位本机柳如烟数据目录（可选，用于复用 models.json / search_config.json 及一次性迁移旧数据）。"""
    candidates = []
    env = (os.getenv("LIURUYAN_DATA_DIR") or "").strip()
    if env:
        candidates.append(Path(env).expanduser())
    home = Path.home()
    candidates.extend([
        home / ".liuruyan-dev",
        home / ".liuruyan",
        Path(r"D:\AI_Project\柳如烟"),
    ])
    for cand in candidates:
        if cand.is_dir() and (
            (cand / "models.json").exists()
            or (cand / "studio").is_dir()
            or (cand / "content").is_dir()
        ):
            return cand
    return None


def _copy_if_missing(src: Path, dst: Path) -> None:
    if dst.exists() or not src.exists():
        return
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dst)
    except Exception:
        pass


def studio_dir() -> Path:
    d = data_dir() / "studio"
    if not d.exists():
        d.mkdir(parents=True, exist_ok=True)
        lry = liuruyan_data_dir()
        if lry and (lry / "studio").is_dir():
            try:
                for item in (lry / "studio").iterdir():
                    target = d / item.name
                    if item.is_dir() and not target.exists():
                        shutil.copytree(item, target)
                    elif item.is_file() and not target.exists():
                        shutil.copy2(item, target)
            except Exception:
                pass
    return d


def content_config_path() -> Path:
    dst = data_dir() / "content" / "config.json"
    dst.parent.mkdir(parents=True, exist_ok=True)
    if not dst.exists():
        lry = liuruyan_data_dir()
        if lry:
            _copy_if_missing(lry / "content" / "config.json", dst)
    return dst


def wechat_mp_config_path() -> Path:
    dst = data_dir() / "wechat_mp.json"
    if not dst.exists():
        lry = liuruyan_data_dir()
        if lry:
            _copy_if_missing(lry / "wechat_mp.json", dst)
    return dst


def gateway_config_path() -> Path:
    return data_dir() / "gateway.json"


def settings_config_path() -> Path:
    return data_dir() / "settings.json"


def db_path() -> Path:
    return data_dir() / "aicontent.db"


def models_config_paths() -> list[tuple[Path, Optional[Path]]]:
    """返回候选 (models.json, models.secrets.json) 列表，优先 ai-content 自有配置，再回退柳如烟配置。"""
    out: list[tuple[Path, Optional[Path]]] = []
    local_models = data_dir() / "models.json"
    local_secrets = data_dir() / "models.secrets.json"
    if local_models.exists():
        out.append((local_models, local_secrets if local_secrets.exists() else None))
    lry = liuruyan_data_dir()
    if lry:
        lm = lry / "models.json"
        ls = lry / "models.secrets.json"
        if lm.exists():
            out.append((lm, ls if ls.exists() else None))
    return out


def find_tavily_api_key() -> str:
    env_key = (os.getenv("AICONTENT_TAVILY_KEY") or os.getenv("TAVILY_API_KEY") or "").strip()
    if env_key:
        return env_key
    sp = settings_config_path()
    if sp.exists():
        try:
            import json
            sc = json.loads(sp.read_text(encoding="utf-8-sig"))
            k = str(sc.get("tavily_api_key") or "").strip()
            if k:
                return k
        except Exception:
            pass
    for base in [data_dir(), liuruyan_data_dir()]:
        if not base:
            continue
        p = base / "search_config.json"
        if p.exists():
            try:
                import json
                cfg = json.loads(p.read_text(encoding="utf-8-sig"))
                k = str(cfg.get("tavily_api_key") or "").strip()
                if k:
                    return k
            except Exception:
                pass
    return ""
