"""安全模块测试:命令过滤、代码扫描、供应链防火墙、挖矿检测、工具组装。"""


from app.security.filter import CommandFilter, CommandLevel
from app.security.mining import MiningDetector
from app.security.scanner import code_scanner
from app.security.supply import SupplyChainFirewall
from app.tools.assembler import ToolAssembler


# ---------- 命令分级过滤 ----------


def test_classify_levels():
    cf = CommandFilter()
    assert cf.classify("rm -rf /") == CommandLevel.L3
    assert cf.classify("dd if=/dev/zero of=/dev/sda") == CommandLevel.L3
    assert cf.classify("pip install requests") == CommandLevel.L2
    assert cf.classify("apt-get update") == CommandLevel.L2
    assert cf.classify("echo hello") == CommandLevel.L1


def test_filter_l1_auto():
    cf = CommandFilter()
    cf.l1_auto = True
    assert cf.filter("echo hi") == {"executable": True, "level": "L1"}


def test_filter_l2_needs_votes():
    cf = CommandFilter()
    cf.l2_threshold = 0.5
    assert cf.filter("pip install x", votes=[True, True])["executable"] is True
    assert cf.filter("pip install x", votes=[False])["executable"] is False
    assert cf.filter("pip install x")["executable"] is False


def test_filter_l3_blocked():
    cf = CommandFilter()
    cf.l3_block = True
    assert cf.filter("rm -rf /")["executable"] is False


def test_filter_l3_block_disabled():
    cf = CommandFilter()
    cf.l3_block = False
    assert cf.filter("rm -rf /")["executable"] is False


# ---------- 工具组装 ----------


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


# ---------- 供应链防火墙 ----------


def test_supply_firewall_blocklist():
    fw = SupplyChainFirewall()
    assert fw.check_install_command("pip install malicious-package") is False
    assert fw.check_install_command("pip install requests") is True
    assert fw.check_install_command("npm install evil-package") is False
    assert fw.check_install_command("apt install python3") is True


# ---------- 挖矿检测 ----------


def test_mining_detector_patterns():
    md = MiningDetector()
    assert md.scan_command_line("./xmrig -o stratum+tcp://pool.minexmr.com:4444") is True
    assert md.scan_command_line("python3 -u miner.py") is True
    assert md.scan_command_line("python3 print('hello')") is False


# ---------- 代码扫描 ----------


async def test_scanner_no_tool_degrades():
    result = await code_scanner.scan("print(1)", language="python")
    assert isinstance(result, list)