"""工具组装器与安全扫描器测试。"""

import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.resolve()
sys.path.insert(0, str(ROOT))

import pytest

from app.tools.assembler import ToolAssembler
from app.security.scanner import code_scanner
from app.security.supply import SupplyChainFirewall
from app.security.mining import MiningDetector
from app.agents.deliverer import DelivererAgent


def test_safe_filename_preserves_structure():
    assert DelivererAgent._safe_filename("src/models/todo.py") == "src/models/todo.py"
    assert (
        DelivererAgent._safe_filename("tests/unit/test_a.py") == "tests/unit/test_a.py"
    )
    assert DelivererAgent._safe_filename("../evil/x.py") == "evil/x.py"
    assert DelivererAgent._safe_filename("a:b.py") == "a_b.py"
    assert DelivererAgent._safe_filename("") == "unnamed.txt"


def test_assemble_sequence_has_calls():
    parts = [
        {"name": "a", "code": "def part_0(d):\n    return d + 1"},
        {"name": "b", "code": "def part_1(d):\n    return d * 2"},
    ]
    code = ToolAssembler.assemble_sequence(parts)
    assert "def assembled_tool(input_data):" in code
    assert "data = part_0(data)" in code
    assert "data = part_1(data)" in code
    ns = {}
    exec(code, ns)
    assert ns["assembled_tool"](5) == 12


def test_assemble_condition_branches():
    cond = {"name": "c", "code": "def condition(d):\n    return d > 0"}
    t = {"name": "t", "code": "def true_branch(d):\n    return 'pos'"}
    f = {"name": "f", "code": "def false_branch(d):\n    return 'neg'"}
    code = ToolAssembler.assemble_condition(cond, t, f)
    ns = {}
    exec(code, ns)
    assert ns["assembled_tool"](1) == "pos"
    assert ns["assembled_tool"](-1) == "neg"


def test_supply_firewall_blocklist():
    fw = SupplyChainFirewall()
    assert fw.check_install_command("pip install malicious-package") is False
    assert fw.check_install_command("pip install requests") is True
    assert fw.check_install_command("npm install evil-package") is False
    assert fw.check_install_command("apt install python3") is True


def test_mining_detector_patterns():
    md = MiningDetector()
    assert (
        md.scan_command_line("./xmrig -o stratum+tcp://pool.minexmr.com:4444") is True
    )
    assert md.scan_command_line("python3 -u miner.py") is True
    assert md.scan_command_line("python3 print('hello')") is False


@pytest.mark.asyncio
async def test_scanner_no_tool_degrades():
    result = await code_scanner.scan("print(1)", language="python")
    assert isinstance(result, list)
