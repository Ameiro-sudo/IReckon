#!/usr/bin/env bash
# 俺寻思 AI 工厂 启动脚本 (Termux/Ubuntu)
set -e

echo "============================================"
echo "  俺寻思 AI 工厂 启动中..."
echo "============================================"

# 自动设定项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# 1. 检查 Python 环境
if ! command -v python3 &> /dev/null; then
    echo "❌ Python3 未安装，请先安装 Python 3.10+"
    exit 1
fi

# 2. 检查依赖（可选）
if [ "$1" == "--check" ]; then
    python3 scripts/check_system.py
    exit $?
fi

# 3. 激活虚拟环境（如果存在）
if [ -f venv/bin/activate ]; then
    source venv/bin/activate
fi

# 4. 启动后端与前端
echo "🚀 启动后端服务 (端口 8000) ..."
python3 -m uvicorn web.api:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

echo "🚀 启动前端界面 (端口 8501) ..."
python3 -m streamlit run frontend/app.py --server.port 8501 --server.headless true &
FRONTEND_PID=$!

# 5. 捕获退出信号
cleanup() {
    echo ""
    echo "🛑 正在停止服务..."
    # 安全终止：仅当进程存在时发送信号
    if kill -0 $BACKEND_PID 2>/dev/null; then
        kill $BACKEND_PID 2>/dev/null
    fi
    if kill -0 $FRONTEND_PID 2>/dev/null; then
        kill $FRONTEND_PID 2>/dev/null
    fi
    wait $BACKEND_PID $FRONTEND_PID 2>/dev/null
    echo "✅ 服务已停止"
}
trap cleanup SIGINT SIGTERM EXIT

echo "✅ 所有服务已启动"
echo "   后端: http://localhost:8000"
echo "   前端: http://localhost:8501"
echo "   按 Ctrl+C 停止所有服务"
wait