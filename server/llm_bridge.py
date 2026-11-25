# -*- coding: utf-8 -*-
"""ai-content 模型目录与 Gateway 桥接（零依赖柳如烟 backend）。

解析优先级：
1. data/settings.json 显式配置（mode == 'gateway' 或 'custom'，或 'auto' 下填了 custom/gateway）
2. 环境变量（AICONTENT_GATEWAY_URL / AICONTENT_GATEWAY_TOKEN / LLM_BASE_URL / LLM_API_KEY）
3. 兼容只读本地 models.json（优先 ai-content/data/models.json，其次柳如烟 models.json）
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Any, Dict, List, Optional, Tuple

import httpx

from . import settings_store
from .paths import gateway_config_path, liuruyan_data_dir, models_config_paths


def _load_gateway_cfg() -> Optional[Dict[str, str]]:
    st = settings_store.load_settings()
    mode = st.get("mode", "auto")
    if mode == "custom":
        return None
    if mode == "gateway" and st.get("gateway_url"):
        return {
            "base_url": str(st["gateway_url"]).strip().rstrip("/"),
            "api_key": str(st.get("gateway_token") or "").strip(),
            "default_model": str(st.get("default_text_model") or "").strip(),
        }

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
    if mode == "auto" and st.get("gateway_url") and st.get("gateway_token"):
        return {
            "base_url": str(st["gateway_url"]).strip().rstrip("/"),
            "api_key": str(st["gateway_token"]).strip(),
            "default_model": str(st.get("default_text_model") or "").strip(),
        }
    return None


def _load_custom_cfg() -> Optional[Dict[str, str]]:
    st = settings_store.load_settings()
    mode = st.get("mode", "auto")
    if mode == "gateway":
        return None
    if st.get("llm_base_url") and st.get("llm_api_key"):
        return {
            "base_url": str(st["llm_base_url"]).strip().rstrip("/"),
            "api_key": str(st["llm_api_key"]).strip(),
            "default_model": str(st.get("default_text_model") or "").strip(),
            "fast_model": str(st.get("fast_text_model") or "").strip(),
        }
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


_PRO_TRANSPORTS = {"google-antigravity", "compute_account"}
_PRO_GW_CACHE: Dict[str, Any] = {"ts": 0.0, "base_url": "", "api_key": "", "items": []}


def _read_liuruyan_gateway_creds() -> Tuple[bool, str, str]:
    """只读读取本地柳如烟 Gateway 是否启用及可用令牌（不修改柳如烟数据）。"""
    st = settings_store.load_settings()
    custom_url = str(st.get("gateway_url") or "").strip().rstrip("/")
    custom_tok = str(st.get("gateway_token") or "").strip()
    lry = liuruyan_data_dir()
    enabled = True
    lry_tok = ""
    if lry:
        gw_cfg = lry / "gateway_config.json"
        if gw_cfg.exists():
            try:
                enabled = bool(json.loads(gw_cfg.read_text(encoding="utf-8-sig")).get("enabled", False))
            except Exception:
                enabled = False
        tok_file = lry / "gateway_tokens.json"
        if tok_file.exists():
            try:
                raw = json.loads(tok_file.read_text(encoding="utf-8-sig"))
                for t in (raw.get("tokens") or []):
                    if isinstance(t, dict) and not t.get("disabled") and (t.get("token") or "").strip():
                        lry_tok = str(t["token"]).strip()
                        break
            except Exception:
                pass
    token = custom_tok or lry_tok
    if not custom_tok and lry_tok:
        # 若 settings.json 里残留旧端口 (如 8000) 且未配 token，优先自动探测 8002/8000
        return enabled, custom_url, token
    return enabled, custom_url, token


def _discover_liuruyan_pro_models(force: bool = False) -> Tuple[str, str, List[Dict[str, str]]]:
    """探测本地柳如烟 Gateway 暴露的算力池模型（如 google-antigravity），20 秒缓存。"""
    if os.getenv("AICONTENT_DATA_DIR") and not os.getenv("AICONTENT_PRO_GATEWAY_PROBE"):
        return "", "", []
    now = time.time()
    if not force and (now - float(_PRO_GW_CACHE.get("ts") or 0.0)) < 20.0:
        return (
            str(_PRO_GW_CACHE.get("base_url") or ""),
            str(_PRO_GW_CACHE.get("api_key") or ""),
            list(_PRO_GW_CACHE.get("items") or []),
        )
    enabled, cfg_url, token = _read_liuruyan_gateway_creds()
    if not enabled or not token:
        _PRO_GW_CACHE.update({"ts": now, "base_url": "", "api_key": "", "items": []})
        return "", "", []

    candidates: List[str] = []
    for u in ("http://127.0.0.1:8002/gateway/v1", "http://127.0.0.1:8000/gateway/v1", cfg_url):
        clean = (u or "").strip().rstrip("/")
        if clean and clean not in candidates:
            candidates.append(clean)

    headers = {"Authorization": f"Bearer {token}"}
    for base in candidates:
        try:
            r = httpx.get(f"{base}/models", headers=headers, timeout=0.8)
            if r.status_code != 200:
                continue
            rows = r.json().get("data") or []
            items: List[Dict[str, str]] = []
            for row in rows:
                if not isinstance(row, dict):
                    continue
                tr = str(row.get("transport") or "").strip().lower()
                pid = str(row.get("provider") or "").strip().lower()
                if tr not in _PRO_TRANSPORTS and pid not in _PRO_TRANSPORTS:
                    continue
                mid = str(row.get("id") or "").strip()
                if not mid:
                    continue
                items.append({
                    "model": mid,
                    "name": str(row.get("name") or mid.split(":", 1)[-1]),
                    "provider": str(row.get("provider") or "google-antigravity"),
                    "provider_name": f"{row.get('provider_name') or 'Google Antigravity'} (柳如烟)",
                })
            _PRO_GW_CACHE.update({"ts": now, "base_url": base, "api_key": token, "items": items})
            return base, token, items
        except Exception:
            continue

    _PRO_GW_CACHE.update({"ts": now, "base_url": "", "api_key": "", "items": []})
    return "", "", []


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


def active_source() -> str:
    st = settings_store.load_settings()
    mode = st.get("mode", "auto")
    if mode == "gateway" and st.get("gateway_url"):
        return "gateway"
    if mode == "custom" or (mode == "auto" and _load_custom_cfg()):
        return "custom"
    if _load_gateway_cfg():
        return "gateway"
    providers, _ = _load_providers_raw()
    if providers:
        return "liuruyan_models"
    if (os.getenv("LLM_BASE_URL") or "").strip():
        return "env"
    return "unconfigured"


_FAST_MODEL_PRIORITY = (
    "deepseek-flash",
    "deepseek-v4-flash",
    "deepseek/deepseek-v4-flash-free",
    "deepseek-v4.1-flash",
    "qwen3.8-max",
    "gpt-5.6-sol",
    "grok-4.5",
    "glm-5.3-flash",
)


def current_model() -> str:
    cat = build_model_catalog()
    if cat.get("default"):
        return str(cat["default"])
    st = settings_store.load_settings()
    if st.get("default_text_model"):
        return str(st["default_text_model"]).strip()
    return (os.getenv("LLM_MODEL") or "").strip()


def current_fast_model() -> str:
    """解析当前实际生效的翻译/快讯/筛选快模型名称。"""
    st = settings_store.load_settings()
    user_fast = str(st.get("fast_text_model") or "").strip()
    if user_fast:
        return user_fast
    cat = build_model_catalog()
    models_map = cat.get("models") or {}
    if st.get("mode") != "custom":
        for fid in _FAST_MODEL_PRIORITY:
            if fid in models_map and models_map[fid].get("api_key"):
                return fid
    return current_model()


_SUPPORTED_TRANSPORTS = ("openai_chat", "anthropic_messages")
_NON_TEXT_TAGS = {"image_gen", "embedding", "audio", "tts", "asr", "rerank", "video"}


def _is_text_model(m: Any) -> Tuple[str, str, bool]:
    mid = (m.get("id") if isinstance(m, dict) else str(m)).strip()
    mname = ((m.get("name") if isinstance(m, dict) else "") or mid).strip()
    tags = {str(t).lower() for t in ((m.get("tags") if isinstance(m, dict) else []) or [])}
    ok = bool(mid) and not (tags & _NON_TEXT_TAGS)
    return mid, mname, ok


def _normalize_anthropic_messages_url(base_url: str) -> str:
    raw = (base_url or "").strip()
    if not raw:
        return ""
    if raw.endswith("#"):
        lit = raw[:-1].rstrip("/")
        return lit if lit.endswith("/messages") else f"{lit}/messages"
    clean = raw.rstrip("/")
    if clean.endswith("/messages"):
        return clean
    clean = re.sub(r"/v\d+(?:alpha|beta)?$", "", clean, flags=re.I)
    return f"{clean}/v1/messages"


def _iter_provider_text_models(providers: Dict[str, Dict[str, Any]]) -> List[Dict[str, Any]]:
    """按有 api_key 优先遍历所有已启用且协议受支持的文本模型，避免无 key 渠道抢占同名模型。"""
    entries: List[Dict[str, Any]] = []
    for pid, pdata in providers.items():
        if not pdata.get("enabled", True):
            continue
        tr = (pdata.get("transport") or "openai_chat").strip()
        if tr not in _SUPPORTED_TRANSPORTS:
            continue
        base_url = (pdata.get("base_url") or "").strip()
        if not base_url:
            continue
        api_key = (pdata.get("api_key") or "").strip()
        pname = str(pdata.get("name") or pid)
        for m in pdata.get("models") or []:
            mid, mname, ok = _is_text_model(m)
            if not ok:
                continue
            entries.append({
                "model": mid,
                "name": mname,
                "provider": pid,
                "provider_name": pname,
                "transport": tr,
                "base_url": base_url,
                "api_key": api_key,
            })
    entries.sort(key=lambda e: (0 if e["api_key"] else 1))
    return entries


def list_text_models() -> List[Dict[str, str]]:
    st = settings_store.load_settings()
    custom = _load_custom_cfg()
    if st.get("mode") == "custom" and custom:
        out: List[Dict[str, str]] = []
        seen: set[str] = set()
        for mid in (custom.get("default_model"), custom.get("fast_model")):
            m = (mid or "").strip()
            if m and m not in seen:
                seen.add(m)
                out.append({"model": m, "name": m, "provider": "custom", "provider_name": "自定义 API"})
        return out

    gw = _load_gateway_cfg()
    if gw:
        ms = _gateway_models(gw)
        if ms:
            return ms

    providers, _ = _load_providers_raw()
    out = []
    seen = set()
    if custom:
        for mid in (custom.get("default_model"), custom.get("fast_model")):
            m = (mid or "").strip()
            if m and m not in seen:
                seen.add(m)
                out.append({"model": m, "name": m, "provider": "custom", "provider_name": "自定义 API"})

    for e in _iter_provider_text_models(providers):
        mid = e["model"]
        if mid in seen:
            continue
        seen.add(mid)
        out.append({
            "model": mid,
            "name": e["name"],
            "provider": e["provider"],
            "provider_name": e["provider_name"],
        })

    _pro_url, _pro_key, pro_items = _discover_liuruyan_pro_models()
    for pitem in pro_items:
        mid = pitem["model"]
        if mid in seen:
            continue
        seen.add(mid)
        out.append(pitem)

    if not out and (os.getenv("LLM_BASE_URL") or "").strip():
        mid = (os.getenv("LLM_MODEL") or "deepseek-chat").strip()
        out.append({"model": mid, "name": mid, "provider": "env", "provider_name": "环境变量"})
    return out


def list_image_models() -> List[Dict[str, str]]:
    st = settings_store.load_settings()
    out: List[Dict[str, str]] = []
    seen: set[str] = set()
    custom_img = str(st.get("default_image_model") or "").strip()
    if custom_img and (st.get("image_base_url") or (st.get("mode") == "custom" and st.get("llm_base_url"))):
        seen.add(custom_img)
        out.append({"model": custom_img, "provider": "custom_image", "provider_name": "自定义生图"})
    providers, _ = _load_providers_raw()
    for pid, pdata in providers.items():
        if not pdata.get("enabled", True):
            continue
        pname = str(pdata.get("name") or pid)
        for m in pdata.get("models") or []:
            mid = m.get("id") if isinstance(m, dict) else str(m)
            tags = (m.get("tags") if isinstance(m, dict) else []) or []
            if mid and "image_gen" in tags and mid not in seen:
                seen.add(mid)
                out.append({"model": mid, "provider": pid, "provider_name": pname})
    return out


def build_model_catalog(selected_model: str = "") -> Dict[str, Any]:
    st = settings_store.load_settings()
    custom = _load_custom_cfg()
    if st.get("mode") == "custom" and custom:
        models: Dict[str, Any] = {}
        for mid in (selected_model, custom.get("default_model"), custom.get("fast_model")):
            m = (mid or "").strip()
            if m:
                models[m] = {
                    "base_url": custom["base_url"],
                    "api_key": custom["api_key"],
                    "transport": "openai_chat",
                    "provider": "custom",
                }
        default = (selected_model or "").strip() or custom.get("default_model") or custom.get("fast_model") or ""
        return {"default": default, "models": models}

    gw = _load_gateway_cfg()
    if gw:
        models = {}
        for item in _gateway_models(gw):
            models[item["model"]] = {
                "base_url": gw["base_url"],
                "api_key": gw.get("api_key", ""),
                "transport": "openai_chat",
                "provider": "gateway",
            }
        default = (selected_model or "").strip() or st.get("default_text_model") or gw.get("default_model") or ""
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
    if custom:
        for mid in (custom.get("default_model"), custom.get("fast_model")):
            m = (mid or "").strip()
            if m:
                models[m] = {
                    "base_url": custom["base_url"],
                    "api_key": custom["api_key"],
                    "transport": "openai_chat",
                    "provider": "custom",
                }

    for e in _iter_provider_text_models(providers):
        mid = e["model"]
        if mid in models:
            continue
        models[mid] = {
            "base_url": e["base_url"],
            "api_key": e["api_key"],
            "transport": e["transport"],
            "provider": e["provider"],
        }
    direct_default = (
        str(st.get("default_text_model") or "").strip()
        or (cur if cur in models else "")
        or (os.getenv("LLM_MODEL") or "").strip()
    )
    if direct_default not in models and models:
        direct_default = next(iter(models))

    pro_url, pro_key, pro_items = _discover_liuruyan_pro_models()
    if pro_url and pro_items:
        for pitem in pro_items:
            mid = pitem["model"]
            if mid in models:
                continue
            models[mid] = {
                "base_url": pro_url,
                "api_key": pro_key,
                "transport": "openai_chat",
                "provider": pitem["provider"],
            }

    sel = (selected_model or "").strip()
    default = sel if sel in models else direct_default
    if default not in models and models:
        default = next(iter(models))
    return {"default": default, "models": models}


def _single_anthropic_request(
    base_url: str,
    api_key: str,
    target_model: str,
    messages: List[Dict[str, str]],
    temperature: float,
    max_tokens: int,
    timeout: int,
) -> str:
    url = _normalize_anthropic_messages_url(base_url)
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    if api_key:
        headers["x-api-key"] = api_key
    sys_parts: List[str] = []
    anth_msgs: List[Dict[str, str]] = []
    for m in messages:
        role = str(m.get("role") or "user").strip().lower()
        content = str(m.get("content") or "")
        if not content:
            continue
        if role == "system":
            sys_parts.append(content)
            continue
        r_norm = "assistant" if role == "assistant" else "user"
        if anth_msgs and anth_msgs[-1]["role"] == r_norm:
            anth_msgs[-1]["content"] += "\n\n" + content
        else:
            anth_msgs.append({"role": r_norm, "content": content})
    if not anth_msgs:
        anth_msgs = [{"role": "user", "content": "\n".join(sys_parts) or "Hello"}]
        sys_parts = []
    elif anth_msgs[0]["role"] != "user":
        anth_msgs.insert(0, {"role": "user", "content": "请继续。"})
    payload: Dict[str, Any] = {
        "model": target_model,
        "messages": anth_msgs,
        "max_tokens": max(256, int(max_tokens or 2400)),
        "temperature": temperature,
    }
    if sys_parts:
        payload["system"] = "\n\n".join(sys_parts)
    r = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    blocks = data.get("content") or []
    texts: List[str] = []
    for b in blocks:
        if isinstance(b, dict) and b.get("type") == "text" and b.get("text"):
            texts.append(str(b["text"]))
    return "\n".join(texts).strip()


def _single_chat_request(
    base_url: str,
    api_key: str,
    target_model: str,
    messages: List[Dict[str, str]],
    temperature: float,
    max_tokens: int,
    timeout: int,
    transport: str = "openai_chat",
) -> str:
    if transport == "anthropic_messages":
        return _single_anthropic_request(
            base_url, api_key, target_model, messages, temperature, max_tokens, timeout
        )
    url = base_url if base_url.endswith("/chat/completions") else f"{base_url}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": target_model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    r = httpx.post(url, headers=headers, json=payload, timeout=timeout)
    r.raise_for_status()
    data = r.json()
    choices = data.get("choices") or []
    if not choices:
        return ""
    msg = choices[0].get("message") or {}
    return str(msg.get("content") or "").strip()


def chat_completion_with_meta(
    messages: List[Dict[str, str]],
    model: str = "",
    temperature: float = 0.4,
    max_tokens: int = 2400,
    timeout: int = 60,
    prefer_fast: bool = False,
) -> Tuple[str, str]:
    """发起同步对话请求并返回 (reply_text, actual_model_used)。"""
    st = settings_store.load_settings()
    cat = build_model_catalog(model)
    models_map = cat.get("models") or {}
    target_model = (model or cat.get("default") or "").strip()

    candidates: List[Tuple[str, Dict[str, Any]]] = []
    seen_ids: set[str] = set()

    def _add_cand(mid: str, cfg: Dict[str, Any]) -> None:
        if mid and mid not in seen_ids and cfg.get("base_url"):
            seen_ids.add(mid)
            candidates.append((mid, cfg))

    if prefer_fast and not model:
        user_fast = str(st.get("fast_text_model") or "").strip()
        if user_fast and user_fast in models_map:
            _add_cand(user_fast, models_map[user_fast])

    fast_ids = _FAST_MODEL_PRIORITY
    if prefer_fast and not model and st.get("mode") != "custom":
        for fid in fast_ids:
            if fid in models_map and models_map[fid].get("api_key"):
                _add_cand(fid, models_map[fid])
                if len(candidates) >= 2:
                    break

    if target_model and target_model in models_map:
        _add_cand(target_model, models_map[target_model])
    elif not models_map:
        env_url = (os.getenv("LLM_BASE_URL") or "").strip().rstrip("/")
        env_key = (os.getenv("LLM_API_KEY") or "").strip()
        if env_url:
            _add_cand(target_model or (os.getenv("LLM_MODEL") or "deepseek-chat").strip(), {"base_url": env_url, "api_key": env_key})

    if not model and st.get("mode") != "custom":
        for fid in fast_ids:
            if fid in models_map and models_map[fid].get("api_key"):
                _add_cand(fid, models_map[fid])
                if len(candidates) >= 4:
                    break

    if not candidates:
        raise RuntimeError("未配置可用的文本模型或 Gateway")

    last_err: Optional[Exception] = None
    for mid, cfg in candidates[:4]:
        base_url = str(cfg.get("base_url") or "").rstrip("/")
        if not base_url:
            continue
        try:
            text = _single_chat_request(
                base_url,
                str(cfg.get("api_key") or ""),
                mid,
                messages,
                temperature,
                max_tokens,
                timeout,
                transport=str(cfg.get("transport") or "openai_chat"),
            )
            if text:
                return text, mid
        except Exception as e:
            last_err = e
            continue
    if last_err:
        raise last_err
    return "", candidates[0][0]


def chat_completion(
    messages: List[Dict[str, str]],
    model: str = "",
    temperature: float = 0.4,
    max_tokens: int = 2400,
    timeout: int = 60,
    prefer_fast: bool = False,
) -> str:
    """使用当前解析到的模型目录发起一次同步 OpenAI 兼容对话请求（支持快模型优先与兜底）。"""
    text, _ = chat_completion_with_meta(
        messages,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        timeout=timeout,
        prefer_fast=prefer_fast,
    )
    return text
