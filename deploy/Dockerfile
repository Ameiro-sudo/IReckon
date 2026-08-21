# syntax=docker/dockerfile:1
# ============================================================
# Stage 1: 构建 Vue 前端
# ============================================================
FROM node:20-alpine AS frontend-build

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
# 注意：Windows/9p 挂载下无符号链接支持，使用 node 直接调用 vite
RUN npm ci --no-bin-links --no-audit --no-fund || npm install --no-bin-links --no-audit --no-fund
COPY frontend/ .
RUN node node_modules/vite/bin/vite.js build

# ============================================================
# Stage 2: Python 后端 + 静态前端托管
# ============================================================
FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    IRECKON_HOME=/app \
    IRECKON_API_HOST=0.0.0.0 \
    IRECKON_API_PORT=8000

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# 后端源码与配置
COPY main.py ./
COPY app/ ./app/
COPY config/ ./config/
COPY scripts/ ./scripts/

# 前端构建产物
COPY --from=frontend-build /build/frontend/dist/ ./frontend/dist/

# 运行时数据目录
RUN mkdir -p /app/data \
    && useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
VOLUME ["/app/data"]

# 以非 root 运行：容器被攻破时不直接持有宿主 root 等价权限
USER appuser

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD curl -f http://localhost:8000/api/health || exit 1

CMD ["python", "-m", "uvicorn", "app.web.api:app", "--host", "0.0.0.0", "--port", "8000"]
