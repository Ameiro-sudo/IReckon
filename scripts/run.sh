#!/usr/bin/env bash
# IReckon 生产环境启动脚本
# 用法:
#   ./scripts/run.sh            # 生产模式：构建前端(如需) + 启动后端 (FastAPI 托管前端)
#   ./scripts/run.sh --dev      # 开发模式：前端 dev server + 后端
#   ./scripts/run.sh --check    # 只做依赖/构建检查

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

PY="${PYTHON:-python3}"
MODE="${1:-prod}"

echo "==> IReckon launcher (mode: ${MODE})"

require_python() {
  if ! command -v "$PY" >/dev/null 2>&1; then
    echo "[ERROR] 未找到 Python ($PY)，请先安装 Python 3.10+"
    exit 1
  fi
  "$PY" -c "import fastapi, uvicorn" 2>/dev/null || {
    echo "[INFO] 安装后端依赖..."
    "$PY" -m pip install -r requirements.txt
  }
}

build_frontend() {
  if [ -d "frontend/dist" ]; then
    echo "[INFO] 前端构建产物已存在 (frontend/dist)"
    return
  fi
  if ! command -v node >/dev/null 2>&1; then
    echo "[WARN] 未安装 Node.js，跳过前端构建，将使用 dev server (需 npm)"
    return
  fi
  echo "[INFO] 构建前端..."
  (cd frontend && npm install --no-bin-links --no-audit --no-fund >/dev/null && npm run build)
}

case "$MODE" in
  --check)
    require_python
    build_frontend
    echo "==> 检查完成 ✓"
    ;;
  --dev)
    require_python
    echo "[INFO] 开发模式启动 (前端 :3000 / 后端 :8000)"
    IRECKON_DEV_FRONTEND=1 "$PY" main.py
    ;;
  *)
    require_python
    build_frontend
    echo "[INFO] 生产模式启动 (后端 :8000 托管前端)"
    exec "$PY" main.py
    ;;
esac
