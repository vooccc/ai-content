# -*- coding: utf-8 -*-
"""启动 ai-content 独立 Web 服务（默认 http://127.0.0.1:8010）。"""
import argparse
import os
import signal
import socket
import subprocess
import sys
import time

import httpx
import uvicorn


def _port_in_use(host: str, port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.5)
        return s.connect_ex((host, port)) == 0


def _try_replace_existing(host: str, port: int) -> None:
    try:
        r = httpx.get(f"http://{host}:{port}/health", timeout=1.5)
        if r.status_code != 200 or r.json().get("service") != "ai-content":
            print(f"[警告] 端口 {port} 已被其他程序占用，请更换 AICONTENT_PORT 后重试。")
            sys.exit(1)
    except Exception:
        print(f"[警告] 端口 {port} 已被占用且非 ai-content 服务，请更换 AICONTENT_PORT。")
        sys.exit(1)

    if os.name == "nt":
        out = subprocess.check_output(
            ["cmd", "/c", f"netstat -ano | findstr :{port}"],
            text=True,
            errors="replace",
        )
        pids = set()
        for line in out.splitlines():
            parts = line.split()
            if len(parts) >= 5 and "LISTENING" in line and f":{port}" in parts[1]:
                try:
                    pid = int(parts[-1])
                    if pid != os.getpid():
                        pids.add(pid)
                except ValueError:
                    pass
        for pid in pids:
            subprocess.run(["taskkill", "/PID", str(pid), "/F"], capture_output=True)
    else:
        out = subprocess.check_output(["lsof", "-ti", f":{port}"], text=True, errors="replace")
        for tok in out.split():
            try:
                pid = int(tok)
                if pid != os.getpid():
                    os.kill(pid, signal.SIGTERM)
            except Exception:
                pass
    for _ in range(15):
        if not _port_in_use(host, port):
            return
        time.sleep(0.2)


def main():
    parser = argparse.ArgumentParser(description="Start ai-content server")
    parser.add_argument("--replace", action="store_true", help="Replace existing ai-content server on the same port")
    args, _ = parser.parse_known_args()

    host = os.getenv("AICONTENT_HOST", "127.0.0.1")
    port = int(os.getenv("AICONTENT_PORT", "8010"))

    if _port_in_use(host, port):
        if args.replace:
            _try_replace_existing(host, port)
        else:
            print(f"[提示] 端口 {port} 已有服务在运行。如需重启替换，请运行：python run_server.py --replace")
            sys.exit(1)

    uvicorn.run("server.app:app", host=host, port=port, reload=False)


if __name__ == "__main__":
    main()
