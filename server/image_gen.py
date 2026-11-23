# -*- coding: utf-8 -*-
"""自包含生图客户端：调用 OpenAI 兼容 /v1/images/generations 端点。

Provider 解析优先级：
1. 环境变量 ``AICONTENT_IMAGE_BASE_URL`` / ``AICONTENT_IMAGE_API_KEY``（显式独立配置）
2. ``server.paths.models_config_paths()``（优先 ai-content/data/models.json，其次兼容读取柳如烟 models.json）
"""
from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, Optional
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from .paths import models_config_paths

_IMAGE_GEN_PATTERNS = [
    re.compile(r"dall-?e", re.IGNORECASE),
    re.compile(r"\bsd-", re.IGNORECASE),
    re.compile(r"stable-diffusion", re.IGNORECASE),
    re.compile(r"flux", re.IGNORECASE),
    re.compile(r"midjourney", re.IGNORECASE),
    re.compile(r"image-?gen", re.IGNORECASE),
    re.compile(r"image-?\d", re.IGNORECASE),
    re.compile(r"agnes-image", re.IGNORECASE),
    re.compile(r"wanx", re.IGNORECASE),
    re.compile(r"cogview", re.IGNORECASE),
    re.compile(r"kolors", re.IGNORECASE),
]


def _is_image_gen_model(model_id: str) -> bool:
    return any(p.search(model_id) for p in _IMAGE_GEN_PATTERNS)


def _load_providers() -> Dict[str, Any]:
    for models_path, secrets_path in models_config_paths():
        try:
            config = json.loads(models_path.read_text(encoding="utf-8-sig"))
        except Exception:
            continue
        providers_raw = config.get("providers", {})
        secrets: Dict[str, str] = {}
        if secrets_path and secrets_path.exists():
            try:
                secrets = json.loads(secrets_path.read_text(encoding="utf-8-sig"))
            except Exception:
                secrets = {}
        providers: Dict[str, Any] = {}
        for pid, pdata in providers_raw.items():
            if isinstance(pdata, dict):
                item = dict(pdata)
                sk = f"provider:{pid}"
                if sk in secrets and not item.get("api_key"):
                    item["api_key"] = secrets[sk]
                providers[pid] = item
        if providers:
            return providers
    return {}


def _provider_matches(pdata: Dict, provider_selector: str) -> bool:
    selector = (provider_selector or "").strip().lower()
    if not selector:
        return False
    return selector in {
        str(pdata.get("id", "")).lower(),
        str(pdata.get("name", "")).lower(),
    }


def _provider_has_model(pdata: Dict, model_id: str) -> bool:
    for m in pdata.get("models", []):
        mid = m.get("id", "") if isinstance(m, dict) else str(m)
        if mid == model_id:
            return True
    return False


def _find_provider_for_model(providers: Dict, model_id: str, provider_selector: str = "") -> Optional[Dict]:
    for pid, pdata in providers.items():
        if not pdata.get("enabled", True):
            continue
        if provider_selector and not _provider_matches(pdata, provider_selector):
            continue
        if _provider_has_model(pdata, model_id):
            return pdata
    return None


def _find_any_image_gen(providers: Dict, provider_selector: str = ""):
    for pid, pdata in providers.items():
        if not pdata.get("enabled", True):
            continue
        if provider_selector and not _provider_matches(pdata, provider_selector):
            continue
        for m in pdata.get("models", []):
            mid = m.get("id", "") if isinstance(m, dict) else str(m)
            if _is_image_gen_model(mid):
                return pdata, mid
    return None, None


def _build_images_url(base_url: str) -> str:
    url = base_url.rstrip("/").rstrip("#")
    if url.endswith("/v1") or re.search(r"/v\d+(alpha|beta)?$", url):
        return url + "/images/generations"
    return url + "/v1/images/generations"


def _read_image_as_base64(image_path: str) -> Optional[str]:
    p = Path(image_path)
    if not p.exists():
        return None
    raw = p.read_bytes()
    ext = p.suffix.lower()
    mime_map = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp", ".bmp": "image/bmp",
    }
    mime = mime_map.get(ext, "image/png")
    b64 = base64.b64encode(raw).decode("ascii")
    return f"data:{mime};base64,{b64}"


