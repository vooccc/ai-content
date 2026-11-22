# -*- coding: utf-8 -*-
"""ai-content 模型目录与 Gateway 桥接（零依赖柳如烟 backend）。

解析优先级：
1. Gateway 模式（配置了 ``AICONTENT_GATEWAY_URL`` + ``AICONTENT_GATEWAY_TOKEN`` 或 ``data/gateway.json``）：
   - 通过标准 OpenAI ``/v1/models`` 获取可用模型；
   - 所有模型请求统一路由到 Gateway（复用柳如烟的多模型路由、Fallback 与用量统计）。
2. 本地 ``models.json`` 模式（优先 ``ai-content/data/models.json``，其次兼容只读柳如烟 ``models.json``）：
   - 过滤 ``enabled=True`` 且 ``transport == "openai_chat"`` 的模型直连厂商；
   - 列出带 ``image_gen`` 标签的模型供生图选用。
3. 环境变量兜底（``LLM_BASE_URL`` / ``LLM_API_KEY`` / ``LLM_MODEL``）。
"""
from __future__ import annotations

import json
import os
from typing import Any, Dict, List, Optional, Tuple

import httpx

from .paths import gateway_config_path, models_config_paths


def _load_gateway_cfg() -> Optional[Dict[str, str]]:
    url = (os.getenv("AICONTENT_GATEWAY_URL") or "").strip().rstrip("/")
    token = (os.getenv("AICONTENT_GATEWAY_TOKEN") or "").strip()
    default_model = (os.getenv("AICONTENT_GATEWAY_MODEL") or os.getenv("LLM_MODEL") or "").strip()
    if url and token:
        return {"base_url": url, "api_key": token, "default_model": default_model}
    p = gateway_config_path()
    if p.exists():
        try:
            data = json.loads(p.read_text(encoding="utf-8-sig"))
            if data.get("enabled", True) and data.get("base_url"):
                return {
                    "base_url": str(data["base_url"]).strip().rstrip("/"),
                    "api_key": str(data.get("api_key") or data.get("token") or "").strip(),
                    "default_model": str(data.get("default_model") or default_model).strip(),
                }
        except Exception:
            pass
    return None


def _load_providers_raw() -> Tuple[Dict[str, Dict[str, Any]], str]:
    """加载第一个可用的 (providers_dict, current_model)。"""
    for models_path, secrets_path in models_config_paths():
        try:
            cfg = json.loads(models_path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        secrets: Dict[str, str] = {}
        if secrets_path and secrets_path.exists():
            try:
                secrets = json.loads(secrets_path.read_text(encoding="utf-8-sig"))
            except Exception:
                secrets = {}
        providers: Dict[str, Dict[str, Any]] = {}
        for pid, pdata in (cfg.get("providers") or {}).items():
            if not isinstance(pdata, dict):
                continue
            item = dict(pdata)
            sk = f"provider:{pid}"
            if sk in secrets and not item.get("api_key"):
                item["api_key"] = secrets[sk]
            providers[pid] = item
        return providers, str(cfg.get("current_model") or "").strip()
    return {}, ""


def _gateway_models(gw: Dict[str, str]) -> List[Dict[str, str]]:
    headers = {}
    if gw.get("api_key"):
        headers["Authorization"] = f"Bearer {gw['api_key']}"
    try:
        r = httpx.get(f"{gw['base_url']}/models", headers=headers, timeout=5)
        if r.status_code != 200:
            return []
        rows = r.json().get("data") or []
        out: List[Dict[str, str]] = []
        for row in rows:
            mid = str(row.get("id") or "").strip()
            if not mid:
                continue
            out.append({
                "model": mid,
                "name": str(row.get("name") or mid),
                "provider": "gateway",
                "provider_name": "Gateway",
            })
        return out
    except Exception:
        return []


def current_model() -> str:
    gw = _load_gateway_cfg()
    if gw and gw.get("default_model"):
        return gw["default_model"]
    _, cur = _load_providers_raw()
    if cur:
        return cur
    return (os.getenv("LLM_MODEL") or "").strip()


def list_text_models() -> List[Dict[str, str]]:
    gw = _load_gateway_cfg()
    if gw:
        ms = _gateway_models(gw)
        if ms:
            return ms
    providers, _ = _load_providers_raw()
    out: List[Dict[str, str]] = []
    for pid, pdata in providers.items():
        if not pdata.get("enabled", True):
            continue
        if (pdata.get("transport") or "openai_chat") != "openai_chat":
            continue
        if not (pdata.get("base_url") or "").strip():
            continue
        pname = str(pdata.get("name") or pid)
        for m in pdata.get("models") or []:
            mid = m.get("id") if isinstance(m, dict) else str(m)
            mname = (m.get("name") if isinstance(m, dict) else "") or mid
            tags = (m.get("tags") if isinstance(m, dict) else []) or []
            if not mid or "image_gen" in tags:
                continue
            out.append({
                "model": mid,
                "name": mname,
                "provider": pid,
                "provider_name": pname,
            })
    if not out and (os.getenv("LLM_BASE_URL") or "").strip():
        mid = (os.getenv("LLM_MODEL") or "deepseek-chat").strip()
        out.append({"model": mid, "name": mid, "provider": "env", "provider_name": "环境变量"})
    return out


def list_image_models() -> List[Dict[str, str]]:
    providers, _ = _load_providers_raw()
    out: List[Dict[str, str]] = []
    for pid, pdata in providers.items():
        if not pdata.get("enabled", True):
            continue
        pname = str(pdata.get("name") or pid)
        for m in pdata.get("models") or []:
            mid = m.get("id") if isinstance(m, dict) else str(m)
            tags = (m.get("tags") if isinstance(m, dict) else []) or []
            if mid and "image_gen" in tags:
                out.append({"model": mid, "provider": pid, "provider_name": pname})
    return out


def build_model_catalog(selected_model: str = "") -> Dict[str, Any]:
    gw = _load_gateway_cfg()
    if gw:
        models: Dict[str, Any] = {}
        for item in _gateway_models(gw):
            models[item["model"]] = {
                "base_url": gw["base_url"],
                "api_key": gw.get("api_key", ""),
                "transport": "openai_chat",
                "provider": "gateway",
            }
        default = (selected_model or "").strip() or gw.get("default_model") or ""
        if default and default not in models:
            models[default] = {
                "base_url": gw["base_url"],
                "api_key": gw.get("api_key", ""),
                "transport": "openai_chat",
                "provider": "gateway",
            }
        if not default and models:
            default = next(iter(models))
        return {"default": default, "models": models}

    providers, cur = _load_providers_raw()
    models = {}
    for pid, pdata in providers.items():
        if not pdata.get("enabled", True):
            continue
        if (pdata.get("transport") or "openai_chat") != "openai_chat":
            continue
        base_url = (pdata.get("base_url") or "").strip()
        if not base_url:
            continue
        api_key = (pdata.get("api_key") or "").strip()
        for m in pdata.get("models") or []:
            mid = m.get("id") if isinstance(m, dict) else str(m)
            tags = (m.get("tags") if isinstance(m, dict) else []) or []
            if not mid or "image_gen" in tags:
                continue
            models[mid] = {
                "base_url": base_url,
                "api_key": api_key,
                "transport": "openai_chat",
                "provider": pid,
            }
    default = (selected_model or "").strip() or cur or (os.getenv("LLM_MODEL") or "").strip()
    if default not in models and models:
        default = next(iter(models))
    return {"default": default, "models": models}
