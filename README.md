# IReckon - 俺寻思 AI 工厂

> *"俺寻思能行" —  Warhammer 40K Orks*

**IReckon** 是一个**多智能体自主编程系统**，输入自然语言需求，自动规划、编码、审查、修改、交付，全程无需人工干预。

## 项目结构

```
IReckon/
├── main.py                  # 入口
├── app/                     # 后端核心
│   ├── agents/              # AI 角色（调度/执行/审查/创意/交付...）
│   ├── core/                # 配置/数据库/日志/状态管理
│   ├── engine/              # LangGraph 状态机 & 任务管理
│   ├── knowledge/           # ChromaDB 向量知识库
│   ├── llm/                 # LLM 客户端 & 能力池
│   ├── security/            # 安全扫描/沙箱/供应链防火墙
│   ├── tools/               # 内置工具 & 零件库
│   └── web/                 # FastAPI 后端 + WebSocket
├── ui/                      # Streamlit 前端
├── config/                  # 配置 & 提示词模板 & 主题
├── data/                    # 运行时数据（日志/DB/快照/输出）
└── scripts/                 # 辅助脚本
```

## 特性

- **多角色 AI 团队** — Scheduler / Executor / Reviewer / Creative / Deliverer / Learner 等
- **全自动交付** — 提需求 → 出成品
- **LangGraph 工作流** — 带条件路由的正式状态图（规划→执行→审查→修改→交付）
- **实时审查** — 正确性 + 效率双重审查机制
- **空闲学习** — 无任务时自动爬取 GitHub Trending 学习
- **安全子系统** — 代码扫描/命令分级/沙箱执行/供应链防火墙/挖矿检测
- **Web 界面** — Streamlit + WebSocket 实时推送
- **LLM 无关** — 通过 litellm 支持 100+ 模型（Ollama / OpenAI / Anthropic 等）
- **恢复机制** — 任务快照支持暂停/恢复

## 快速开始

### 环境要求

- Python 3.10+
- LLM 端点（默认 Ollama `http://localhost:11434` + `qwen2.5:7b`）

### 安装与运行

```bash
pip install -r requirements.txt
bash run.sh
```

启动后：
- 后端 API: `http://localhost:8000`
- 前端 UI:  `http://localhost:8501`

### 使用流程

1. 打开 `http://localhost:8501`
2. 点击 **New Task**，输入需求（如 "创建一个 Flask TODO 应用"）
3. 系统自动调度 AI 团队 → 执行 → 审查 → 修改 → 交付
4. 在 Chat / Dashboard 页面实时查看进度
5. 成品输出到 `data/outputs/{task_id}/`

## 技术栈

| 模块 | 技术 |
|------|------|
| 语言 | Python 3.10+ (asyncio) |
| LLM | litellm (100+ 模型统一接口) |
| 工作流 | LangGraph |
| 向量库 | ChromaDB |
| 后端 | FastAPI + WebSocket |
| 前端 | Streamlit |
| 数据库 | SQLite (aiosqlite) |
| 配置 | YAML + 环境变量 + 热重载 |
| 日志 | loguru |
| 安全 | Bandit, semgrep, udocker |
