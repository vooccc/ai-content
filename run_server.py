# -*- coding: utf-8 -*-
"""启动 ai-content 独立 Web 服务（默认 http://127.0.0.1:8010）。"""
import os
import uvicorn


def main():
    host = os.getenv("AICONTENT_HOST", "127.0.0.1")
    port = int(os.getenv("AICONTENT_PORT", "8010"))
    uvicorn.run("server.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
