# IReckon — 俺寻思 AI 工厂

> *"俺寻思能行"* — Warhammer 40K Orks

**IReckon** 是一个**多智能体自主编程系统**。输入自然语言需求，AI 团队自动完成规划、编码、审查、修改、交付全流程，无需人工干预。

---

## 快速开始

### 环境要求

- Python 3.10+
- LLM 端点（默认 Ollama `http://localhost:11434` + `qwen2.5:7b`）

### 安装

```bash
git clone https://github.com/ninasukiwww-png/IReckon.git
cd IReckon
pip install -r requirements.txt
```

### 启动

```bash
# 方式一：一键启动（后端 + 前端）
bash run.sh

# 方式二：分别启动
python -m uvicorn app.web.api:app --host 0.0.0.0 --port 8000   # 后端
streamlit run ui/app.py --server.port 8501                       # 前端

# 方式三：启动前检查环境
bash run.sh --check
```

启动后访问：
- 后端 API: `http://localhost:8000` — Swagger 文档 `/docs`
- 前端 UI: `http://localhost:8501` — Streamlit 界面

### 使用流程

1. 打开前端 UI，点击 **New Task**
2. 输入自然语言需求，例如 `"创建一个 Flask TODO 应用，支持增删改查"`
3. AI 团队自动执行：规划 → 编码 → 审查 → 修改 → 交付
4. 在 Chat / Dashboard 页面实时查看进度
5. 成品输出到 `data/outputs/{task_id}/`

---

## 架构

```
┌──────────────────────────────────────────────────────────┐
│                    Streamlit UI (port 8501)               │
│   Chat / Dashboard / Config Panel / Theme Selector        │
└────────────────────────┬─────────────────────────────────┘
                         │ HTTP / WebSocket
┌────────────────────────▼─────────────────────────────────┐
│                   FastAPI Backend (port 8000)              │
│   REST API (/api/tasks, /api/ai-instances, /api/config)   │
│   WebSocket (/ws/{task_id})                               │
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│                    Workflow Engine                         │
│   ┌──────────┐   ┌──────────┐   ┌──────────┐              │
│   │ Planning │──▶│ Execute  │──▶│  Review  │              │
│   └──────────┘   └──────────┘   └────┬─────┘              │
│         ▲                            │ pass/fail          │
│         │                   ┌────────▼────────┐            │
│         └───────────────────│  Revise / Deliver│            │
│                             └─────────────────┘            │
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│                    AI Agent Team                           │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐     │
│  │Scheduler │ │ Executor │ │ Reviewer │ │Deliverer │     │
│  └──────────┘ └──────────┘ └──────────┘ └──────────┘     │
│  ┌──────────┐ ┌──────────┐ ┌──────────┐                   │
│  │ Creative │ │ Learner  │ │Tool Mgr  │                   │
│  └──────────┘ └──────────┘ └──────────┘                   │
└────────────────────────┬─────────────────────────────────┘
                         │
┌────────────────────────▼─────────────────────────────────┐
│                  Infrastructure                            │
│  LLM Pool (litellm) │ ChromaDB │ SQLite │ Security Suite   │
└──────────────────────────────────────────────────────────┘
```

---

## AI 角色

| 角色 | 职责 |
|------|------|
| **Scheduler** (调度员) | 将需求拆解为可执行的阶段计划，为每个阶段招募 AI 成员 |
| **Executor** (开发者) | 编写代码、应用 diff 补丁、调试修复 |
| **Reviewer** (审查员) | 正确性审查 + 效率/架构审查，双重把关 |
| **Deliverer** (交付员) | 打包产物、生成 READY.txt、归档输出 |
| **Creative** (创意官) | 头脑风暴、方案设计、技术选型建议 |
| **Learner** (学习者) | 空闲时爬取 GitHub Trending，学习开源模式 |
| **Tool Manager** (工具管理) | 管理工具零件库，按需调用内置工具 |

## 工作流

IReckon 使用 **LangGraph** 构建有向状态图：

```
planning ──▶ execute ──▶ review ──┐
                ▲            │     │
                │      ┌─────┘     │
                │      ▼           ▼
                └── revise     deliver ──▶ END
                                   
                fail ──▶ handle_error ──▶ END
```

- **review_router**: 审查通过 → 交付；需修改 → 修订；失败 → 错误处理
- **revise_router**: 状态为 executing → 继续执行；否则 → 重新审查
- 超过 3 轮修订自动升级到高性能模型

---

## 特性

### 核心
- **多角色 AI 团队** — 7 种专业角色协同工作
- **全自动交付** — 提需求 → 出成品，零人工介入
- **LangGraph 状态机** — 带条件路由的正式工作流
- **双重审查** — 正确性 + 效率架构双重把关
- **智能重试** — 审查失败自动修订，超过阈值自动换模型

