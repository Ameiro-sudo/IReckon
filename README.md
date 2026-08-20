<p style="text-align:center">
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=for-the-badge&logo=python" alt="Python">
  <img src="https://img.shields.io/badge/FastAPI-0.110%2B-00a393?style=for-the-badge&logo=fastapi" alt="FastAPI">
  <img src="https://img.shields.io/badge/Vue_3-4.21%2B-4FC08D?style=for-the-badge&logo=vue.js" alt="Vue 3">
  <img src="https://img.shields.io/badge/LangGraph-%E2%9C%94-6C5CE7?style=for-the-badge" alt="LangGraph">
  <img src="https://img.shields.io/badge/ChromaDB-%E2%9C%94-FF6B6B?style=for-the-badge" alt="ChromaDB">
  <br>
  <img src="https://img.shields.io/github/license/Ameiro-sudo/IReckon?style=for-the-badge" alt="License">
  <img src="https://img.shields.io/github/last-commit/Ameiro-sudo/IReckon?style=for-the-badge" alt="Last Commit">
  <img src="https://img.shields.io/badge/%E7%8A%B6%E6%80%81-Beta-yellow?style=for-the-badge" alt="Status">
</p>

<h1 style="text-align:center">IReckon — 多智能体自主编程系统</h1>
<p style="text-align:center"><em>I think it can work</em></p>

<p style="text-align:center">
  <a href="docs/README_EN.md">English</a> · <a href="docs/BUILD_APK.md">构建 APK</a>
</p>

---

## 概述

**IReckon** 是一个生产级的多智能体 AI 系统，能够将自然语言需求自主转化为完整、经过审查、可交付的软件产物。系统编排一支专业 AI 智能体团队，覆盖标准软件开发生命周期（规划 → 编码 → 审查 → 修订 → 交付），执行过程无需人工干预。

系统基于 **LangGraph 状态机**构建，支持条件路由、循环检测与自动模型升级，在安全沙箱环境中处理完整的软件开发流水线。

---

## 系统架构

```mermaid
graph TB
    subgraph Frontend["Vue 3 前端 (端口 3000)"]
        UI[毛玻璃 UI]
        WS[WebSocket 客户端]
        RT[实时仪表盘]
    end

    subgraph Backend["FastAPI 后端 (端口 8000)"]
        API[REST API 层]
        WSS[WebSocket 服务]
        CFG[配置管理<br/>YAML + 热重载]
    end

    subgraph Engine["工作流引擎 — LangGraph 状态机"]
        direction TB
        PL[规划] --> EX[执行]
        EX --> RV[审查]
        RV -->|通过| DV[交付]
        RV -->|修订| RS[修订]
        RS --> EX
        RV -->|失败| EH[错误处理]
        EH --> END[结束]
        DV --> END
    end

    subgraph Agents["AI 智能体团队"]
        SCH[调度员]
        EXE[执行者]
        REV[审查员<br/>正确性 + 效率]
        DEL[交付员]
        CRE[创意官]
        LRN[学习者]
        TLM[工具管理员]
    end

    subgraph Infrastructure["基础设施层"]
        LLM[LLM 能力池<br/>litellm + DeepSeek V4]
        HARN[DeepSeek Harness<br/>dsh 执行引擎]
        VDB[(ChromaDB<br/>向量数据库)]
        SDB[(SQLite<br/>关系数据库)]
        SEC[安全套件<br/>Bandit + semgrep + udocker]
        KB[知识库<br/>文件存储]
    end

    UI -->|HTTP/WS| API
    UI -->|WS| WSS
    WSS --> RT
    API --> CFG
    API --> Engine
    Engine -->|任务路由| SCH
    SCH --> EXE
    EXE -->|代码| REV
    REV --> DEL
    CRE -->|设计| EXE
    LRN -->|趋势学习| KB
    TLM -->|工具| EXE
    EXE -->|委托| HARN
    Agents -->|LLM 调用| LLM
    Engine --> VDB
    Engine --> SDB
    Engine --> SEC
    Engine --> KB
```

### 智能体角色

