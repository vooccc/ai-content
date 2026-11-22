# -*- coding: utf-8 -*-
"""LLM 客户端包：指向任意 OpenAI 兼容端点。

集成进柳如烟时由宿主通过环境变量注入网关地址（LLM_BASE_URL / LLM_API_KEY / LLM_MODEL）；
独立运行时把 LLM_BASE_URL 换成任意公网 OpenAI 端点即可。
"""
