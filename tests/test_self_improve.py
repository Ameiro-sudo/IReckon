"""自我改进模块测试:SelfImprover 的解析、黑名单、补丁应用与 git 操作。"""

import asyncio
from pathlib import Path
from types import SimpleNamespace

import app.engine.self_improve as si_mod
from app.engine.self_improve import SelfImprover, _get_executor, _parse_analysis
from conftest import ROOT, make_cap

# 触发 app/agents/* 的角色注册（executor 等），供 role_registry.create_agent 使用
import app.agents  # noqa: E402,F401


def _cfg_get(k, d=None):
    cfg = {
        "self_update.enabled": True,
        "self_update.max_files_per_round": 5,
        "self_update.branch_prefix": "self-improve",
        "self_update.file_blacklist": [
            "config/config.yaml",
            "data/",
            "app/security/",
            "app/core/updater.py",
        ],
        "ai_pool.instances": [],
    }
    return cfg.get(k, d)


def make_improver(monkeypatch):
    # self_improve 在导入时绑定 get = config_manager.get，必须同时打模块级 get
    monkeypatch.setattr(si_mod, "get", _cfg_get)
    monkeypatch.setattr(si_mod.config_manager, "get", _cfg_get)
    return SelfImprover()


class FakeExecutor:
    def __init__(self, response="ok"):
        self.response = response
        self.bound = None

    def bind_context(self, task_id):
        self.bound = task_id

    async def think(self, prompt, temperature=None):
        return self.response


# ---------- analyze ----------


def test_analyze_disabled(monkeypatch):
    imp = make_improver(monkeypatch)
    imp._enabled = False
    result = asyncio.run(imp.analyze("t1"))
    assert result["success"] is False
    assert "关闭" in result["error"]


def test_analyze_no_source_files(monkeypatch):
    imp = make_improver(monkeypatch)
    monkeypatch.setattr(imp, "_list_source_files", lambda: [])
    result = asyncio.run(imp.analyze("t1"))
    assert result["success"] is False
    assert "没有可分析" in result["error"]


def test_analyze_no_executor(monkeypatch):
    imp = make_improver(monkeypatch)

    async def _no_executor(tid):
        return None

    monkeypatch.setattr(si_mod, "_get_executor", _no_executor)
    result = asyncio.run(imp.analyze("t1"))
    assert result["success"] is False
    assert "Executor" in result["error"]


def test_analyze_success(monkeypatch):
    imp = make_improver(monkeypatch)
    executor = FakeExecutor("发现了一些问题，2 个文件需要修改")

    async def _get_exec(tid):
        return executor

    monkeypatch.setattr(si_mod, "_get_executor", _get_exec)
    result = asyncio.run(imp.analyze("t1"))
    assert result["success"] is True
    assert "发现了一些问题" in result["analysis"]
    assert result["changes_proposed"] == 2


# ---------- _get_executor ----------


def test_get_executor_uses_find_best_match(monkeypatch):
    make_improver(monkeypatch)
    _instances_get = lambda k, d=None: (
        [{"id": "x"}] if k == "ai_pool.instances" else _cfg_get(k, d)
    )
    monkeypatch.setattr(si_mod, "get", _instances_get)
    monkeypatch.setattr(si_mod.config_manager, "get", _instances_get)
    cap = make_cap(tags=["coding", "smart"])

    async def fake_find(**kw):
        return cap

    monkeypatch.setattr(si_mod.capability_pool, "find_best_match", fake_find)
    ex = asyncio.run(_get_executor("t1"))
    assert ex is not None
    assert ex.context is not None
    assert ex.context.task_id == "t1"


def test_get_executor_falls_back_to_get_all(monkeypatch):
    make_improver(monkeypatch)
    cap = make_cap(tags=["coding", "smart"])

    async def fake_get_all():
        return [cap]

    monkeypatch.setattr(si_mod.capability_pool, "get_all", fake_get_all)
    ex = asyncio.run(_get_executor("t1"))
    assert ex is not None


def test_get_executor_no_caps(monkeypatch):
    make_improver(monkeypatch)

    async def fake_get_all():
        return []

    monkeypatch.setattr(si_mod.capability_pool, "get_all", fake_get_all)
    assert asyncio.run(_get_executor("t1")) is None