| 角色 | 职责 |
|------|------|
| **调度员 (Scheduler)** | 将需求拆解为子任务，为每个阶段选择最优智能体 |
| **执行者 (Executor)** | 编写、修补、调试和重构代码 — 核心生产力 |
| **审查员 (Reviewer)** | 双流水线审查：正确性检查 + 架构/效率分析 |
| **交付员 (Deliverer)** | 打包产物，生成交付说明，归档输出 |
| **创意官 (Creative)** | 头脑风暴解决方案，输出技术设计方案 |
| **学习者 (Learner)** | 空闲时学习：爬取 GitHub Trending，提取开源模式 |
| **工具管理员 (Tool Manager)** | 管理工具注册表，按需组装自定义工具流水线 |

### 工作流状态

```
planning ──▶ execute ──▶ review ──┐
                ▲            │     │
                │      ┌─────┘     │
                │      ▼           ▼
                └── revise     deliver ──▶ END

                fail ──▶ handle_error ──▶ END
```

---

## 功能特性

### 核心引擎
- **多智能体编排** — 7 个专业智能体，带角色特定提示词和工具访问权限
- **LangGraph 状态机** — 带条件路由、子图和并行执行的正式 DAG
- **双流水线审查** — 正确性（功能）+ 效率（架构）两道关卡
- **自适应模型升级** — 修订失败自动提升 LLM 等级（flash → pro）
- **循环检测** — 相似度阈值 + 最大轮次限制，防止死循环
- **任务快照与恢复** — 完整状态持久化，支持暂停/恢复/崩溃恢复

### DeepSeek 集成
- **DeepSeek V4 原生支持** — 内置 `deepseek-v4-flash` / `deepseek-v4-pro` 实例，自动启用 thinking mode 与 reasoning_effort
- **DeepSeek Harness (dsh) 执行引擎** — 双通道：Python SDK + headless CLI（`npx @deepseek-ai/dsh`）自动降级
- **独立工作区隔离** — 每个任务在 `data/harness/workspaces/<session_id>` 独立沙箱运行，复用 session_id 可延续持久 Bash 会话
- **dsh_task 内置工具** — 任一智能体可委托复杂重构/调试任务给 DeepSeek Harness
- **Executor 可选路径** — 任务带 `use_harness: true` 时走 dsh 执行，产物自动汇回流水线

### LLM 与 AI 基础设施
- **模型无关** — 通过 litellm 支持 100+ 模型（OpenAI, Anthropic, Google, Azure, Ollama, vLLM 等）
- **智能能力池** — 多端点管理、健康检查、熔断器、冷却机制、自动故障转移
- **流式 + 降级** — 自动流式降级、指数退避重试、每端点速率限制
- **成本追踪** — 每任务 token 核算、预算强制执行、月度配额告警

### 安全体系
- **多层命令过滤** — L1 自动执行 / L2 共识投票 / L3 严格拦截
- **静态代码扫描** — 集成 Bandit + semgrep 漏洞检测
- **沙箱执行** — udocker 容器隔离，带资源限制（CPU/内存/网络）
- **供应链防火墙** — pip/npm 包黑名单，依赖来源验证
- **挖矿检测** — 进程命令行模式匹配，运行时异常检测

### 前端
- **极简 SaaS 设计系统** — 克制的边框/阴影、Indigo 强调色、深浅双主题，Linear/Notion 质感
- **实时 WebSocket 流** — 任务进度、日志和消息实时推送（心跳保活 + 自动重连）
- **Markdown 消息渲染** — marked + DOMPurify（XSS 过滤）+ highlight.js 代码高亮
- **8 个页面** — 聊天 / 任务表格 / 仪表盘 / 系统日志 / 交付产物 / AI 实例 / 自我进化 / 设置
- **多视觉主题** — catgirl / programmer 主题，深浅色模式
- **响应式布局** — 桌面/平板/移动端自适应

### DevOps
- **配置热重载** — YAML 修改通过 watchdog 实时生效
- **空闲自学习** — 无任务时自动爬取 GitHub Trending
- **自更新系统** — 分析 → 修改 → PR 推送自动化循环
- **Docker 部署** — 支持容器化一键部署
- **Windows 打包** — PyInstaller 构建 exe（见 `scripts/build_exe.bat`）

---

## 快速开始