### LLM 与 AI
- **模型无关** — 通过 litellm 支持 100+ 模型（Ollama / OpenAI / Anthropic / Google / Azure 等）
- **能力池** — 多端点管理、自动故障转移、健康检测、冷却机制
- **流式/非流式** — 自动降级、指数退避重试

### 安全
- **代码扫描** — 集成 Bandit / semgrep
- **命令分级** — L1 自动执行 / L2 投票阈值 / L3 拦截
- **沙箱执行** — udocker 容器隔离
- **供应链防火墙** — pip / npm 黑名单过滤
- **挖矿检测** — 进程命令行匹配

### 用户体验
- **实时推送** — WebSocket 推送进度、日志、消息
- **可定制主题** — catgirl / programmer 角色扮演主题
- **任务快照** — 支持暂停 / 恢复
- **配置热重载** — YAML 修改自动生效
- **空闲学习** — 无任务时自动学习 GitHub Trending

---

## 配置

所有配置集中在 `config/config.yaml`，支持环境变量引用 `${VAR:-default}` 和热重载。

### 核心配置项

```yaml
server:
  host: 0.0.0.0       # 服务监听地址
  port: 8000            # 服务端口
  log_level: INFO       # 日志级别

ai_pool:
  default_model: qwen2.5:7b   # 默认 LLM 模型
  instances:                    # AI 端点列表
    - id: local-ollama-qwen
      model: ollama/qwen2.5:7b
      endpoint: http://localhost:11434
      tags: [general, cheap, fast, python]

ui:
  theme: catgirl          # UI 主题（catgirl / programmer / raw）
  default_view: styled    # 默认视图模式

task_defaults:
  max_review_rounds: 5         # 最大审查轮次
  loop_detection_max_rounds: 5 # 循环检测阈值
```

可在前端 UI 的 Config Panel 中实时修改，或通过 API：

```bash
curl -X POST http://localhost:8000/api/config/update \
  -H "Content-Type: application/json" \
  -d '{"updates": {"ui.theme": "programmer"}}'
```

---

## API 文档

| 方法 | 路径 | 说明 |
|------|------|------|
| POST | `/api/tasks` | 创建新任务 |
| GET | `/api/tasks` | 列出所有任务 |
| GET | `/api/tasks/{id}` | 获取任务详情 |
| POST | `/api/tasks/{id}/cancel` | 取消任务 |
| POST | `/api/tasks/{id}/resume` | 恢复任务 |
| GET | `/api/tasks/{id}/messages` | 获取任务消息 |
| POST | `/api/tasks/{id}/messages` | 发送消息 |
| GET | `/api/ai-instances` | 列出 AI 端点 |
| POST | `/api/ai-instances` | 创建 AI 端点 |
| PUT | `/api/ai-instances/{id}` | 更新 AI 端点 |
| DELETE | `/api/ai-instances/{id}` | 删除 AI 端点 |
| POST | `/api/ai-instances/{id}/test` | 测试 AI 端点 |
| GET | `/api/config` | 获取配置 |
| POST | `/api/config/update` | 更新配置 |
| GET | `/api/themes` | 获取主题列表 |
| GET | `/api/health` | 健康检查 |
| WS | `/ws/{task_id}` | 任务 WebSocket |
| WS | `/ws` | 全局 WebSocket |

---

## 技术栈

| 模块 | 技术 |
|------|------|
| 语言 | Python 3.10+ (asyncio) |
| LLM 接口 | litellm（100+ 模型） |
| 工作流 | LangGraph |
| 向量数据库 | ChromaDB |
| 关系数据库 | SQLite (aiosqlite) |
| 后端框架 | FastAPI + WebSocket |
| 前端框架 | Streamlit |
| 配置管理 | YAML + 环境变量 + watchdog 热重载 |
| 日志 | loguru |
| 安全扫描 | Bandit, semgrep |
| 沙箱 | udocker |
| 加密 | cryptography (Fernet) |
| 模板引擎 | Jinja2 |

---

## 开发

```bash
# 环境检查
python scripts/preflight.sh

# 功能测试（创建 Hello World 任务）
python scripts/test_run.py

# 代码扫描
bandit -r app/
semgrep --config=auto app/
```

### 环境变量

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `IRECKON_HOME` | `.` | 项目根目录 |
| `IRECKON_API_HOST` | `localhost` | API 主机地址 |
| `IRECKON_API_PORT` | `8000` | API 端口 |
| `IRECKON_API_TIMEOUT` | `10` | API 请求超时（秒） |

---

## 目录结构

