# -*- coding: utf-8 -*-
"""ai-content 工作流引擎（从柳如烟/ai-quant 工作流引擎复制而来，纯逻辑、零三方依赖）。

- 工作流 = 节点列表（data/agent/judge/debater/loop/human）+ 角色提示词。
- 共享 state + 每个节点显式声明 reads（上下文隔离）。
- 配置驱动：换一份 flows/*.yaml 就是另一条工作流（见 loader.py）。
"""
from .engine import run_workflow, run_single_step, WorkflowDef, Node  # noqa: F401