### 环境要求
- Python 3.10+
- LLM 端点（默认: `http://localhost:3003/v1` — FreeLLM API，可自行配置）
- Node.js 18+（前端开发/构建用）

### 安装

```bash
git clone https://github.com/Ameiro-sudo/IReckon.git
cd IReckon
pip install -r requirements.txt
# 开发/测试额外依赖：
pip install -r requirements-dev.txt
```

### 配置 LLM

```bash
# DeepSeek V4 官方 API（能力池内置 deepseek-v4-flash / deepseek-v4-pro 实例）
export DEEPSEEK_API_KEY=sk-xxx

# 可选：FreeLLM API（config.yaml 默认实例）
export FREELMAPI_KEY=xxx

# 或自定义：在 config/config.yaml 的 ai_pool.instances 中增改端点
```

能力池配置说明见 `config/config.yaml` 的 `ai_pool` 段；dsh 执行引擎见 `harness` 段（mode: auto 优先 SDK、缺失时降级 CLI）。

### 启动

```bash
# 一键启动（自动构建/托管前端，端口 8000）
python main.py

# 生产模式（FastAPI 托管构建后的前端）
./scripts/run.sh

# 手动启动
python -m uvicorn app.web.api:app --host 0.0.0.0 --port 8000
cd frontend && npm run dev

# Docker 部署（多阶段构建：Node 构建前端 + Python 后端）
cd deploy && docker compose up -d --build
```

> 提示：`python main.py` 会检测 `frontend/dist`，不存在时自动启动 Vite dev server（:3000）并安装前端依赖；也可设置 `IRECKON_DEV_FRONTEND=1` 强制开发模式。

### 访问地址

| 服务 | 地址 |
|------|------|
| 后端 API | `http://127.0.0.1:8000` |
| 交互式文档 | `http://127.0.0.1:8000/docs` |
| 前端 UI（开发模式） | `http://127.0.0.1:3000` |
| 健康检查 | `http://127.0.0.1:8000/api/health` |

---

## API 参考

### 任务

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tasks` | 创建新任务 |
| GET | `/api/tasks` | 获取任务列表（`?limit&offset&status` 分页筛选） |
| GET | `/api/tasks/{id}` | 获取任务详情（含计划、看板、Token 用量） |
| GET | `/api/tasks/{id}/board` | 获取任务看板状态 |
| GET | `/api/tasks/{id}/artifacts` | 列出交付产物 |
| GET | `/api/tasks/{id}/artifact?path=` | 读取单个产物文件内容（路径穿越防护） |
| GET | `/api/tasks/{id}/download` | 下载交付产物 (zip) |
| POST | `/api/tasks/{id}/cancel` | 取消运行中的任务 |
| POST | `/api/tasks/{id}/resume` | 恢复暂停/失败的任务 |
| DELETE | `/api/tasks/{id}` | 删除任务（级联清理消息/看板/快照） |
| GET | `/api/tasks/{id}/messages` | 获取任务消息 |
| POST | `/api/tasks/{id}/messages` | 发送消息到任务 |

### AI 实例与配置

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/ai-instances` | 列出 AI 端点 |
| POST | `/api/ai-instances` | 注册新 AI 端点 |
| PUT | `/api/ai-instances/{id}` | 更新 AI 端点 |
| DELETE | `/api/ai-instances/{id}` | 删除 AI 端点 |
| POST | `/api/ai-instances/{id}/test` | 测试端点连通性 |
| GET | `/api/capabilities` | 能力池状态 |
| GET | `/api/config` | 获取当前配置 |
| POST | `/api/config/update` | 运行时更新配置（原子写入） |
| GET | `/api/themes` | 获取 UI 主题列表 |

