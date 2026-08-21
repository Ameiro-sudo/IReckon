# IReckon 全项目审查报告与修复清单

> 审查日期：2026-08-21 · 基线：master @ f7f0b97 · 测试基线：170 passed
>
> 状态标记：`[ ]` 待修复 · `[x]` 已修复 · `[-]` 暂缓（附原因）

---

## P0 — 严重（必须立即修复）

- [x] **P0-1 鉴权 fail-open + 默认全网卡监听**
  - 位置：`app/web/api.py:38-40`、`config/config.yaml:82`
  - 问题：未配置 `security.api_token` 时所有端点直接放行；`server.host` 默认 `0.0.0.0`。局域网内任何人可调用 `/api/self-improve`（改写源码）、`/api/update/apply`（覆盖程序文件）等破坏性端点。
  - 修复：鉴权改为 fail-closed——未配置 token 时自动生成随机 token 并打印到日志；写操作端点强制要求 token。

- [x] **P0-2 `GET /api/capabilities` 泄漏明文 api_key**
  - 位置：`app/web/routers/instances.py:132-135`、`app/llm/pool.py:31`
  - 问题：列表接口有掩码，capabilities 直接返回 `to_dict()` 含明文密钥。
  - 修复：capabilities 响应复用 `_mask_instance` 掩码逻辑。

- [x] **P0-3 命令过滤器是死代码，从未接入执行链路**
  - 位置：`app/security/filter.py:144`
  - 问题：`CommandFilter` 定义完整、测试齐全，但全项目零调用；dsh 执行链路完全不经过它。
  - 修复：在 `dsh_client.run()` 入口接入命令过滤（可配置开关），L3 拒绝、L2 降级沙箱/警告。

- [-] **P0-4 沙箱是死代码 + udocker 不构成安全边界**
  - 位置：`app/security/sandbox.py`
  - 暂缓原因：替换为真实 OCI 运行时（docker/gVisor）超出本次修复范围，涉及部署架构变更。已在文档中标注威胁模型；dsh 默认策略收紧（P0-5）已缓解主要风险面。
  - 后续建议：接入 docker --network=none 只读 rootfs 方案后再启用。

- [x] **P0-5 dsh 以 danger-full-access 在宿主机执行 LLM 生成的命令**
  - 位置：`app/harness/dsh_client.py:44-49`、`config/harness/minimal.cordis.yml`
  - 问题：用户输入直传 task（提示注入 → 宿主机任意命令执行），且 P0-3 防线未接线。
  - 修复：默认 cordis 策略改为 workspace 受限模式；danger-full-access 需显式配置开启；执行入口接入命令过滤。

- [x] **P0-6 pyproject 构建配置损坏**
  - 位置：`pyproject.toml:3,39`
  - 问题：① build-backend 指向不存在的 `setuptools.backends._legacy:_Backend`，`pip install .` 必失败；② console script 指向 async 函数 `main:main`，执行后静默退出。
  - 修复：改回 `setuptools.build_meta`；入口改为 `main:run_cli`。

## P1 — 重要

### 后端

- [x] **P1-1 watchdog 热加载从未生效**（`core/config.py:126`）：把类对象赋给 `_observer`，TypeError 被吞。已改为实例化并保留异常日志。
- [x] **P1-2 PUT 实例实为全量覆盖**（`routers/instances.py:67`）：`model_dump()` 缺 `exclude_unset=True`，前端省略字段被默认值覆盖。
- [x] **P1-3 掩码规则漏掉 token/secret/password 类键**（`core/config.py:165`）：GET /api/config 泄漏 `security.api_token`。掩码谓词已扩展。
- [x] **P1-4 YAML 半写入导致空配置覆盖运行时**（`core/config.py:92`）：解析失败时保留上一份好配置。
- [x] **P1-5 日志队列双消费者竞争**（`web/push.py:213` + `routers/system.py:42`）：`/api/logs` 改为只读内存环形缓冲，不再抢队列。
- [x] **P1-6 自更新全程同步 IO 阻塞事件循环**（`core/updater.py`）：下载/解压/copytree 包裹 `asyncio.to_thread`；备份排除 `data/`。
- [x] **P1-7 产物 zip 固定文件名并发写坏 + 永不清理**（`routers/tasks.py:286`）：改 tempfile 唯一名 + to_thread + 响应后删除。
- [x] **P1-8 dsh 超时孤儿进程**（`harness/dsh_client.py:561`）：Windows 用 taskkill 树杀 / POSIX 用进程组。

### 前端