def test_get_executor_unregistered_role(monkeypatch):
    make_improver(monkeypatch)
    cap = make_cap(tags=["coding", "smart"])

    async def fake_get_all():
        return [cap]

    monkeypatch.setattr(si_mod.capability_pool, "get_all", fake_get_all)
    monkeypatch.setattr(
        si_mod.role_registry, "create_agent", lambda role, cap, **kw: None
    )
    assert asyncio.run(_get_executor("t1")) is None


# ---------- 源文件扫描 ----------


def test_list_source_files_respects_blacklist(monkeypatch):
    imp = make_improver(monkeypatch)
    files = imp._list_source_files()
    assert isinstance(files, list)
    assert files
    paths = {f["path"] for f in files}
    root = Path(ROOT)
    assert all(root.joinpath(p).exists() for p in paths)
    assert "app/core/updater.py" not in paths
    assert not any(p.startswith("data/") for p in paths)
    assert not any(p.startswith("app/security/") for p in paths)
    assert all(f["size"] >= 0 for f in files)


def test_is_blacklisted(monkeypatch):
    imp = make_improver(monkeypatch)
    assert imp._is_blacklisted("config/config.yaml") is True
    assert imp._is_blacklisted("data/anything/x.py") is True
    assert imp._is_blacklisted("app/security/filter.py") is True
    assert imp._is_blacklisted("app/security") is True
    assert imp._is_blacklisted("app/core/updater.py") is True
    assert imp._is_blacklisted("app/engine/machine.py") is False
    assert imp._is_blacklisted("config/config.yaml.evil") is False


def test_build_analysis_prompt(monkeypatch):
    imp = make_improver(monkeypatch)
    files = [{"path": f"app/x{i}.py", "size": 100} for i in range(3)]
    prompt = imp._build_analysis_prompt(files)
    assert "共 3 个" in prompt
    assert "app/x0.py (100 bytes)" in prompt
    assert "…" not in prompt


def test_build_analysis_prompt_many_files(monkeypatch):
    imp = make_improver(monkeypatch)
    files = [{"path": f"app/x{i}.py", "size": 10} for i in range(40)]
    prompt = imp._build_analysis_prompt(files)
    assert "共 40 个" in prompt
    assert "及其他 10 个文件" in prompt


def test_parse_analysis(monkeypatch):
    make_improver(monkeypatch)
    result = _parse_analysis("发现 2 个文件需要修改")
    assert result["success"] is True
    assert result["changes_proposed"] == 2
    empty = _parse_analysis("没有发现")
    assert empty["changes_proposed"] == 0


# ---------- apply_improvements ----------


def test_apply_improvements_disabled_analysis(monkeypatch):
    imp = make_improver(monkeypatch)
    analysis = {"success": False, "error": "自我改进已关闭"}
    result = asyncio.run(imp.apply_improvements("t1", analysis))
    assert result == analysis


def test_apply_improvements_branch_fail(monkeypatch):
    imp = make_improver(monkeypatch)
    monkeypatch.setattr(imp, "_git_create_branch", lambda b: False)
    result = asyncio.run(
        imp.apply_improvements("t1", {"success": True, "analysis": "x"})
    )
    assert result["success"] is False
    assert "分支" in result["error"]


def test_apply_improvements_no_caps(monkeypatch):
    imp = make_improver(monkeypatch)
    monkeypatch.setattr(imp, "_git_create_branch", lambda b: True)

    async def fake_get_all():
        return []

    monkeypatch.setattr(si_mod.capability_pool, "get_all", fake_get_all)
    result = asyncio.run(
        imp.apply_improvements("t1", {"success": True, "analysis": "x"})
    )
    assert result["success"] is False
    assert "AI 实例" in result["error"]


def test_apply_improvements_no_valid_patches(monkeypatch):
    imp = make_improver(monkeypatch)
    monkeypatch.setattr(imp, "_git_create_branch", lambda b: True)
    monkeypatch.setattr(imp, "_apply_patches", lambda r, s: {})

    async def fake_get_all():
        return [make_cap(tags=["coding", "smart"])]

    monkeypatch.setattr(si_mod.capability_pool, "get_all", fake_get_all)
    monkeypatch.setattr(
        si_mod.role_registry, "create_agent", lambda role, cap, **kw: FakeExecutor()
    )
    result = asyncio.run(
        imp.apply_improvements("t1", {"success": True, "analysis": "x"})
    )
    assert result["success"] is False
    assert "没有生成有效" in result["error"]