### 系统

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/api/health` | 健康检查（含版本/更新/连接数/运行时长） |
| GET | `/api/stats` | 仪表盘统计（任务状态分布/AI 实例/用量） |
| GET | `/api/usage` | Token/成本用量汇总 |
| GET | `/api/logs` | 最近系统日志 |
| POST | `/api/uploads` | 上传文件（任务附件） |
| POST | `/api/self-improve` | 触发自我进化分析 |
| POST | `/api/self-improve/push` | 推送自我进化分支 |
| GET | `/api/update/check` | 检查新版本 |
| POST | `/api/update/apply` | 应用更新 |
| WS | `/ws/{task_id}` | 按任务的实时事件流 |
| WS | `/ws` | 全局事件流（日志/消息） |

---

## 技术栈

| 层 | 技术 |
|----|------|
| 语言 | Python 3.10+ (asyncio) |
| LLM 接口 | litellm（100+ 模型）+ DeepSeek V4 原生 |
| 执行引擎 | DeepSeek Harness (dsh) — SDK / headless CLI |
| 工作流引擎 | LangGraph |
| 向量数据库 | ChromaDB |
| 关系数据库 | SQLite (aiosqlite) |
| 后端框架 | FastAPI + WebSocket |
| 前端框架 | Vue 3 + Vite + Pinia |
| 配置管理 | YAML + 环境变量 + watchdog |
| 日志系统 | loguru |
| 安全扫描 | Bandit, semgrep |
| 容器沙箱 | udocker |
| 数据加密 | cryptography (Fernet) |
| 模板引擎 | Jinja2 |
| CI/CD | GitHub Actions |
| 打包工具 | PyInstaller, Buildozer |

---

## 项目结构

```
IReckon/
├── main.py                       # 应用入口（后端 + 前端自动托管）
├── pyproject.toml                # 项目元数据 + 工具链配置（ruff/mypy/bandit/coverage）
├── requirements.txt              # 运行依赖
├── requirements-dev.txt          # 开发依赖（pytest/ruff/mypy 等）
├── buildozer.spec                # Buildozer (Android/Kivy) 打包配置
├── .editorconfig                 # 跨编辑器编码规范
├── .env.example                  # 环境变量示例（API Keys）
│
├── app/                          # 后端包
│   ├── py.typed                  # PEP 561 类型标注标记
│   ├── agents/                   # AI 智能体（scheduler/executor/reviewer/deliverer/creative/learner/tool_manager）
│   ├── core/                     # 基础设施（配置/数据库/日志/更新）
│   ├── engine/                   # 工作流引擎（LangGraph 状态机/看板/会议室/自我进化）
│   ├── harness/                  # DeepSeek Harness (dsh) 集成
│   ├── llm/                      # LLM 基础设施（能力池/客户端）
│   ├── knowledge/                # 知识管理
│   ├── security/                 # 安全子系统（命令过滤/扫描/沙箱）
│   ├── tools/                    # 工具系统
│   ├── utils/                    # 通用工具
│   └── web/                      # Web 层
│       ├── api.py                # FastAPI 应用工厂（路由挂载 + SPA 托管）
│       ├── push.py               # WebSocket 推送（心跳保活）
│       └── routers/              # 按领域拆分的路由（tasks/instances/config/system/uploads）
│
├── frontend/                     # Vue 3 前端（Vite + Pinia + marked/highlight.js）
│   ├── src/
│   │   ├── views/                # 8 个页面（聊天/任务/仪表盘/日志/产物/AI实例/自我进化/设置）
│   │   ├── components/           # 组件（NewTaskModal/ArtifactBrowser/LogViewer/TaskBoardPanel/...）
│   │   ├── stores/               # Pinia 状态（任务/看板/实时消息/轮询）
│   │   └── utils/markdown.js     # Markdown 渲染 + XSS 过滤 + 代码高亮
│   └── dist/                     # 构建产物（FastAPI 托管）
│
├── config/                       # 配置（config.yaml / prompts / themes / harness）
├── scripts/                      # 工具脚本（run.sh 启动器 / build_exe 打包 / 测试）
├── docs/                         # 文档
├── deploy/                       # Docker / Inno Setup 部署
└── data/                         # 运行时数据（db/logs/states/output/harness）
```

---

## 开发指南

```bash
# 安装依赖
pip install -r requirements-dev.txt
cd frontend && npm install

# 代码检查
ruff check app/
mypy app/

# 安全扫描
bandit -r app/
semgrep --config=auto app/

# 格式化
ruff format app/

# 测试
pytest
python scripts/smoke_test.py
python scripts/test_run.py
```

---

## 开源许可

基于 **MIT License** 分发。详见 `LICENSE` 文件。

---

<p style="text-align:center">
  <sub>IReckon Team 用心打造</sub>
</p>