def generate_image(
    prompt: str,
    model: str = "",
    size: str = "1024x1024",
    n: int = 1,
    response_format: str = "",
    image_path: str = "",
    style: str = "",
    negative_prompt: str = "",
    provider_selector: str = "",
) -> Dict[str, Any]:
    env_base = (os.getenv("AICONTENT_IMAGE_BASE_URL") or "").strip()
    env_key = (os.getenv("AICONTENT_IMAGE_API_KEY") or "").strip()
    env_model = (os.getenv("AICONTENT_IMAGE_MODEL") or "").strip()

    from . import settings_store
    st_cfg = settings_store.load_settings()

    resolved_model = (model or "").strip() or env_model or str(st_cfg.get("default_image_model") or "").strip()
    provider: Optional[Dict[str, Any]] = None

    if env_base:
        provider = {"id": "env", "base_url": env_base, "api_key": env_key}
        if not resolved_model:
            resolved_model = "dall-e-3"
    elif st_cfg.get("image_base_url") and st_cfg.get("image_api_key"):
        provider = {
            "id": "custom_image",
            "base_url": str(st_cfg["image_base_url"]).strip(),
            "api_key": str(st_cfg["image_api_key"]).strip(),
        }
        if not resolved_model:
            resolved_model = "dall-e-3"
    elif st_cfg.get("mode") == "custom" and st_cfg.get("llm_base_url") and st_cfg.get("llm_api_key") and not provider_selector:
        provider = {
            "id": "custom",
            "base_url": str(st_cfg["llm_base_url"]).strip(),
            "api_key": str(st_cfg["llm_api_key"]).strip(),
        }
        if not resolved_model:
            resolved_model = "dall-e-3"
    else:
        providers = _load_providers()
        if not providers:
            return {"error": "未配置生图模型：请在「账号与设置 → 模型与连接配置」中配置生图接口或模型。"}
        if resolved_model:
            provider = _find_provider_for_model(providers, resolved_model, provider_selector)
            if not provider:
                suffix = f"，provider='{provider_selector}'" if provider_selector else ""
                return {"error": f"找不到拥有模型 '{resolved_model}' 的 provider{suffix}。"}
        else:
            provider, resolved_model = _find_any_image_gen(providers, provider_selector)
            if not provider:
                return {"error": "没有找到可用的生图模型，请先选择一个生图模型。"}

    base_url = (provider.get("base_url") or "").strip()
    api_key = (provider.get("api_key") or "").strip()
    if not base_url:
        return {"error": f"Provider '{provider.get('id', '?')}' 没有配置 base_url。"}

    endpoint = _build_images_url(base_url)
    body: Dict[str, Any] = {
        "model": resolved_model,
        "prompt": prompt,
        "n": min(4, max(1, n)),
        "size": size,
    }
    extra: Dict[str, Any] = {}
    if image_path:
        img_data = _read_image_as_base64(image_path)
        if img_data:
            extra["tags"] = ["img2img"]
            extra["image"] = [img_data]
        elif image_path.startswith("http"):
            extra["tags"] = ["img2img"]
            extra["image"] = [image_path]
        else:
            return {"error": f"图片文件不存在: {image_path}"}

    if "agnes" in resolved_model.lower():
        extra["response_format"] = response_format if response_format in ("url", "b64_json") else "url"
    elif response_format in ("url", "b64_json"):
        body["response_format"] = response_format

    if style:
        body["style"] = style
    if negative_prompt:
        body["negative_prompt"] = negative_prompt
    if extra:
        body["extra_body"] = extra

    headers = {"Content-Type": "application/json", "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    for k, v in (provider.get("extra_headers") or {}).items():
        headers[k] = v

    req = Request(endpoint, data=json.dumps(body, ensure_ascii=False).encode("utf-8"), headers=headers, method="POST")
    try:
        with urlopen(req, timeout=120) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except HTTPError as e:
        try:
            err_body = json.loads(e.read().decode("utf-8"))
            err_msg = err_body.get("error", {}).get("message") or err_body.get("detail") or str(err_body)[:500]
        except Exception:
            err_msg = str(e)
        return {"error": f"生图 API 返回错误 {e.code}: {err_msg}", "provider": provider.get("id", ""), "model": resolved_model}
    except URLError as e:
        return {"error": f"网络请求失败: {e.reason}"}
    except Exception as e:
        return {"error": f"请求异常: {e}"}

    images = data.get("data", [])
    if not images:
        return {"error": "生图 API 返回了空的 data 列表。"}

    results = []
    for img in images:
        item: Dict[str, Any] = {}
        if "url" in img:
            item["url"] = img["url"]
            item["display_type"] = "url"
        elif "b64_json" in img:
            item["data_uri"] = f"data:image/png;base64,{img['b64_json']}"
            item["display_type"] = "b64"
        if "revised_prompt" in img:
            item["revised_prompt"] = img["revised_prompt"]
        results.append(item)

    return {
        "_runtime_block": "generated_image",
        "images": results,
        "prompt": prompt,
        "model": resolved_model,
        "provider": provider.get("id", ""),
        "size": size,
        "count": len(results),
    }
