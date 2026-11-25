# -*- coding: utf-8 -*-
"""Canvas 新版创作台专属流式多模态 LLM 调用封装（复用 llm_bridge 模型目录，零破坏旧接口）。"""
from __future__ import annotations

import json
import os
import re
from typing import Any, Dict, Generator, List, Tuple

import requests

from . import llm_bridge, settings_store


def _normalize_anthropic_url(base_url: str) -> str:
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


def _to_anthropic_content(content: Any) -> Any:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return str(content or "")
    blocks: List[Dict[str, Any]] = []
    for part in content:
        if not isinstance(part, dict):
            continue
        ptype = part.get("type")
        if ptype == "text":
            txt = str(part.get("text") or "")
            if txt:
                blocks.append({"type": "text", "text": txt})
        elif ptype == "image_url":
            url = str(((part.get("image_url") or {}).get("url")) or "")
            m = re.match(r"^data:([^;]+);base64,(.+)$", url, re.S)
            if m:
                blocks.append({
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": m.group(1).strip(),
                        "data": m.group(2).strip(),
                    },
                })
    return blocks or ""


def _stream_openai(
    base_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float,
    max_tokens: int,
    timeout: int,
) -> Generator[Tuple[str, str], None, None]:
    url = base_url if base_url.endswith("/chat/completions") else f"{base_url.rstrip('/')}/chat/completions"
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
        "stream": True,
    }
    with requests.post(url, headers=headers, json=payload, timeout=timeout, stream=True) as resp:
        resp.raise_for_status()
        for raw in resp.iter_lines():
            line = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else (raw or "")
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                break
            try:
                obj = json.loads(data)
                choices = obj.get("choices") or []
                if not choices:
                    continue
                delta = choices[0].get("delta") or {}
            except Exception:
                continue
            rc = delta.get("reasoning_content")
            if rc:
                yield ("reasoning", str(rc))
            c = delta.get("content")
            if c:
                yield ("content", str(c))


def _stream_anthropic(
    base_url: str,
    api_key: str,
    model: str,
    messages: List[Dict[str, Any]],
    temperature: float,
    max_tokens: int,
    timeout: int,
) -> Generator[Tuple[str, str], None, None]:
    url = _normalize_anthropic_url(base_url)
    headers = {
        "Content-Type": "application/json",
        "anthropic-version": "2023-06-01",
    }
    if api_key:
        headers["x-api-key"] = api_key
    sys_parts: List[str] = []
    anth_msgs: List[Dict[str, Any]] = []
    for m in messages:
        role = str(m.get("role") or "user").strip().lower()
        raw_content = m.get("content")
        if role == "system":
            txt = raw_content if isinstance(raw_content, str) else json.dumps(raw_content, ensure_ascii=False)
            if txt:
                sys_parts.append(txt)
            continue
        r_norm = "assistant" if role == "assistant" else "user"
        conv = _to_anthropic_content(raw_content)
        if not conv:
            continue
        if anth_msgs and anth_msgs[-1]["role"] == r_norm:
            prev = anth_msgs[-1]["content"]
            if isinstance(prev, str) and isinstance(conv, str):
                anth_msgs[-1]["content"] = prev + "\n\n" + conv
            else:
                prev_list = [{"type": "text", "text": prev}] if isinstance(prev, str) else list(prev)
                conv_list = [{"type": "text", "text": conv}] if isinstance(conv, str) else list(conv)
                anth_msgs[-1]["content"] = prev_list + conv_list
        else:
            anth_msgs.append({"role": r_norm, "content": conv})
    if not anth_msgs:
        anth_msgs = [{"role": "user", "content": "\n".join(sys_parts) or "Hello"}]
        sys_parts = []
    elif anth_msgs[0]["role"] != "user":
        anth_msgs.insert(0, {"role": "user", "content": "请继续。"})

    payload: Dict[str, Any] = {
        "model": model,
        "messages": anth_msgs,
        "max_tokens": max(512, int(max_tokens or 4096)),
        "temperature": temperature,
        "stream": True,
    }
    if sys_parts:
        payload["system"] = "\n\n".join(sys_parts)

    with requests.post(url, headers=headers, json=payload, timeout=timeout, stream=True) as resp:
        resp.raise_for_status()
        for raw in resp.iter_lines():
            line = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else (raw or "")
            if not line or not line.startswith("data:"):
                continue
            data = line[5:].strip()
            if not data or data == "[DONE]":
                break
            try:
                evt = json.loads(data)
            except Exception:
                continue
            if evt.get("type") == "content_block_delta":
                delta = evt.get("delta") or {}
                dt = delta.get("type")
                if dt == "thinking_delta" and delta.get("thinking"):
                    yield ("reasoning", str(delta["thinking"]))
                elif dt == "text_delta" and delta.get("text"):
                    yield ("content", str(delta["text"]))


def _resolve_candidates(model: str = "") -> List[Tuple[str, Dict[str, Any]]]:
    st = settings_store.load_settings()
    cat = llm_bridge.build_model_catalog(model)
    models_map = cat.get("models") or {}
    target = (model or cat.get("default") or "").strip()
    candidates: List[Tuple[str, Dict[str, Any]]] = []
    seen: set[str] = set()

    def _add(mid: str, cfg: Dict[str, Any]) -> None:
        if mid and mid not in seen and cfg.get("base_url"):
            seen.add(mid)
            candidates.append((mid, cfg))

    if target and target in models_map:
        _add(target, models_map[target])
    elif not models_map:
        env_url = (os.getenv("LLM_BASE_URL") or "").strip().rstrip("/")
        env_key = (os.getenv("LLM_API_KEY") or "").strip()
        if env_url:
            _add(target or (os.getenv("LLM_MODEL") or "deepseek-chat").strip(), {"base_url": env_url, "api_key": env_key, "transport": "openai_chat"})

    if not model and st.get("mode") != "custom":
        for fid in llm_bridge._FAST_MODEL_PRIORITY:
            if fid in models_map and models_map[fid].get("api_key"):
                _add(fid, models_map[fid])
                if len(candidates) >= 3:
                    break
    return candidates


def stream_multimodal_chat(
    messages: List[Dict[str, Any]],
    model: str = "",
    temperature: float = 0.4,
    max_tokens: int = 4096,
    timeout: int = 120,
) -> Generator[Tuple[str, str], None, None]:
    """流式多模态对话，逐块 yield ('model'|'reasoning'|'content'|'error', value)。"""
    candidates = _resolve_candidates(model)
    if not candidates:
        yield ("error", "未配置可用的文本模型或 Gateway，请先在「账号与设置」配置。")
        return

    last_err: Exception | None = None
    for mid, cfg in candidates[:3]:
        base_url = str(cfg.get("base_url") or "").rstrip("/")
        if not base_url:
            continue
        api_key = str(cfg.get("api_key") or "")
        transport = str(cfg.get("transport") or "openai_chat")
        emitted = False
        try:
            yield ("model", mid)
            gen = (
                _stream_anthropic(base_url, api_key, mid, messages, temperature, max_tokens, timeout)
                if transport == "anthropic_messages"
                else _stream_openai(base_url, api_key, mid, messages, temperature, max_tokens, timeout)
            )
            for kind, chunk in gen:
                emitted = True
                yield (kind, chunk)
            if emitted:
                return
        except Exception as e:
            last_err = e
            if emitted:
                yield ("error", f"流式中断：{e}")
                return
            continue
    yield ("error", f"模型调用失败：{last_err or '无有效响应'}")