```
IReckon/
├── main.py                    # 应用入口
├── run.sh                     # 启动脚本
├── requirements.txt           # 依赖
├── pyproject.toml             # 项目元数据
│
├── app/                       # 后端包
│   ├── agents/                # AI 角色实现
│   │   ├── base.py            #   基类
│   │   ├── scheduler.py       #   调度员
│   │   ├── executor.py        #   开发者（含 diff 补丁）
│   │   ├── reviewer.py        #   审查员
│   │   ├── deliverer.py       #   交付员
│   │   ├── creative.py        #   创意官
│   │   ├── learner.py         #   学习者
│   │   ├── tool_manager.py    #   工具管理
│   │   └── content_filter.py  #   内容安全过滤
│   ├── core/                  # 基础设施
│   │   ├── config.py          #   配置管理（热重载）
│   │   ├── database.py        #   SQLite + Fernet 加密
│   │   ├── logger.py          #   loguru 日志
│   │   └── state.py           #   任务状态快照
│   ├── engine/                # 工作流引擎
│   │   ├── machine.py         #   LangGraph 状态机
│   │   ├── tasks.py           #   任务生命周期
│   │   ├── room.py            #   会议室（多 agent 通信）
│   │   ├── board.py           #   Kanban 看板
│   │   ├── registry.py        #   角色注册表
│   │   ├── detector.py        #   循环检测
│   │   ├── cost.py            #   成本追踪
│   │   ├── learner.py         #   空闲学习循环
│   │   └── style.py           #   UI 主题引擎
│   ├── llm/                   # LLM 层
│   │   ├── client.py          #   客户端（重试/回退/流式）
│   │   └── pool.py            #   能力池（端点管理）
│   ├── knowledge/             # 知识库
│   │   ├── vector.py          #   ChromaDB 向量库
│   │   └── files.py           #   文件知识库
│   ├── security/              # 安全子系统
│   │   ├── scanner.py         #   代码扫描
│   │   ├── filter.py          #   命令分级过滤
│   │   ├── sandbox.py         #   udocker 沙箱
│   │   ├── mining.py          #   挖矿检测
│   │   └── supply.py          #   供应链防火墙
│   ├── tools/                 # 工具系统
│   │   ├── registry.py        #   工具注册
│   │   ├── library.py         #   零件库
│   │   ├── assembler.py       #   工具组装器
│   │   └── builtin/           #   内置工具
│   └── web/                   # Web 层
│       ├── api.py             #   FastAPI 路由
│       ├── ws.py              #   WebSocket 处理
│       └── push.py            #   WebSocket 推送
│
├── ui/                        # 前端包
│   ├── app.py                 #   Streamlit 主入口
│   ├── components/            #   UI 组件
│   │   ├── chat.py            #     聊天视图
│   │   ├── dashboard.py       #     仪表盘
│   │   ├── config_panel.py    #     配置面板
│   │   └── style.py           #     CSS 样式注入
│   └── utils/                 #   前端工具
│       ├── api.py             #     HTTP 客户端
│       └── ws.py              #     WebSocket 客户端
│
├── config/                    # 配置 & 模板
│   ├── config.yaml            #   主配置
│   ├── prompts/               #   Jinja2 提示词模板
│   └── themes/                #   角色主题（catgirl / programmer）
│
├── scripts/                   # 工具脚本
│   ├── preflight.sh           #   环境预检
│   └── test_run.py            #   功能测试
│
├── .streamlit/                # Streamlit 配置
│   └── config.toml            #   主题 / 服务配置
│
└── data/                      # 运行时数据（gitignored）
    ├── .key                   #   加密密钥
    ├── chromadb/              #   向量数据库
    ├── db/                    #   SQLite 数据库
    ├── logs/                  #   日志文件
    ├── outputs/               #   交付产物
    ├── states/                #   任务快照
    └── knowledge_base/        #   知识文件
```

---

## 常见问题

**Q: 启动后 API 返回 502？**  
A: 确认 LLM 端点已启动并可访问。默认使用 `http://localhost:11434`（Ollama）。

**Q: 如何更换 AI 模型？**  
A: 在 UI 的 Config Panel 中添加 AI Instance，或修改 `config/config.yaml` 的 `ai_pool.instances`。

**Q: 任务卡死怎么办？**  
A: 可在 UI 中撤销任务，或通过 API `POST /api/tasks/{id}/cancel` 取消后恢复。

**Q: 如何在 Windows 上运行？**  
A: 使用 `python main.py` 启动后端，另一个终端运行 `streamlit run ui/app.py`。

**Q: 如何调试 Agent 输出？**  
A: 设置 `system.log_level: DEBUG` 查看详细日志，或在 UI 的 Chat 页面查看 L2 层消息。

---

## 许可

MIT License — 详见项目 LICENSE 文件。