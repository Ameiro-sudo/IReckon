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