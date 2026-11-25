# -*- coding: utf-8 -*-
"""模型目录解析：把宿主（柳如烟）注入的「模型目录」解析成可直连的 LLMClient。

来源优先级：
1. 环境变量 ``LLM_CATALOG_FILE`` 指向的 JSON —— 宿主 spawn 时写好，含所有可用模型
   的 base_url+api_key 映射 + 一个 default（= 本篇项目选的模型，或宿主当前模型）。
2. 环境变量 ``LLM_BASE_URL`` / ``LLM_API_KEY`` / ``LLM_MODEL`` —— 单模型直连。
3. ``ai/llm_client.py`` 内置默认 —— 脱离宿主单跑时的兜底。

模型目录 JSON 格式（宿主注入）::

    {
      "default": "deepseek-chat",
      "models": {
        "deepseek-chat":   {"base_url": "https://api.deepseek.com", "api_key": "sk-...", "transport": "openai_chat"},
        "kimi-k2":         {"base_url": "...", "api_key": "...", "transport": "openai_chat"}
      }
    }

**多级 model 选择**（节点级 > 项目级 > 全局）在调用方 studio_json 完成：
- 节点级：``node.params["model"]``（YAML 里某步指定，二期用）。
- 项目级 / 全局：本模块的 default（宿主注入时已按"项目选的或当前模型"填好）。
本模块只负责"给一个 model 名 → 返回能直连它的 LLMClient"。
"""
from __future__ import annotations

import os
import json
from typing import Optional

from ai.llm_client import LLMClient

_catalog_cache: Optional[dict] = None


def _load_catalog() -> dict:
    global _catalog_cache
    if _catalog_cache is not None:
        return _catalog_cache
    path = os.environ.get("LLM_CATALOG_FILE")
    if path and os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                _catalog_cache = {
                    "default": data.get("default", "") or "",
                    "models": data.get("models", {}) or {},
                }
                return _catalog_cache
        except Exception:
            pass
    _catalog_cache = {"default": os.environ.get("LLM_MODEL", ""), "models": {}}
    return _catalog_cache


def default_model() -> str:
    return _load_catalog().get("default", "") or os.environ.get("LLM_MODEL", "")


def resolve_client(model: str = "") -> LLMClient:
    """按 model 名拿 base_url+api_key 造 LLMClient（直连厂商）。

    model 为空 → 用目录 default。目录里命中该 model → 用其 base_url/key 直连；
    命中不到 → 回退环境变量（LLM_BASE_URL/KEY/MODEL）或 llm_client 内置默认，
    保证脱离宿主单独跑也不崩。
    """
    cat = _load_catalog()
    name = (model or "").strip() or cat.get("default", "") or os.environ.get("LLM_MODEL", "")
    entry = (cat.get("models") or {}).get(name)
    if isinstance(entry, dict) and entry.get("base_url"):
        return LLMClient(
            base_url=entry.get("base_url"),
            api_key=entry.get("api_key", ""),
            model=name,
            transport=entry.get("transport", "openai_chat") or "openai_chat",
        )
    return LLMClient(model=name) if name else LLMClient()