def test_apply_improvements_full_success(monkeypatch, tmp_path):
    imp = make_improver(monkeypatch)
    monkeypatch.setattr(imp, "_git_create_branch", lambda b: True)
    monkeypatch.setattr(imp, "_git_commit", lambda m: True)

    async def fake_get_all():
        return [make_cap(tags=["coding", "smart"])]

    monkeypatch.setattr(si_mod.capability_pool, "get_all", fake_get_all)
    monkeypatch.setattr(
        si_mod.role_registry,
        "create_agent",
        lambda role, cap, **kw: FakeExecutor(
            "FILE: app/engine/cost.py\n```python\nprint('x')\n```"
        ),
    )
    written = []
    monkeypatch.setattr(
        Path,
        "write_text",
        lambda self, content, encoding=None: written.append((str(self), content)),
    )

    result = asyncio.run(
        imp.apply_improvements("t1", {"success": True, "analysis": "分析"})
    )
    assert result["success"] is True
    assert result["branch"] == "self-improve/t1"
    assert result["files_changed"] == ["app/engine/cost.py"]
    assert "self-improve" in result["commit_message"]
    assert len(written) == 1


def test_build_patch_prompt(monkeypatch):
    imp = make_improver(monkeypatch)
    sources = {"app/a.py": "content-a", "app/b.py": "content-b"}
    prompt = imp._build_patch_prompt("分析结果", sources)
    assert "分析结果" in prompt
    assert "===== app/a.py =====" in prompt
    assert "content-b" in prompt
    assert f"最多 {imp._max_files} 个文件" in prompt


# ---------- _apply_patches ----------


def test_apply_patches_parses_single_file(monkeypatch):
    imp = make_improver(monkeypatch)
    response = "FILE: app/x.py\n```python\nprint(1)\n```"
    result = imp._apply_patches(response, {"app/x.py": "old"})
    assert result == {"app/x.py": "print(1)"}


def test_apply_patches_multiple_files_and_truncation(monkeypatch):
    imp = make_improver(monkeypatch)
    imp._max_files = 2
    response = "\n".join(
        part
        for i in range(4)
        for part in [
            f"FILE: app/f{i}.py",
            "```python",
            f"code{i}",
            "```",
            "",
        ]
    )
    sources = {f"app/f{i}.py": "old" for i in range(4)}
    result = imp._apply_patches(response, sources)
    assert set(result) == {"app/f0.py", "app/f1.py"}
    assert result["app/f0.py"] == "code0"


def test_apply_patches_filters_blacklist_and_unknown(monkeypatch):
    imp = make_improver(monkeypatch)
    response = "\n".join(
        [
            "FILE: app/core/updater.py",
            "```python",
            "evil",
            "```",
            "FILE: app/nonexistent.py",
            "```python",
            "unknown",
            "```",
        ]
    )
    result = imp._apply_patches(response, {"app/known.py": "old"})
    assert result == {}


def test_apply_patches_ignores_non_code_lines(monkeypatch):
    imp = make_improver(monkeypatch)
    response = "说明文字\nFILE: app/x.py\n```python\ncode\n中间没有围栏的尾巴\n"
    result = imp._apply_patches(response, {"app/x.py": "old"})
    assert result == {"app/x.py": "code\n中间没有围栏的尾巴"}


# ---------- git 操作 ----------


def test_git_create_branch_success(monkeypatch):
    imp = make_improver(monkeypatch)
    calls = []
    monkeypatch.setattr(
        si_mod.subprocess,
        "run",
        lambda *a, **kw: calls.append((a, kw)) or SimpleNamespace(returncode=0),
    )
    assert imp._git_create_branch("self-improve/x") is True
    assert calls and calls[0][0][0][0] == "git"


def test_git_create_branch_failure(monkeypatch):
    imp = make_improver(monkeypatch)

    def boom(*a, **kw):
        raise RuntimeError("no git")

    monkeypatch.setattr(si_mod.subprocess, "run", boom)
    assert imp._git_create_branch("x") is False


def test_git_commit(monkeypatch):
    imp = make_improver(monkeypatch)
    calls = []

    def fake_run(args, *a, **kw):
        calls.append(args)
        if args[1] == "status":
            return SimpleNamespace(
                returncode=0,
                stdout=" M app/engine/cost.py\n M data/secret.db\n M .env\n",
            )
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(si_mod.subprocess, "run", fake_run)
    assert imp._git_commit("msg") is True
    added = [list(c) for c in calls if c[1] == "add"]
    assert added == [["git", "add", "--", "app/engine/cost.py"]]
    assert ["git", "commit", "-m", "msg"] in calls


