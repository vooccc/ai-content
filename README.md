# ai-content

独立自媒体内容创作与多平台分发应用（已从柳如烟主工程完整剥离）。

## 形态

**本地常驻后台服务（FastAPI）+ 独立 Web 工作台（React / Vite）**：
- 后端 `server/` 负责创作工作台 API、资料搜集、生图管线、多平台账号与公众号草稿箱直推，并静态托管 `frontend/dist`。
- 引擎 `workflow/` + `flows/` + `prompts/` 负责 YAML 工作流编排与角色提示词解析。
- 生产模式访问 `http://127.0.0.1:8010` 即可使用完整 Web 工作台。

## 目录

```
server/          # FastAPI 独立服务（content / studio / publish / xhs / wechat_mp / llm_bridge）
frontend/        # 独立 Vite + React + TypeScript 前端工作台
workflow/        # 通用工作流引擎（纯逻辑）
flows/           # YAML 流水线定义（content_pipeline / xhs_pipeline）
prompts/         # 角色提示词与写作风格库
ai/              # 瘦 LLM 客户端与模型目录解析
studio_json.py   # 工作流单步执行桥
run_server.py    # 独立 Web 服务启动入口
start.bat        # Windows 一键启动脚本
```

## 快速启动

```bash
# 1. 安装后端依赖
venv\Scripts\python.exe -m pip install -r requirements.txt

# 2. 构建前端（首次或修改前端后）
cd frontend && npm install && npm run build && cd ..

# 3. 启动服务（默认 http://127.0.0.1:8010）
venv\Scripts\python.exe run_server.py
```

开发联调时可同时启动 `cd frontend && npm run dev`（`http://localhost:5175`，已配 Vite proxy 到 `8010`）。

## 模型与配置

1. **Gateway 模式（推荐与柳如烟协作时使用）**：设置环境变量 `AICONTENT_GATEWAY_URL`（如 `http://127.0.0.1:8001/gateway/v1`）与 `AICONTENT_GATEWAY_TOKEN`，或在 `data/gateway.json` 中配置。
2. **本地配置文件 / 兼容模式**：优先读取 `data/models.json`；未单独配置时自动兼容只读本机 `~/.liuruyan-dev` 或 `~/.liuruyan` 中的模型与搜索配置。
3. **环境变量兜底**：`LLM_BASE_URL` / `LLM_API_KEY` / `LLM_MODEL`。
