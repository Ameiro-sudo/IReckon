#!/usr/bin/env bash
# 启动前自动检查环境（兼容 Termux）

echo "============================================"
echo "  环境检查"
echo "============================================"

# Python 版本
PYVER=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python 版本: $PYVER"

# 必要系统工具
for cmd in pip git curl; do
    if command -v $cmd &> /dev/null; then
        echo "✓ $cmd 已安装"
    else
        echo "✗ $cmd 未安装"
    fi
done

# 端口占用检查（使用 netstat，若不存在则回退到 lsof）
check_port() {
    local port=$1
    if command -v netstat &> /dev/null; then
        if netstat -tuln 2>/dev/null | grep -q ":$port "; then
            echo "⚠ 端口 $port 已被占用"
        else
            echo "✓ 端口 $port 空闲"
        fi
    elif command -v ss &> /dev/null; then
        if ss -tuln 2>/dev/null | grep -q ":$port "; then
            echo "⚠ 端口 $port 已被占用"
        else
            echo "✓ 端口 $port 空闲"
        fi
    else
        echo "? 端口 $port 无法检查（缺少 netstat/ss）"
    fi
}

check_port 8000
check_port 8501

echo "============================================"
echo "检查完成。运行 ./run.sh 启动系统。"