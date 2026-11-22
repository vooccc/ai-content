# -*- coding: utf-8 -*-
"""通用工作流引擎：节点化 + 共享 state + reads 隔离 + 防护 + human-in-the-loop。

节点类型：data / agent / judge / debater / loop / human。
每个 agent/judge 节点声明 reads（只读这些字段）→ 上下文隔离。
human 节点支持审核回调（CLI 交互 / UI 暂停），非交互环境自动通过。
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class Node:
    id: str
    type: str                                  # data|agent|judge|debater|loop|human
    role: Optional[str] = None
    reads: List[str] = field(default_factory=list)
    writes: Optional[str] = None
    tool: Optional[str] = None
    params: Dict[str, Any] = field(default_factory=dict)
    body: List["Node"] = field(default_factory=list)   # loop 子节点


@dataclass
class WorkflowDef:
    id: str
    name: str
    inputs: List[str]
    role_prompts: Dict[str, str]               # role -> system prompt
    nodes: List[Node]


_REPORT_FIELDS = [("市场/技术面", "market_report"), ("基本面", "fundamental_report"),
                  ("新闻", "news_report"), ("情绪", "sentiment_report")]


def _four_reports(state: dict) -> str:
    return "\n\n".join(f"【{label}分析】\n{state.get(k) or '（无）'}" for label, k in _REPORT_FIELDS)


def _get_field(state: dict, ref: str):
    if ref == "reports":
        return _four_reports(state)
    if "." in ref:
        a, b = ref.split(".", 1)
        v = state.get(a)
        return v.get(b, "") if isinstance(v, dict) else ""
    return state.get(ref, "")


def assemble_context(state: dict, reads: List[str]) -> str:
    parts = []
    for ref in reads:
        val = _get_field(state, ref)
        parts.append(val if ref == "reports" else f"【{ref}】\n{val or '（无）'}")
    return "\n\n".join(parts)


def _new_state(wf: WorkflowDef, inputs: dict) -> dict:
    st: Dict[str, Any] = {"_wf": wf.id, "errors": [], "timings": {}, "events": []}
    st.update(inputs)
    st["data"] = {}
    st["debate"] = {"history": "", "current": "", "count": 0,
                    "bull_history": "", "bear_history": ""}
    return st


def assemble_user(wf: WorkflowDef, st: dict, node: "Node", feedback: Optional[str] = None) -> str:
    """拼装 agent/judge 节点的 user 消息（任务输入 + reads 隔离上下文 + 可选重写反馈）。

    抽出来供 _run_node 与分步工作台的流式执行（studio_json）复用，保证两条路径口径一致。
    """
    head = "任务输入：" + "，".join(f"{k}={st.get(k, '')}" for k in wf.inputs) + "\n"
    user = head + assemble_context(st, node.reads) + "\n\n请据此输出你的专业意见。"
    if feedback:
        prev = st.get(node.writes or "", "") if node.writes else ""
        if prev:
            user += "\n\n【上一版产物】\n" + str(prev)
        user += "\n\n【用户修改意见】\n" + feedback + "\n请据此重写本步产物。"
    return user


def _llm_call(llm, wf: WorkflowDef, role: str, user: str, temperature: float) -> str:
    system = wf.role_prompts.get(role, "")
    try:
        return llm.chat(prompt=user, system=system, temperature=temperature)
    except Exception as e:
        return f"（{role} 调用失败：{e}）"


def run_workflow(wf: WorkflowDef, inputs: dict, llm=None, tools: Optional[dict] = None,
                 on_event=None, human_handler=None, max_debate_rounds: int = 1,
                 pause_on_human: bool = False, state: Optional[dict] = None,
                 start_index: int = 0, resume_review: Optional[dict] = None) -> dict:
    """运行工作流。

    pause_on_human=True 时，遇到 human 节点会**暂停并返回**（state["status"]="paused"，
    state["_paused"] 记录待审内容），交给上层 UI 审核；之后用 state + start_index +
    resume_review 调用本函数续跑。pause_on_human=False 时 human 节点走 human_handler（CLI/自动）。
    """
    if llm is None:
        from ai.llm_client import LLMClient
        llm = LLMClient()
    tools = tools or {}
    st = state if state is not None else _new_state(wf, inputs)
    st.pop("_paused", None)
    st["status"] = "running"

    def emit(stage: str, text: str = ""):
        st["events"].append({"stage": stage, "text": text, "ts": time.time()})
        if on_event:
            try:
                on_event(stage, text)
            except Exception:
                pass

    t0 = time.time()
    i = start_index
    while i < len(wf.nodes):
        node = wf.nodes[i]
        if node.type == "human" and pause_on_human:
            if resume_review is not None:
                # 续跑：应用用户审核结果，继续下一节点
                st[node.writes or node.id] = resume_review
                emit(node.id + ":done",
                     f"审核：{resume_review.get('status', '')} {resume_review.get('feedback', '')}".strip())
                resume_review = None
            else:
                # 暂停：记录待审内容后返回，交给上层 UI
                emit(node.id, "等待人工审核 ...")
                st["_paused"] = {
                    "node": node.id, "index": i,
                    "writes": node.writes or node.id,
                    "content": assemble_context(st, node.reads),
                }
                st["status"] = "paused"
                st["timings"]["partial"] = round(time.time() - t0, 1)
                return st
        else:
            _run_node(node, wf, st, llm, tools, emit, max_debate_rounds, human_handler)
        i += 1

    st["status"] = "done"
    st["timings"]["total"] = round(time.time() - t0, 1)
    return st


def _run_node(node: Node, wf: WorkflowDef, st: dict, llm, tools: dict, emit,
              max_rounds: int, human_handler=None, step_feedback: Optional[str] = None):
    t0 = time.time()
    try:
        if node.type == "data":
            emit(node.id, "取数中 ...")
            fn = tools.get(node.tool)
            result = fn(st) if fn else {"error": f"工具未注册:{node.tool}"}
            if node.writes:
                st[node.writes] = result
            emit(node.id + ":done", "数据就绪")

        elif node.type in ("agent", "judge"):
            emit(node.id, f"{node.role} 思考中 ...")
            user = assemble_user(wf, st, node, step_feedback)
            out = _llm_call(llm, wf, node.role, user, node.params.get("temperature", 0.3))
            if node.writes:
                st[node.writes] = out
            emit(node.id + ":done", out)

        elif node.type == "debater":
            emit(node.id, f"{node.role} 发言 ...")
            out = _run_debater(node, wf, st, llm)
            emit(node.id + ":done", out)

        elif node.type == "loop":
            rounds = node.params.get("rounds", max_rounds)
            for _ in range(max(1, rounds)):
                for sub in node.body:
                    _run_node(sub, wf, st, llm, tools, emit, max_rounds, human_handler)

        elif node.type == "human":
            emit(node.id, "等待人工审核 ...")
            if human_handler:
                review = human_handler(node, st) or {}
            else:
                review = {"status": "auto_approved", "feedback": ""}
            st[node.writes or node.id] = review
            emit(node.id + ":done", f"审核：{review.get('status', '')} {review.get('feedback', '')}".strip())

        else:
            st["errors"].append({"where": node.id, "error": f"未知节点类型:{node.type}"})
    except Exception as e:
        st["errors"].append({"where": node.id, "error": str(e)})
        emit(node.id + ":error", str(e))
    st["timings"][node.id] = round(time.time() - t0, 1)


def run_single_step(wf: WorkflowDef, state: dict, index: int, llm=None,
                    tools: Optional[dict] = None, feedback: Optional[str] = None) -> dict:
    """只执行 wf.nodes[index] 这一个节点（分步创作工作台用）。

    复用 _run_node：data 取数 / agent·judge 调 LLM / human 自动通过。
    feedback 非空时，agent/judge 节点带"上一版 + 用户意见"重写本步。
    state 原地更新并返回（含该步产物 state[node.writes] 与 _last_step 元信息）。
    """
    if llm is None:
        from ai.llm_client import LLMClient
        llm = LLMClient()
    tools = tools or {}
    if index < 0 or index >= len(wf.nodes):
        raise IndexError(f"step index 越界: {index} / {len(wf.nodes)}")
    state.setdefault("errors", [])
    state.setdefault("timings", {})
    node = wf.nodes[index]

    events: List[dict] = []

    def emit(stage: str, text: str = ""):
        events.append({"stage": stage, "text": text})

    _run_node(node, wf, state, llm, tools, emit, max_rounds=1,
              human_handler=None, step_feedback=feedback)
    state["_last_step"] = {"index": index, "node": node.id,
                           "writes": node.writes or node.id, "events": events}
    return state


def _run_debater(node: Node, wf: WorkflowDef, st: dict, llm) -> str:
    deb = st["debate"]
    user = (f"标的：{st.get('symbol', '')}。\n四位分析师报告：\n{_four_reports(st)}\n\n"
            f"辩论历史：\n{deb['history'] or '（首轮）'}\n\n"
            f"对方上一轮：\n{deb['current'] or '（对方尚未发言）'}\n\n请发表你的论点。")
    out = _llm_call(llm, wf, node.role, user, node.params.get("temperature", 0.5))
    tag = "看涨方" if node.role == "bull" else "看跌方"
    deb["history"] += f"\n\n【{tag}】{out}"
    deb[node.role + "_history"] = deb.get(node.role + "_history", "") + f"\n\n{out}"
    deb["current"] = out
    deb["count"] += 1
    return out
