# -*- coding: utf-8 -*-
"""ai-content 独立 FastAPI 服务入口（API + 静态托管 frontend/dist）。"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .canvas_routes import router as canvas_router
from .content_routes import router as content_router
from .paths import data_dir, project_root
from .publish_routes import router as publish_router
from .scheduler import start_scheduler, stop_scheduler
from .studio_routes import router as studio_router
from .topic_routes import router as topic_router


@asynccontextmanager
async def _lifespan(app: FastAPI):
    start_scheduler()
    try:
        yield
    finally:
        stop_scheduler()


app = FastAPI(title="AI Content Studio", version="0.1.0", lifespan=_lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(content_router)
app.include_router(studio_router)
app.include_router(canvas_router)
app.include_router(publish_router)
app.include_router(topic_router)


@app.get("/health")
def health():
    return {"ok": True, "service": "ai-content", "data_dir": str(data_dir())}


_FRONTEND_DIST = project_root() / "frontend" / "dist"
if _FRONTEND_DIST.is_dir():
    assets_dir = _FRONTEND_DIST / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")
    icons_dir = _FRONTEND_DIST / "media-icons"
    if icons_dir.is_dir():
        app.mount("/media-icons", StaticFiles(directory=str(icons_dir)), name="media-icons")

    @app.get("/")
    def serve_index():
        return FileResponse(_FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-store"})

    @app.get("/{full_path:path}")
    def serve_spa(full_path: str):
        candidate = _FRONTEND_DIST / full_path
        if full_path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(_FRONTEND_DIST / "index.html", headers={"Cache-Control": "no-store"})
else:
    @app.get("/")
    def no_dist():
        return JSONResponse({
            "ok": True,
            "service": "ai-content",
            "hint": "frontend/dist 未构建，请运行 cd frontend && npm run build（或开发模式 npm run dev）",
        })
