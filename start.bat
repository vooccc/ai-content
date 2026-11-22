@echo off
cd /d "%~dp0"
set AICONTENT_PORT=8010
start "" http://127.0.0.1:%AICONTENT_PORT%
"%~dp0venv\Scripts\python.exe" run_server.py
