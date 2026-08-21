"""构建打包防泄漏测试：stage_config 必须把本地真实 config.yaml 挡在发行包外。

背景：--add-data 曾整目录打包 config/，开发者本机构建会把含真实密钥与
自动生成 api_token 的 config/config.yaml 烧进 EXE/安装包。
"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))


def test_stage_config_excludes_local_yaml(tmp_path, monkeypatch):
    import shutil

    import scripts.build_exe as be

    src = tmp_path / "config"
    (src / "prompts").mkdir(parents=True)
    (src / "config.yaml").write_text("api_token:irk_super_secret", encoding="utf-8")
    (src / "config.example.yaml").write_text("api_token:''", encoding="utf-8")
    (src / ".pre-commit-config.yaml").write_text("repos:[]", encoding="utf-8")
    (src / "prompts" / "executor.md").write_text("# prompt", encoding="utf-8")

    monkeypatch.chdir(tmp_path)
    staged = be.stage_config()

    assert (staged / "config.example.yaml").is_file()
    assert (staged / "prompts" / "executor.md").is_file()
    assert not (staged / "config.yaml").exists()
    assert not (staged / ".pre-commit-config.yaml").exists()

    shutil.rmtree(staged, ignore_errors=True)