def test_git_commit_no_whitelisted_changes(monkeypatch):
    imp = make_improver(monkeypatch)
    calls = []

    def fake_run(args, *a, **kw):
        calls.append(args)
        if args[1] == "status":
            return SimpleNamespace(
                returncode=0, stdout=" M data/secret.db\n M config/config.yaml\n"
            )
        return SimpleNamespace(returncode=0, stdout="")

    monkeypatch.setattr(si_mod.subprocess, "run", fake_run)
    assert imp._git_commit("msg") is False
    assert all(c[1] != "commit" for c in calls)


def test_git_commit_failure(monkeypatch):
    imp = make_improver(monkeypatch)

    def boom(*a, **kw):
        raise RuntimeError("no git")

    monkeypatch.setattr(si_mod.subprocess, "run", boom)
    assert imp._git_commit("msg") is False


def test_push_to_remote_master(monkeypatch):
    imp = make_improver(monkeypatch)
    monkeypatch.setattr(
        si_mod.subprocess,
        "run",
        lambda *a, **kw: SimpleNamespace(stdout="master"),
    )
    assert asyncio.run(imp.push_to_remote()) is False


def test_push_to_remote_branch(monkeypatch):
    imp = make_improver(monkeypatch)
    calls = []
    monkeypatch.setattr(
        si_mod.subprocess,
        "run",
        lambda *a, **kw: (
            calls.append(a[0]) or SimpleNamespace(returncode=0, stdout="feature/x")
        ),
    )
    assert asyncio.run(imp.push_to_remote()) is True
    assert ["git", "push", "-u", "origin", "feature/x"] in calls


def test_push_to_remote_failure(monkeypatch):
    imp = make_improver(monkeypatch)

    def boom(*a, **kw):
        raise RuntimeError("network down")

    monkeypatch.setattr(si_mod.subprocess, "run", boom)
    assert asyncio.run(imp.push_to_remote()) is False


# ---------- 异步运行态：start_run / status / history ----------


def _make_async_improver(monkeypatch, tmp_path):
    """带 tmp 数据目录的 improver；历史持久化全部落在测试沙箱内。"""
    imp = make_improver(monkeypatch)

    def get_with_datadir(k, d=None):
        if k == "system.data_dir":
            return str(tmp_path)
        return _cfg_get(k, d)

    monkeypatch.setattr(si_mod, "get", get_with_datadir)
    monkeypatch.setattr(si_mod.config_manager, "get", get_with_datadir)
    return imp


def test_start_run_completes_and_persists_history(monkeypatch, tmp_path):
    import json

    imp = _make_async_improver(monkeypatch, tmp_path)

    async def fake_analyze(task_id):
        return {"success": True, "analysis": "## 发现 1\n涉及 2 个文件"}

    async def fake_apply(task_id, analysis):
        return {
            "success": True,
            "branch": "self-improve/abcd1234",
            "files_changed": ["app/x.py"],
            "commit_message": "self-improve: AI 自动改进",
        }

    monkeypatch.setattr(imp, "analyze", fake_analyze)
    monkeypatch.setattr(imp, "apply_improvements", fake_apply)

    async def scenario():
        started = await imp.start_run()
        assert started["status"] == "started"
        assert started["run"]["status"] == "running"
        await asyncio.gather(*list(imp._run_tasks))
        status = await imp.get_status()
        return started, status

    started, status = asyncio.run(scenario())
    assert started["run"]["run_id"] == status["run"]["run_id"]
    assert status["active"] is False
    run = status["run"]
    assert run["status"] == "ok"
    assert run["branch"] == "self-improve/abcd1234"
    assert run["files_changed"] == ["app/x.py"]
    assert run["finished_at"]

    hist_file = tmp_path / "self_improve" / "history.json"
    assert hist_file.exists()
    items = json.loads(hist_file.read_text(encoding="utf-8"))
    assert len(items) == 1
    assert items[0]["status"] == "ok"
    assert items[0]["run_id"] == run["run_id"]


def test_start_run_rejects_concurrent(monkeypatch, tmp_path):
    imp = _make_async_improver(monkeypatch, tmp_path)
    release = asyncio.Event()

    async def slow_apply(task_id, analysis):
        await release.wait()
        return {"success": True, "branch": "self-improve/zz", "files_changed": []}

    async def fake_analyze(task_id):
        return {"success": True, "analysis": "x"}

    async def scenario():
        first = await imp.start_run()
        second = await imp.start_run()  # 流水线仍挂起 → busy
        release.set()
        await asyncio.gather(*list(imp._run_tasks))
        return first, second

    monkeypatch.setattr(imp, "analyze", fake_analyze)
    monkeypatch.setattr(imp, "apply_improvements", slow_apply)
    first, second = asyncio.run(scenario())
    assert first["status"] == "started"
    assert second["status"] == "busy"
    assert second["run"]["run_id"] == first["run"]["run_id"]


