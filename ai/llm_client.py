# -*- coding: utf-8 -*-
"""
瘦 LLM 客户端：调用 OpenAI 兼容的 Chat Completions 接口（默认 DeepSeek）。

设计原则：
- 只做"文本进 → 文本/结构化 JSON 出"，不依赖柳如烟，保证量化引擎可独立运行。
- 任何 OpenAI 兼容端点都能用：DeepSeek 公网、柳如烟本地网关、其它。
- 配置优先级：构造参数 > 环境变量 > config.settings.LLM_CONFIG > 兜底默认。
"""
import os
import re
import json
import time

import requests

try:
    from config.settings import LLM_CONFIG
except Exception:  # 允许脱离 settings 单独使用
    LLM_CONFIG = {}


class LLMClient:
    def __init__(self, base_url=None, api_key=None, model=None, timeout=None):
        self.base_url = (base_url or os.environ.get("LLM_BASE_URL")
                         or LLM_CONFIG.get("base_url", "https://api.deepseek.com")).rstrip("/")
        self.api_key = (api_key or os.environ.get("LLM_API_KEY")
                        or LLM_CONFIG.get("api_key", ""))
        self.model = (model or os.environ.get("LLM_MODEL")
                      or LLM_CONFIG.get("model", "deepseek-chat"))
        self.timeout = timeout or LLM_CONFIG.get("timeout", 60)

    def chat(self, prompt: str, system: str = None,
             temperature: float = 0.2, max_retries: int = 2) -> str:
        """发起一次对话，返回模型文本。失败重试，仍失败抛异常。"""
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": self.model, "messages": messages, "temperature": temperature}

        last_err = None
        for attempt in range(max_retries + 1):
            try:
                resp = requests.post(url, headers=headers, json=payload, timeout=self.timeout)
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except Exception as e:  # 网络/限流/解析等
                last_err = e
                if attempt < max_retries:
                    time.sleep(2 * (attempt + 1))
        raise RuntimeError(f"LLM 调用失败（重试 {max_retries} 次）: {last_err}")

    def chat_stream(self, prompt: str, system: str = None, temperature: float = 0.2):
        """流式对话：逐块 yield ("content", delta) 或 ("reasoning", delta)。

        用于分步创作工作台「看到生成过程」。流式失败时回退非流式整段返回（仍 yield content）。
        reasoning_content 兼容 DeepSeek-R1 等带思考链的模型。
        """
        url = f"{self.base_url}/chat/completions"
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        payload = {"model": self.model, "messages": messages,
                   "temperature": temperature, "stream": True}
        try:
            with requests.post(url, headers=headers, json=payload,
                               timeout=self.timeout, stream=True) as resp:
                resp.raise_for_status()
                # 不用 decode_unicode=True：SSE 无 charset 时 requests 默认按 ISO-8859-1
                # 解码 → 中文乱码。这里取 bytes 手动按 utf-8 解码。
                for raw in resp.iter_lines():
                    line = raw.decode("utf-8", errors="replace") if isinstance(raw, (bytes, bytearray)) else (raw or "")
                    if not line or not line.startswith("data:"):
                        continue
                    data = line[5:].strip()
                    if data == "[DONE]":
                        break
                    try:
                        delta = json.loads(data)["choices"][0].get("delta", {})
                    except Exception:
                        continue
                    rc = delta.get("reasoning_content")
                    if rc:
                        yield ("reasoning", rc)
                    c = delta.get("content")
                    if c:
                        yield ("content", c)
        except Exception as e:
            try:
                yield ("content", self.chat(prompt, system=system, temperature=temperature))
            except Exception:
                yield ("content", f"（生成失败：{e}）")

    def chat_json(self, prompt: str, system: str = None, **kwargs):
        """要求模型返回 JSON，解析为 dict；解析失败返回 None。"""
        raw = self.chat(prompt, system=system, **kwargs)
        return extract_json(raw)


def extract_json(text: str):
    """从模型输出里提取 JSON：先直接 parse，失败则抓第一个 {...} 块。"""
    if not text:
        return None
    try:
        return json.loads(text)
    except Exception:
        pass
    # 去掉 ```json ... ``` 围栏后再试
    fenced = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S)
    if fenced:
        try:
            return json.loads(fenced.group(1))
        except Exception:
            pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None