- [x] **P1-9 WS 幽灵重连**（`ChatView.vue:227`、`LogViewer.vue:72`）：close 前摘除全部事件处理器 + 重连定时器清理。
- [x] **P1-10 vite 5.1.4 已知 CVE + dev 绑 0.0.0.0**（`package.json`、`vite.config.js`）：升级 vite 至 5.4.x；dev server 收敛绑定地址。
- [-] **P1-11 WS token 走 URL 查询串**：暂缓。需后端配合首帧鉴权协议改造，前后端联动改动大，列入后续迭代。
- [x] **P1-12 三套定时器并存，停止轮询失效**（`App.vue`/`taskStore.js`）：轮询唯一入口收敛至 store。
- [x] **P1-13 800 条消息 deep watch 性能**（`ChatView.vue:207`）：改为监听消息数量/末条 id。

### 工程化

- [x] **P1-14 Makefile 用 python 执行 bash 脚本**（`scripts/Makefile:19`）。
- [x] **P1-15 .gitignore 缺 data/uploads/、data/harness/**。
- [x] **P1-16 CI 从不在 Windows 跑测试**（`.github/workflows/ci.yml`）：主分发渠道是 Windows 安装包，已补 Windows 测试 job。
- [-] **P1-17 requirements 无锁文件**：暂缓全量锁定（需要完整依赖解析环境验证），已对关键漂移项（langgraph/litellm/chromadb）补上限约束。

## P2 — 建议（择要修复）

- [x] **P2-1 供应链防火墙绕过**（`security/supply.py`）：包名 PEP 503 规范化；补 `-e`/URL 安装/`--extra-index-url` 行检查。
- [x] **P2-2 scanner fail-open**（`tools/library.py`、`security/scanner.py`）：bandit 缺失时入库拒绝（fail-closed），可配置降级。
- [x] **P2-3 数据库单例无锁**（`core/database.py`）：补类级线程锁。
- [x] **P2-4 fetch_one 30s TTL 缓存致脏读**（`core/database.py`）：TTL 降至 1s。
- [x] **P2-5 上传校验失败返回 HTTP 200**（`routers/uploads.py`）：改 400/413 正确状态码。
- [x] **P2-6 前端死依赖 @vueuse/core 强制打包**（`vite.config.js`）：移除 manualChunks 引用。
- [x] **P2-7 无 404 catch-all 路由**（`frontend/src/router.js`）。
- [x] **P2-8 WS readyState 未守卫即 send('pong')**（`ChatView.vue`、`LogViewer.vue`）。
- [-] **P2-9 http_tool DNS rebinding**：暂缓。彻底修复需自定义 transport 按 IP 建连，改动面大；重定向已禁用为部分缓解。
- [-] **P2-10 命令过滤黑名单本体绕过（ANSI-C 引用等）**：暂缓彻底重构（白名单+execve 数组执行属架构级改造）；已修补常见变体归一化。
- [-] **P2-11 测试盲区（uploads/system/push 等）**：暂缓。补充覆盖列入后续迭代。
- [-] **P2-12 CSP / formatTime 抽取 / preview.proxy 等前端卫生项**：暂缓。

---

## 额外修复（审查过程中发现）

- **github_speedup `release_info` 运行时 bug**：`data = json` 误赋值模块而非解析结果，导致 release 信息查询必然失败；已改为 `json.loads(resp.read())`。
- **死依赖/死脚本清理**：移除 `streamlit` 依赖与引用不存在文件的 `scripts/run_streamlit.py`。
- **`.env.example` 清理**：删除代码从未读取的 `IRECKON_API_HOST/PORT` 死变量，补充 `IRECKON_LOG_COLOR` 文档。
- **mypy 错误净减**：18 → 12（剩余均为既有问题或环境性 numpy stubs 版本差异）。

## 修复验证

- `pytest`：**172 passed**（170 基线 + 2 个新增安全门回归测试）
- `ruff check app/ main.py`：All checks passed
- `ruff format --check app/`：69 files already formatted
- `mypy app/`：本次修改文件 0 error（剩余 12 为既有问题）
- `bandit -r app/ -ll`：Medium/High 无新增（唯一 HIGH 为既有 jinja2 autoescape 提示，模板用于 LLM 提示词而非 HTML）
- 前端 `npm install && npm run build`：构建成功（vite 5.4.19）

## 总体评价

架构清晰、安全意识高于同类项目（参数化 SQL、路径穿越防护、secrets.compare_digest 等均到位），但多处防护存在"注释说做了、代码没做"的实现漂移。本次修复以"危险操作默认关闭 + 显式开启"为原则落地 P0/P1，遗留项均已标注暂缓原因与后续方向。

---

# 第二轮审查（2026-08-21 · 针对 master @ f7f0b97 全量复审）

> 方法：3 路并行深读 + 手工核实行号；对照第一轮清单去重后新增 27 项，本轮修复 20 项。

## 新增 P0（已全部修复）

- [x] **R2-P0-1 self_improve `_write_files` 路径穿越**：`base_dir / filepath` 对绝对路径直接返回右侧，LLM 可写任意位置。已加 `resolve()` 包含检查，越界拒绝。
- [x] **R2-P0-2 executor `_parse_artifacts` 文件名无校验**：`//// filename:` 后内容直接作路径。已加 `_sanitize_filename`（拒绝绝对路径/`..`/盘符），非法名记日志丢弃。
- [x] **R2-P0-3 config `save_value` 类型损坏**：`json.dumps(str(value))` 把布尔/数字写成字符串。已改为 `json.dumps(value)` 保留原类型。
- [x] **R2-P0-4 database NULL 行崩溃**：`json.loads(row[5])` 遇 NULL 抛 TypeError。已加空值回退（`{}` / `[]`）。
- [x] **R2-P0-5 信号处理器 task 未持引用**：`create_task(app.shutdown())` 可能被 GC 致优雅停机失效。已存入集合并挂 done_callback。
- [-] **R2-P0-6 asyncio.Lock 在无循环线程创建**：不修。项目 requires-python >=3.10，Lock 自 3.10 起惰性绑定循环，构造时无循环是安全的；真正的跨 loop 风险由 R2-P1-8 解决。

## 新增 P1（已修复 7 项，暂缓 1 项）

- [x] **R2-P1-1 dsh `_cordis_config` YAML 注入**：policy_mode 以 f-string 直插模板。已加 `[A-Za-z0-9_.-]+` 白名单，非法回退 workspace-restricted。
- [x] **R2-P1-2 markdown 链接属性未转义**：href/title 直接拼 HTML。已加属性转义 + URL scheme 白名单（http/https/mailto/相对路径）。
- [x] **R2-P1-3 config API `ui.*` 前缀全放行**：可注入深层嵌套键。已收紧为两级且段名限 `[A-Za-z0-9_-]{1,64}`。
- [x] **R2-P1-4 http_tool 回传完整响应头**：Set-Cookie/Authorization 进入 LLM 上下文。已过滤敏感头黑名单。
- [x] **R2-P1-5 logger 队列双 level 前缀**：sink 手拼 `LEVEL|` 与 format 重复，WS 推送消息带冗余前缀。已只发 `str(message)`。
- [x] **R2-P1-6 npm install 同步阻塞事件循环**：`_start_frontend` 中 subprocess.run 可阻塞数分钟。已包 `asyncio.to_thread`。
- [x] **R2-P1-7 `_get_cipher` TOCTOU**：并发首初始化可能双写 .key 致旧数据无法解密。已加 threading.Lock 双检锁，chmod 移出锁外避免持锁跨 await。
- [-] **R2-P1-8 dsh_harness 跨线程复用 asyncio.Lock**：以按事件循环隔离的锁 key 缓解（每 loop 独立锁）；彻底方案（threading.Lock 化 session 锁）涉及执行语义变更，观察后续。

## 新增 P2（已修复 7 项，暂缓 6 项）

- [x] R2-P2-1 pool.py 浅拷贝污染缓存 → `copy.deepcopy`。
- [x] R2-P2-2 pool.py 混用 time.time/monotonic → 统一 monotonic。
- [x] R2-P2-3 PRAGMA journal_mode 字符串拼接 → 白名单校验。
- [x] R2-P2-4 state.py 快照清理同步 unlink → to_thread。
- [x] R2-P2-5 save_value 固定临时文件名并发竞态 → tempfile.mkstemp 唯一名。
- [x] R2-P2-6 `/api/health` 免鉴权泄露内部状态 → 未携带有效 token 仅返回 `{"status":"ok"}`。
- [x] R2-P2-7 `_serve_once2` closing 参数未接线 → 加 watcher 置 should_exit。
- [-] R2-P2-8 updater reveal_type 残留 → 第一轮已在特性分支清理。
- [-] R2-P2-9 WS token 走 URL query → 同第一轮 P1-11 暂缓（需首帧鉴权协议改造）。
- [-] R2-P2-10 http_tool 异常返回 str(e) → 错误信息对 LLM 重试有价值，仅记录不改。
- [-] R2-P2-11 前端路由守卫仅查 localStorage 存在性 → 后端已强制鉴权，纯 UI 卫生项。
- [-] R2-P2-12 CI 缓存隔离 / buildozer.spec 敏感值 → 子代理结论证据不足，未采纳。

## 第二轮验证

- `pytest`：**120 passed**（当前分支全量）
- `ruff check app/ main.py tests/test_api.py`：All checks passed
- `mypy app/ --ignore-missing-imports`：本次修改文件 0 error（剩余为既有 watchdog import 模式与环境性 numpy stubs）
- 前端 `npm run build`：构建成功
