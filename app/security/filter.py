"""
命令分层过滤：L1 自动执行 / L2 共识投票 / L3 严格拦截。

使用 shlex 词法解析 + token 级匹配，拒绝 shell 元字符组合与混淆绕过。
"""

import re
import shlex
from enum import Enum
from typing import List, Dict, Any, Optional, Tuple
from app.core.config import config_manager


class CommandLevel(Enum):
    L1 = 1
    L2 = 2
    L3 = 3


# 绝对禁止的 shell 元字符/构造（出现在任意 token 即 L3）
_FORBIDDEN_SUBSTRINGS = [
    "$(",
    "${",
    "`",
    "&&",
    "||",
    ";",
    "|",
    ">",
    "<",
]

# 危险命令（无论参数如何拆分都拦截）
_DANGEROUS_COMMANDS = {
    "rm",
    "mkfs",
    "dd",
    "shutdown",
    "reboot",
    "poweroff",
    "halt",
    "kill",
    "killall",
    "pkill",
    "chmod",
    "chown",
    "mkfs.ext4",
    "mkfs.ext3",
    "mkfs.ext2",
    "mkfs.xfs",
    "parted",
    "fdisk",
    "pvcreate",
    "vgcreate",
    "lvcreate",
    "iptables",
    "ufw",
    "mount",
    "umount",
}

# 直接执行代码的解释器模式（可绕过静态黑名单）
_EXEC_INTERPRETERS = {
    "python",
    "python3",
    "python2",
    "perl",
    "ruby",
    "php",
    "node",
    "bash",
    "sh",
    "zsh",
    "ksh",
    "fish",
}

# 已知混淆/传递执行的关键词
_FORBIDDEN_KEYWORDS = {
    "base64",
    "eval",
    "exec",
    "system",
    "popen",
    "subprocess",
    "os.system",
    "curl",
    "wget",
    "nc",
    "ncat",
    "socat",
    "telnet",
    "ssh",
    "scp",
    "ftp",
    "wget",
    "mkfifo",
    "mknod",
}

# 资源密集型命令（默认 L2，需投票或降级确认）
_RESOURCE_HEAVY_COMMANDS = {
    "pip",
    "pip3",
    "npm",
    "apt",
    "apt-get",
    "aptitude",
    "yum",
    "dnf",
    "docker",
    "systemctl",
    "service",
    "git",
    "make",
    "cmake",
    "gcc",
    "g++",
    "cc",
}


def _normalize(command: str) -> str:
    r"""归一化输入：去除反斜杠转义与重复空白，防 `r\m -rf /` 一类混淆。"""
    # 处理反斜杠转义（\x → x）
    cmd = re.sub(r"\\(.)", r"\1", command)
    # 处理 $IFS 分隔（$IFS → 空白）
    cmd = re.sub(r"\$IFS", " ", cmd)
    # 换行与制表符 → 空白
    cmd = cmd.replace("\n", " ").replace("\t", " ")
    # 连续空白合并（token 语义不受影响，避免空 token 干扰）
    return re.sub(r"\s+", " ", cmd).strip()


class CommandFilter:
    def __init__(self):
        self.l1_auto = config_manager.get(
            "security.local_command_levels.L1_auto_exec", True
        )
        self.l2_threshold = config_manager.get(
            "security.local_command_levels.L2_vote_threshold", 0.5
        )
        self.l3_block = config_manager.get(
            "security.local_command_levels.L3_block", True
        )

    def _tokenize(self, command: str) -> List[str]:
        """shlex 词法解析；解析失败（未闭合引号等）按不信任处理：返回原串分割。"""
        try:
            return shlex.split(command, posix=True)
        except ValueError:
            return command.split()

    def _classify_detail(self, command: str) -> Tuple[CommandLevel, str]:
        cmd = _normalize(command)
        if not cmd:
            return CommandLevel.L1, "空命令"

        tokens = self._tokenize(cmd)
        if not tokens:
            return CommandLevel.L1, "无可执行 token"

        joined = " ".join(tokens).lower()

        # 1) shell 元字符/注入构造 → L3
        for bad in _FORBIDDEN_SUBSTRINGS:
            if bad in joined:
                return CommandLevel.L3, f"包含 shell 元字符: {bad}"

        # 2) 危险命令 → L3
        for tok in tokens:
            base = tok.lower().lstrip("-")
            if base in _DANGEROUS_COMMANDS:
                return CommandLevel.L3, f"危险命令: {tok}"
            # 禁止 rm/mv 等带 -rf / 的破坏性组合（-rf 拆成 -r -f 也拦）
            if base == "rm" or base.startswith("rm"):
                rest = [t for t in tokens if t != tok]
                flags = "".join(t.lower().lstrip("-") for t in rest if t.startswith("-"))
                if "r" in flags and ("f" in flags or "i" in flags):
                    return CommandLevel.L3, "递归强制删除被拦截"

        # 3) 直接执行代码的解释器模式 → L3
        for tok in tokens:
            base = tok.lower()
            if base in _EXEC_INTERPRETERS:
                rest = [t for t in tokens if t != tok]
                if rest and rest[0] in ("-c", "-e", "-m", "-f"):
                    return CommandLevel.L3, f"解释器直接执行代码: {tok} {rest[0]}"

        # 4) 混淆/传递执行关键词 → L3
        for kw in _FORBIDDEN_KEYWORDS:
            if re.search(rf"(^|\s){re.escape(kw)}(\s|$)", joined):
                return CommandLevel.L3, f"禁止关键词: {kw}"

        # 5) 资源密集型命令 → L2
        for tok in tokens:
            base = tok.lower()
            if base in _RESOURCE_HEAVY_COMMANDS:
                return CommandLevel.L2, f"资源密集型命令: {tok}"

        # 6) shutdown/reboot 等系统操作按 token 精确匹配（不在上面集合时补兜底）
        if any(t.lower().lstrip("-") in ("shutdown", "reboot", "poweroff") for t in tokens):
            return CommandLevel.L3, "系统电源操作被拦截"

        return CommandLevel.L1, "常规命令"

    def classify(self, command: str) -> CommandLevel:
        """分级：L1 常规 / L2 资源密集 / L3 危险。"""
        level, _reason = self._classify_detail(command)
        return level

    def filter(
        self, command: str, votes: Optional[List[bool]] = None
    ) -> Dict[str, Any]:
        level, reason = self._classify_detail(command)
        if level == CommandLevel.L1:
            if self.l1_auto:
                return {"executable": True, "level": "L1"}
            return {"executable": False, "level": "L1"}
        if level == CommandLevel.L2:
            # L2 必须由投票决定；无投票默认拒绝
            if votes and sum(votes) / len(votes) >= self.l2_threshold:
                return {"executable": True, "level": "L2"}
            return {"executable": False, "level": "L2"}
        # L3 一律拦截（不随配置放行）
        return {"executable": False, "level": "L3", "reason": reason}


command_filter = CommandFilter()