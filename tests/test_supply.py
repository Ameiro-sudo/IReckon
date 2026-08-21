"""供应链防火墙测试(补覆盖率盲区)：包名规范化/提取、pip/npm 拦截、requirements 递归检查。"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest

from app.security.supply import SupplyChainFirewall


@pytest.fixture
def fw():
    return SupplyChainFirewall()


# ---------- 规范化与包名提取 ----------


@pytest.mark.parametrize(
    "raw,expect",
    [
        ("requests_fake", "requests-fake"),
        ("Requests.Fake", "requests-fake"),
        ("Malicious--Package", "malicious-package"),
        ("requests==2.0", "requests"),
        ("'requests>=2,<3'", "requests"),
        ('"secrethash"', "secrethash"),
        ("@scope/fake-react@1.0.0", "fake-react"),
        ("git+https://github.com/owner/malicious-package.git", "malicious-package"),
        (
            "https://host/wheels/thisisafakedpy-1.0-py3-none-any.whl",
            "thisisafakedpy",
        ),
    ],
)
def test_extract_package_name(raw, expect):
    assert SupplyChainFirewall._extract_package_name(raw) == expect


# ---------- pip 命令 ----------


def test_pip_clean_passes(fw):
    assert fw.check_install_command("pip install numpy pandas") is True


def test_pip_blocked_direct(fw):
    assert fw.check_install_command("pip install malicious-package") is False


def test_pip_blocked_pep503_variants(fw):
    assert fw.check_install_command("pip install Malicious.Package") is False
    assert fw.check_install_command("python -m pip install malicious_package") is False


def test_pip_uninstall_not_inspected(fw):
    # 卸载命令不在安装模式内，不触发拦截(设计如此：只防安装投毒)
    assert fw.check_install_command("pip uninstall malicious-package") is True


def test_non_install_command_ignored(fw):
    assert fw.check_install_command("") is True
    assert fw.check_install_command("ls -la") is True


def test_uv_and_poetry_and_conda_forms(fw):
    assert fw.check_install_command("uv pip install secrethash") is False
    assert fw.check_install_command("poetry add pycrypto-demo") is False
    assert fw.check_install_command("conda install urllib") is False


def test_pip_negative_not_overblocked(fw):
    # urllib3 不等于 urllib；普通科学计算栈放行
    assert fw.check_install_command("pip install urllib3 scipy matplotlib") is True


# ---------- npm 命令 ----------


def test_npm_blocked_direct(fw):
    assert fw.check_install_command("npm install node-stealer") is False


def test_npm_scoped_package_blocked(fw):
    assert fw.check_install_command("yarn add @evil/node-stealer@2.0") is False


def test_npm_short_flag_and_pnpm(fw):
    assert fw.check_install_command("pnpm i fake-react") is False


def test_npm_clean_passes(fw):
    assert fw.check_install_command("npm install express lodash") is True
    assert fw.check_install_command("npm run build") is True


# ---------- requirements 文件递归检查 ----------


def _req_file(tmp_path, content):
    f = tmp_path / "requirements.txt"
    f.write_text(content, encoding="utf-8")
    return str(f)


def test_requirements_blacklisted_line_blocks(fw, tmp_path):
    r = _req_file(tmp_path, "numpy\nrequests_fake\nscipy\n")
    assert fw.check_install_command(f"pip install -r {r}") is False


def test_requirements_missing_file_conservative_reject(fw):
    assert fw.check_install_command("pip install -r ./nope/reqs.txt") is False


def test_requirements_http_index_rejected_https_ok(fw, tmp_path):
    bad = _req_file(tmp_path, "-i http://pypi.example.com/simple\nnumpy\n")
    assert fw.check_install_command(f"pip install -r {bad}") is False
    good = _req_file(tmp_path, "--extra-index-url https://mirror.example.com/simple\n")
    assert fw.check_install_command(f"pip install -r {good}") is True


def test_requirements_editable_checked(fw, tmp_path):
    r = _req_file(tmp_path, "-e git+https://github.com/o/malicious-package.git\n")
    assert fw.check_install_command(f"pip install -r {r}") is False


def test_requirements_comments_and_options_pass(fw, tmp_path):
    r = _req_file(
        tmp_path,
        "# 注释行\n--trusted-host pypi.example.com\nnumpy>=1.24\n",
    )
    assert fw.check_install_command(f"pip install -r {r}") is True


async def test_async_check_wrapper(fw):
    assert await fw.check("pip install malicious-package") is False
    assert await fw.check("pip install numpy") is True