def test_start_run_error_recorded_in_status_and_history(monkeypatch, tmp_path):
    import json

    imp = _make_async_improver(monkeypatch, tmp_path)

    async def failing_analyze(task_id):
        return {"success": False, "error": "无法获取 Executor agent"}

    async def scenario():
        started = await imp.start_run()
        await asyncio.gather(*list(imp._run_tasks))
        return started, await imp.get_status()

    monkeypatch.setattr(imp, "analyze", failing_analyze)
    started, status = asyncio.run(scenario())
    assert started["status"] == "started"
    assert status["active"] is False
    assert status["run"]["status"] == "error"
    assert "Executor" in status["run"]["error"]

    items = json.loads(
        (tmp_path / "self_improve" / "history.json").read_text(encoding="utf-8")
    )
    assert items[0]["status"] == "error"


def test_start_run_disabled(monkeypatch, tmp_path):
    imp = _make_async_improver(monkeypatch, tmp_path)
    imp._enabled = False
    result = asyncio.run(imp.start_run())
    assert result["status"] == "error"
    assert "关闭" in result["error"]


def test_history_capped_at_50_newest_first(monkeypatch, tmp_path):
    imp = _make_async_improver(monkeypatch, tmp_path)
    for i in range(60):
        imp._append_history({"run_id": f"r{i}", "status": "ok"})
    items = imp.get_history()
    assert len(items) == 50
    assert items[0]["run_id"] == "r59"  # 新→旧
    assert items[-1]["run_id"] == "r10"


def test_history_missing_or_corrupt_degrades_empty(monkeypatch, tmp_path):
    imp = _make_async_improver(monkeypatch, tmp_path)
    assert imp.get_history() == []
    f = tmp_path / "self_improve" / "history.json"
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("{not-json", encoding="utf-8")
    assert imp.get_history() == []


# ---------- API 形状（路由薄封装冒烟，直接打 self_improver 单例） ----------


def test_api_start_status_history_flow(monkeypatch, tmp_path):
    import json as _json

    import httpx

    from app.web.api import app

    def get_with_datadir(k, d=None):
        if k == "system.data_dir":
            return str(tmp_path)
        return _cfg_get(k, d)

    monkeypatch.setattr(si_mod, "get", get_with_datadir)
    monkeypatch.setattr(si_mod.config_manager, "get", get_with_datadir)

    imp = si_mod.self_improver
    monkeypatch.setattr(imp, "_enabled", True)

    async def fake_analyze(task_id):
        return {"success": True, "analysis": "涉及 1 个文件"}

    async def fake_apply(task_id, analysis):
        return {
            "success": True,
            "branch": "self-improve/api1",
            "files_changed": ["a.py"],
        }

    monkeypatch.setattr(imp, "analyze", fake_analyze)
    monkeypatch.setattr(imp, "apply_improvements", fake_apply)
    # require_strict_token 端点：显式配置 token 并随请求携带
    monkeypatch.setenv("IRECKON_API_TOKEN", "irk_self_improve_test")

    async def scenario():
        transport = httpx.ASGITransport(app=app)
        headers = {"X-API-Token": "irk_self_improve_test"}
        async with httpx.AsyncClient(
            transport=transport, base_url="http://test", headers=headers
        ) as c:
            post = await c.post("/api/self-improve")
            await asyncio.gather(*list(imp._run_tasks))
            status = await c.get("/api/self-improve/status")
            history = await c.get("/api/self-improve/history")
            return post, status, history

    post, status, history = asyncio.run(scenario())
    assert post.status_code == 200
    body = post.json()
    assert body["status"] == "started"
    assert body["run"]["status"] == "running"

    sbody = status.json()
    assert sbody["status"] == "ok"
    assert sbody["active"] is False
    assert sbody["run"]["status"] == "ok"
    assert sbody["run"]["branch"] == "self-improve/api1"

    hbody = history.json()
    assert hbody["status"] == "ok"
    assert isinstance(hbody["items"], list)
    assert any(item["run_id"] == body["run"]["run_id"] for item in hbody["items"])
    assert _json.dumps(hbody, ensure_ascii=False)  # 序列化健全性
