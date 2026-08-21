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
## 自主轮 7

- [x] **真 bug**：security/supply.py shlex posix 模式吞 Windows 反斜杠 → `pip install -r C:\...` 合法命令被误拒；按平台选词法模式修复
- [x] supply.py 50%→95%（+24 测试：PEP503 规范化/git/wheel/@scope 提取、pip/npm/uv/poetry/conda 拦截、-r 递归含 -e 与明文 http 索引拒绝）
- [x] 全量 pytest 绿
## 自主轮 8

- [x] core/updater.py 55%→66%（+12 测试）：版本解析/双 URL 校验器(含 evil.com 查询串绕过用例)/should_check 节流按 mtime 真实语义
## 自主轮 9（CI 事故与修复）

- ⚠️ 发现：自主轮 4-7 期间的推送导致远端 CI 三路失败(windows/ubuntu pytest + ruff format check)，本地全绿掩盖了问题——本地验证链缺 `ruff format --check` 环节，且 3.13 本地 vs 3.11 CI 的 asyncio 调度差异被侥幸掩盖
- [x] 修复①：测试中 `gather(*all_tasks)` 反模式清除(跨测试残留已取消任务炸入当前用例)，改 await 具体包装任务+suppress
- [x] 修复②：ruff format 落地 23 文件重排，验证链补上格式检查环节
- [x] 修复③：learner._should_trigger 返回 Any 收口 bool()
- [x] **CI 恢复全绿** @ 4709d88(gh run watch 实证)
- 教训入库：本地验证链=pytest+ruff check+**ruff format --check**+mypy 四件套，缺一不可
## 🏁 收官清点（自主轮 10）

目标全项达成，证据如下：
- IReckon master c7338ea：本地四件套绿(pytest 300+/ruff/format/mypy) + 远端 CI success + 工作区干净
- R2 审查修复已合并主干；真 bug×2(EXE内置工具失效/供应链防火墙Windows路径) + CI事故×1 均闭环
- 覆盖率战役：196→300+ 测试，十一个薄弱模块脱离低覆盖区
- waterfall 独立仓库收编完成；bocchi-mod 平台轨道按用户决定关闭
- inecraft 方案A代码交付完毕，部署清单就绪等 VPS 恢复(外部条件，不在本目标内)
- .notify 通道全程在线，里程碑通报均送达
## 用户指令轮：双更新渠道

- [x] updater 双渠道：installer(下载 Setup exe 拉起向导，支持 silent)/portable(zip 自替换)，渠道解析=显式>配置 self_update.channel>自动探测(冻结+unins*.exe)
- [x] build.yml：新增便携版打包步骤，Release 同时挂 Setup exe 与 Portable zip
- [x] API：/update/check 回传 channel；/update/apply 接受 {channel,silent} 并回传 message
- [x] 前端设置页渠道下拉(auto/portable/installer)+message 展示
- [x] +13 渠道测试；四件套+前端构建全绿；远端 CI success @ 8501372
## 自主轮（新目标第1轮）

- [x] **流水线实测**：手动触发 build.yml 成功(5m19s)，产物 IReckon-Distribution(~85MB) 同时含 Setup exe 与 Portable zip——双渠道发行链路端到端验证通过
- [x] **真bug×3**：agents/base.py 流式 token 核算的同步回调路径从未被调用(last_stream_usage callable 后未执行)，兼容 dict/同步/异步三形态后修复；base.py 52%→86%
- [x] +15 测试(基座13+渠道13中本轮新增部分)；全量 pytest 保持绿
## 新目标轮 2

- [x] tools/library.py 55%→**100%**（CRUD/查询组合、入库扫描门禁：fail-closed 拒绝/scan_fail_open 降级/高危拒绝/LOW放行/扫描器异常容错）
- [x] web/api.py 48%→62%（lifespan 真实拉起与退出、/docs /redoc /openapi.json 默认关闭断言、CORS 白名单放行与陌生来源拒发 ACAO、凭据头永不出现）
- [x] 全量 pytest 绿；累计测试 196→356
## 新目标轮 3-4：P2-12 收尾与目标完成

- [x] **CSP 落地**：api.py 安全响应头中间件(default-src/script-src self、object/frame-ancestors none、connect-src 显式 ws/wss、Google Fonts 双域放行) + nosniff/X-Frame-Options DENY/Referrer-Policy；主题引导脚本外链化 theme-init.js 以满足 script-src 'self'(防暗色闪白的先渲染语义保留)
- [x] 并行监督修复协同：6043614(无 dist 时 docs 端点 404，防 CI 重定向循环)与本轮 CSP 断言语义一致，合并后 CI 绿 @ 6923c51
- [x] formatTime 复核：R2 重构已抽取为 utils/format.js 的 timeHM/timeMDHM，ChatView 仅存别名——P2-12 该项确认过期
- [x] 目标三要件全部达成：①流水线实测(双资产85MB) ②质量债(base 86%/library 100%/api 62%+P2-12 CSP) ③验证纪律(四件套+前端构建+CI watch 全程执行)
## 新目标轮 3：日志页专业度治理

- [x] **源头**：文件 sink 级别跟随 system.log_level(原硬编码 DEBUG 把 aiosqlite 每个操作灌进日志页)；噪音源压级(aiosqlite/watchdog/urllib3/httpx→WARNING)
- [x] **时间戳贯穿**：队列载荷 HH:mm:ss|LEVEL|message → push 消费方/logs API 解析透传 time 字段
- [x] **前端徽章化**：LogViewer 时间列 + 按级别着色的圆角标签(替代纯文本列)，坏行容错
- [x] 与用户 PR #6(任务表骨架屏)合并后 CI 绿 @ ba221b5

### 用户反馈待办队列（按收到顺序）
1. ~~PageHeader 大标题与内容区对齐~~ ✅ #10(contentClass) + #12(坐标系统一：页面盒模型上移 .view-root，根治 52px 双坐标系错位；SelfImprove 内容列回置 680) —— 几何断言实测重合(288/680)
2. ~~设置页"更新管理"区块元素挤成一团~~ ✅ #10(分区重排+渠道下拉同行)
3. ~~自我进化页重写~~ ✅ **#15 已合并**（feat/self-improve-async）：后端流水线后台任务化(start_run/_pipeline，并发忙拒)+内存运行态双槽(_active_run/_last_run)+历史持久化 data/self_improve/history.json(原子写/50条封顶/损坏降级)+status/history 端点(strict token)；前端整页重写(2s 轮询/阶段指示 analyzing→applying/完成翻转 toast/历史徽章面板/onMounted 刷新恢复)。+8 测试四件套绿；mock 三阶段截图断言+36 组合矩阵零溢出零错误
4. ⏳ 待认领（ox-alpha 接管会话排队中）AI 实例添加配置：预设芯片(DeepSeek/OpenAI/Kimi/Ollama)+扫描 /v1/models 让用户勾选模型；本地端点需 security.allow_private_endpoints 开关联动 SSRF 门禁(test/probe 一致)

> 接管记录（2026-08-21 23:30 用户指定）：PR#9 mtime 竞态断言放宽✅、PR#12 坐标系统一+/login
> TypeError(useModalA11y 契约归一化 getter)✅ 均五项 CI 绿合并；撞车教训与验证方法学见根目录黑板。