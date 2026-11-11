#!/bin/zsh
set -e
cd "$(dirname "$0")"

if [ ! -d ".venv" ]; then
  echo "📦 首次运行：正在创建 Python 虚拟环境..."
  python3 -m venv .venv
fi

if ! ./.venv/bin/python -c "import fastapi, uvicorn, ytmusicapi, spotipy, requests" 2>/dev/null; then
  echo "📥 正在检查并安装 Python 依赖..."
  ./.venv/bin/python -m pip install -r requirements.txt
fi

export PYTHONWARNINGS="ignore"
echo "🚀 正在启动 Switch Music 2.0 (http://127.0.0.1:8765) ..."

# Wait until port 8765 is actively listening before opening browser
(
  for i in {1..40}; do
    if nc -z 127.0.0.1 8765 2>/dev/null; then
      open "http://127.0.0.1:8765" 2>/dev/null || true
      break
    fi
    sleep 0.25
  done
) &

exec ./.venv/bin/python app.py
