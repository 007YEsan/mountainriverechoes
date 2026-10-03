#!/bin/bash
# 启动民族音乐 Web 界面 (http://127.0.0.1:8766)
cd "$(dirname "$0")/.."
if [ -x "venv/bin/python" ]; then
    exec venv/bin/python webui/mountainriverechoes.py
else
    exec python3 webui/mountainriverechoes.py
fi
