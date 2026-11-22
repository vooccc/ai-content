# -*- coding: utf-8 -*-
"""分步创作工作台 JSON 桥：供柳如烟「自媒体 · 创作工作台」子进程调用。

两个动作（stdout 输出**单个** JSON 对象）：
  1) 初始化：python -m studio_json --wf <id> --inputs '<json>'
     → {"type":"init","name":..,"inputs":[..],"nodes":[{id,type,role,writes}],"state":{...}}
  2) 跑一步：python -m studio_json --step --state <state_file> --index <i> [--feedback <txt>]
     → {"type":"step","index":i,"node":..,"writes":..,"output":..,"state":{...}}

每步产物 = state[node.writes]；state 全 JSON 可序列化，由柳如烟落盘（持久化 / 可回看 / 可回退）。
"""
import os
import sys
import json

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from workflow.engine import run_single_step, _new_state, assemble_user
from workflow.loader import REGISTRY


def _emit(obj):
    sys.stdout.write(json.dumps(obj, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _arg(args, flag, default=None):
    return args[args.index(flag) + 1] if flag in args and args.index(flag) + 1 < len(args) else default


def _to_text(output):
    if isinstance(output, dict):
        return (output.get("material") or output.get("feedback")
                or output.get("plain_text") or output.get("html")
                or output.get("status") or json.dumps(output, ensure_ascii=False))
    return str(output) if output is not None else ""


def _init(wf_id, inputs_json):
    if wf_id not in REGISTRY:
        _emit({"type": "error", "msg": f"unknown workflow: {wf_id}"})
        return
    wf, _tools = REGISTRY[wf_id]
    try:
        inputs = json.loads(inputs_json) if inputs_json else {}
    except Exception:
        inputs = {}
    state = _new_state(wf, inputs)
    # 带上 tool：宿主可区分 data 子类（content.gather 自抓 vs content.format 排版）
    nodes = [{"id": n.id, "type": n.type, "role": n.role,
              "writes": n.writes or n.id, "tool": n.tool or ""}
             for n in wf.nodes]
    _emit({"type": "init", "name": wf.name, "inputs": wf.inputs, "nodes": nodes, "state": state})


def _step(state_file, index, feedback, stream=False, style=""):
    try:
        with open(state_file, "r", encoding="utf-8") as f:
            state = json.load(f)
    except Exception as e:
        _emit({"type": "error", "msg": f"读取 state 失败：{e}"})
        return
    wf_id = state.get("_wf")
    if wf_id not in REGISTRY:
        _emit({"type": "error", "msg": f"unknown workflow in state: {wf_id}"})
        return
    wf, tools = REGISTRY[wf_id]
    node = wf.nodes[index]
    writes = node.writes or node.id

    # 写作风格：按 style 叠加覆盖该角色的 system prompt（流式与非流式都生效）。
    # 用 workflow 感知版：style 只覆盖「确属公众号基础提示词」的 role，避免公众号 style
    # 串到小红书等其它平台的同名 role（如两平台都有 planner，但提示词完全不同）。
    if style and node.role and node.type in ("agent", "judge"):
        from workflow.loader import resolve_role_prompt_for
        resolved = resolve_role_prompt_for(wf, node.role, style)
        if resolved:
            wf.role_prompts[node.role] = resolved

    # 记录写作风格到 state，供 format_output 等非 agent 节点读取（选视觉模板）
    if style:
        state["_style"] = style

    # 流式：agent/judge 节点逐块吐 delta（content）/ reasoning（思考链），让前端看到生成过程
    if stream and node.type in ("agent", "judge"):
        from ai.model_catalog import resolve_client
        llm = resolve_client(node.params.get("model") or "")  # 多级 model：节点级 > 项目/默认
        user = assemble_user(wf, state, node, feedback)
        system = wf.role_prompts.get(node.role, "")
        _emit({"type": "begin", "index": index, "node": node.id, "writes": writes})
        acc = []
        try:
            for kind, text in llm.chat_stream(user, system=system,
                                              temperature=node.params.get("temperature", 0.3)):
                if kind == "reasoning":
                    _emit({"type": "reasoning", "text": text})
                else:
                    acc.append(text)
                    _emit({"type": "delta", "text": text})
        except Exception as e:
            _emit({"type": "error", "msg": str(e)})
            return
        out = "".join(acc)
        state.setdefault("errors", [])
        state.setdefault("timings", {})
        state[writes] = out
        _emit({"type": "step", "index": index, "node": node.id, "writes": writes,
               "output": out, "state": state})
        return

    # 非流式（data/human，或未要求 stream）；agent/judge 按多级 model 选 client
    try:
        from ai.model_catalog import resolve_client
        llm = resolve_client(node.params.get("model") or "") if node.type in ("agent", "judge") else None
        state = run_single_step(wf, state, index, llm=llm, tools=tools, feedback=feedback)
    except Exception as e:
        _emit({"type": "error", "msg": str(e)})
        return
    _emit({"type": "step", "index": index, "node": node.id, "writes": writes,
           "output": _to_text(state.get(writes, "")), "state": state})


def _styles():
    from workflow.loader import list_styles
    _emit({"type": "styles", "styles": list_styles()})


def _fetch(urls_json):
    """抓取网络素材：解析 urls（JSON 数组或字符串），逐个抓正文拼成 material 文本。

    供柳如烟「资料收集」的「网址抓取」用——前端粘贴多行 URL，后端子进程调本动作，
    返回拼好的 material，柳如烟再追加进 state.data.material。复用 loader._fetch_urls，
    抓取逻辑（微信/GitHub/普通页 + SSL 降级 + 失败不崩链）只在 ai-content 维护一份。
    """
    from workflow.loader import _fetch_urls, _normalize_sources
    try:
        raw = json.loads(urls_json) if urls_json else []
    except Exception:
        raw = urls_json or ""
    # 兼容 {"urls":[...]} 包装和裸 URL 数组/字符串两种写法
    if isinstance(raw, dict):
        raw = raw.get("urls") or raw.get("sources") or []
    urls = _normalize_sources(raw)
    if not urls:
        _emit({"type": "error", "msg": "没有有效的 http(s) 链接"})
        return
    material = _fetch_urls(urls)
    # 统计成败：material 里「状态：成功」的条目数 / 「抓取失败」的条目数
    ok = material.count("状态：成功")
    failed = material.count("抓取失败")
    _emit({"type": "fetch", "material": material,
           "count": ok, "failed": failed, "total": len(urls)})


def _get_prompts(style):
    """列默认角色清单的提示词（按 style 解析）+ 可用风格，供前端「提示词编辑器」。"""
    from workflow.loader import list_role_prompts, list_styles
    _emit({"type": "prompts", "style": style or "",
           "roles": list_role_prompts(style or ""), "styles": list_styles()})


def _save_style(file):
    """读 json {name, prompts:{role:text}} 存成自定义风格。"""
    from workflow.loader import save_style
    try:
        with open(file, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception as e:
        _emit({"type": "error", "msg": f"读取风格数据失败：{e}"})
        return
    res = save_style(payload.get("name", ""), payload.get("prompts", {}) or {})
    _emit({"type": "saved", **res})


def main():
    args = sys.argv[1:]
    if "--styles" in args:
        _styles()
    elif "--get-prompts" in args:
        _get_prompts(_arg(args, "--style", "") or "")
    elif "--save-style" in args:
        _save_style(_arg(args, "--file"))
    elif "--step" in args:
        _step(_arg(args, "--state"), int(_arg(args, "--index", "0")),
              _arg(args, "--feedback"), stream="--stream" in args,
              style=_arg(args, "--style", "") or "")
    elif "--wf" in args:
        _init(_arg(args, "--wf"), _arg(args, "--inputs"))
    elif "--fetch" in args:
        _fetch(_arg(args, "--fetch"))
    else:
        _emit({"type": "error", "msg": "no action (--wf or --step)"})


if __name__ == "__main__":
    main()
