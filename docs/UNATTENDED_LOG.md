# 无人值守冲刺进展日志

> 分支：r2-review-fixes（基于 master @ a45c5bb，未 push）
> 环境：Windows / Python 3.13 venv / Node 20

## 第 1 轮（2026-08-21）

### 已完成

| 提交 | 内容 | 验证方式 |
| --- | --- | --- |
| 719bc55 | R2 审查 20 项修复检查点入库（此前 45 文件未提交裸奔在工作区） | pytest 196 全绿后提交 |
| 9dca3a2 | ruff 卫生清零（11 处 F841/F401） | ruff check app/main/tests 全绿 |
| 82a6704 | 测试顺序污染根因修复：self_improve 在 config patch 态触发真实 find_best_match → 单例池缓存"空池+60s 节流"拖垮后续 agents 测试；conftest 加 autouse 重置 fixture | 最小复现对由必挂转绿 |
| 3a775c1 | mypy 崩溃修复：numpy 新 stubs 的 PEP 695 语法与 python_version=3.10 冲突，per-module override 对解析期错误无效（实测 unused section），改全局 follow_imports=skip | mypy app/ 72 文件 0 错误 |
| ea3a78c | BUILD_APK.md 可行性现实化：三方案标注阻断点，明确 Windows EXE 主渠道 | — |
| 1941e45 | **EXE 打包 bug**：register_builtin_tools 相对 cwd 解析路径，打包后内置工具全部静默失效；改为锚定 `__file__` | 重打 EXE 实测 7 工具全部注册 |
| eb9ba2e | 补 P2-11 盲区：uploads 7 项 + push.ConnectionManager 7 项 | 新增 14 测试全绿 |

### 端到端实测记录

- 后端源码启动：`/api/health` 无 token 降级 `{"status":"ok"}`、带 token 返回完整状态（R2-P2-6 实证）
- 鉴权矩阵：无 token 写端点 401 / 合法更新 200 / 深层键注入 `ui.a.b` 403 / 白名单外键 403（R2-P1-3 实证）
- 前端 `npm run build`：成功（vite 5.4.x，重构无断链）
- PyInstaller EXE：构建成功（~102s）；frozen 模式随机端口为设计行为（run_embedded）

### 后端 R2 抽查结论

17 项声称的后端修复逐一核实**全部属实**，含若干高质量实现（cipher 双检锁 chmod 移锁外、信号 task 集合持引用防 GC、fail-closed 读不到策略文件即拒绝执行）。

### 待办（下轮）

- [ ] bocchi-mod：Modrinth/CurseForge 发布需用户注册 mod_id + 配 secrets，已调研现有 CI 已完整，等用户决策
- [ ] waterfall.py CLI 化收编入仓
- [ ] inecraft-Server-Status 后端接口真实化方案
- [ ] 考虑 r2-review-fixes 是否合并回 master（建议用户回来后 review + merge）
- [ ] 已知环境坑：PowerShell 执行策略禁 npm.ps1（用 npm.cmd）；write 工具创建新文件 EISDIR（用 pwsh 兜底）；子代理基础设施本会话不可用（4 连败）
## 第 1 轮补充（同日晚）

- [x] waterfall.py 收编 → D:\project\waterfall\ 独立仓库(root 74533d7)：README+requirements+.gitignore，修复输出父目录自动创建，27 图冒烟测试通过；原散落文件已删除
- [x] inecraft-Server-Status 后端调研 → backend-proposal 分支(9244883) docs/BACKEND_PROPOSAL.md：核心结论"缺的是采样器不是后端"，方案 A(极简 JSON 存储+定时采样器)为推荐，含 API 契约与决策点
- [x] .notify 企微通知通道接入：notify.py 计数 bug 修复(stem→name)，双监听器实例事故清理并重启单实例，通道自检 SENT(1 target)
## 决策轮（用户全权委托后）

- [x] **IReckon r2-review-fixes 已合并回 master**(--no-ff 06796df)，master+分支均已 push 远端备份；合并前处理了一起编辑器陈旧缓冲区回写事故(5个前端文件被旧内容覆盖，已备份补丁至 D:\project\stale-editor-backup.patch 后丢弃)
- [x] bocchi-mod Modrinth/CurseForge 轨道**取消**(用户决定：不上第三方平台)
- [x] inecraft 方案A代码交付(backend-proposal 4239fec)：sampler.py 零依赖采样器实测通过、status.js REMOTE_HISTORY_BASE 注水层、DEPLOY.md；**部署等 VPS 恢复**
## 自主轮 1（合并后）

- [x] **GitHub CI 外部验证**：master 06796df 推送后 CI success（顺带发现此前 6cb289d 的 CI 曾 failure，a45c5bb 起恢复）
- [x] inecraft status.js 通过 node --check，本地 8801 预览站正常响应
- [x] 覆盖率摸底并补盲区：content_filter 35%→100%、tool_manager 19%→67%（+16 测试），04f1b17 已推远端
- [x] IReckon.spec(PyInstaller 产物)入 gitignore
- [ ] 下轮候选：engine/tasks.py(37%)、web/routers/system.py(31%) 补测；learner 循环逻辑审查
## 自主轮 2

- [x] engine/tasks.py 37%→67%：任务创建/上传批次白名单(_UPLOAD_ID_RE)/_ingest_uploads 穿越防护/需求拼装(超限与非法路径跳过)/_launch 异常→FAILED、取消+事件→PAUSED 语义，+13 测试
- [x] web/routers/system.py 31%→67%：auth/check 三态(免鉴权布尔语义/回环信任/错 token)、stats 形状、logs 解析与 level 过滤，+5 测试
- [x] 全量 pytest 保持绿，63f4f84 已推远端
## 自主轮 3

- [x] agents/learner 14%→80% + engine/learner 21%→53%（8c222e9）：工具建议解析全路径、Trending 提取抽纯函数 _extract_repo_candidates、空闲触发判定抽 _should_trigger/_daily_reset_if_needed（行为不变的纯重构）
- [x] knowledge/files.py 33%→84%（类型校验参数化/2MB限制/落盘+DB+向量库打桩三重断言）
- [x] 全量 pytest 保持绿；累计自主轮新增测试 196→253
## 自主轮 4

- [x] security/mining.py 50%→95%：8正4负参数化检测用例、假psutil进程扫描命中、psutil缺失降级
- [x] knowledge/vector.py 39%→82%：绕过 chromadb 构造直测 add 委托/search 映射/n_results 钳制/可选字段容错
- [x] 全量 pytest 绿；累计自主轮测试 196→268
## 自主轮 5

- [x] core/state.py 46%→84% + engine/registry.py 43%→58%（+14 测试）
- [x] 全量 pytest 绿；累计自主轮测试 196→282
## 自主轮 6

- [x] web/routers/tasks.py 48%→81%（+12 API级测试）：产物穿越拒绝矩阵、zip下载子目录打包、删除往返用 start_task 桩保证确定性（LLM 重试退避会让运行态窗口长达 30s+）
- [x] 全量 pytest 绿；累计自主轮测试 196→285