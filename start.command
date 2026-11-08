#!/bin/zsh
cd "$(dirname "$0")"
if [ ! -d ".venv" ]; then
  echo "📦 首次运行：正在创建 Python 虚拟环境并安装依赖..."
  python3 -m venv .venv
  ./.venv/bin/pip install -r requirements.txt
fi
echo "🚀 Starting Switch Music Web UI at http://127.0.0.1:8765 ..."
open "http://127.0.0.1:8765" 2>/dev/null || true
./.venv/bin/python app.py
