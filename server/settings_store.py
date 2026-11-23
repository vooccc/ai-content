# -*- coding: utf-8 -*-
"""ai-content 模型与连接配置存储（data/settings.json，已 gitignore）。"""
from __future__ import annotations

import json
from typing import Any, Dict

from .paths import settings_config_path

DEFAULT_SETTINGS: Dict[str, Any] = {
    "mode": "auto",  # auto | gateway | custom
    "gateway_url": "http://127.0.0.1:8000/gateway/v1",
    "gateway_token": "",
    "llm_base_url": "",
    "llm_api_key": "",
    "default_text_model": "",
    "fast_text_model": "",
    "image_base_url": "",
    "image_api_key": "",
    "default_image_model": "",
    "tavily_api_key": "",
}

_SECRET_FIELDS = ("gateway_token", "llm_api_key", "image_api_key", "tavily_api_key")


def mask_secret(val: str) -> str:
    s = (val or "").strip()
    if not s:
        return ""
    if len(s) <= 8:
        return "*" * len(s)
    return f"{s[:4]}****{s[-4:]}"


def load_settings() -> Dict[str, Any]:
    out = dict(DEFAULT_SETTINGS)
    p = settings_config_path()
    if p.exists():
        try:
            raw = json.loads(p.read_text(encoding="utf-8-sig"))
            if isinstance(raw, dict):
                for k in DEFAULT_SETTINGS:
                    if k in raw and raw[k] is not None:
                        out[k] = str(raw[k]).strip() if isinstance(DEFAULT_SETTINGS[k], str) else raw[k]
        except Exception:
            pass
    if out.get("mode") not in ("auto", "gateway", "custom"):
        out["mode"] = "auto"
    return out


def get_masked_settings() -> Dict[str, Any]:
    raw = load_settings()
    res: Dict[str, Any] = {
        "mode": raw["mode"],
        "gateway_url": raw["gateway_url"],
        "llm_base_url": raw["llm_base_url"],
        "default_text_model": raw["default_text_model"],
        "fast_text_model": raw["fast_text_model"],
        "image_base_url": raw["image_base_url"],
        "default_image_model": raw["default_image_model"],
    }
    for f in _SECRET_FIELDS:
        val = str(raw.get(f) or "")
        res[f"has_{f}"] = bool(val)
        res[f"{f}_masked"] = mask_secret(val)
    return res


def update_settings(patch: Dict[str, Any]) -> Dict[str, Any]:
    cur = load_settings()
    for k in (
        "mode",
        "gateway_url",
        "llm_base_url",
        "default_text_model",
        "fast_text_model",
        "image_base_url",
        "default_image_model",
    ):
        if k in patch and patch[k] is not None:
            cur[k] = str(patch[k]).strip()
    if cur.get("mode") not in ("auto", "gateway", "custom"):
        cur["mode"] = "auto"
    for f in _SECRET_FIELDS:
        if patch.get(f"clear_{f}"):
            cur[f] = ""
            continue
        if f in patch and patch[f] is not None:
            v = str(patch[f]).strip()
            if v and "****" not in v:
                cur[f] = v
    p = settings_config_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(cur, ensure_ascii=False, indent=2), encoding="utf-8")
    return get_masked_settings()
