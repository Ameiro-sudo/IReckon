import re
from pathlib import Path
from loguru import logger
from app.core.config import config_manager


class SupplyChainFirewall:
    """供应链防火墙：解析 pip/npm/yarn/pnpm/uv/poetry/conda 安装命令并匹配包黑名单。"""

    _PIP_INSTALL_RE = re.compile(
        r"(?:^|\s)(?:python(?:3|2)?\s+-m\s+pip|pip3?|pipx|uv\s+pip|poetry|conda)\s+"
        r"(?:install|add|i)\b",
        re.IGNORECASE,
    )
    _NPM_INSTALL_RE = re.compile(
        r"(?:^|\s)(?:npm|yarn|pnpm|npx)\s+(?:install|add|i)\b",
        re.IGNORECASE,
    )

    def __init__(self):
        self._pip_blacklist = [
            "malicious-package",
            "pycrypto-demo",
            "secrethash",
            "thisisafakedpy",
            "urllib",
            "requests-fake",
        ]
        self._npm_blacklist = ["evil-package", "node-stealer", "fake-react"]
        custom_blacklist = config_manager.get("security.supply_chain_blacklist", {})
        self._pip_blacklist.extend(
            str(p).lower() for p in custom_blacklist.get("pip", [])
        )
        self._npm_blacklist.extend(
            str(p).lower() for p in custom_blacklist.get("npm", [])
        )
        self._pip_blacklist = list(dict.fromkeys(self._pip_blacklist))
        self._npm_blacklist = list(dict.fromkeys(self._npm_blacklist))

    @staticmethod
    def _extract_package_name(word: str) -> str:
        """从 token 中提取包名：去引号、去版本约束、去 @scope/@version 前缀。"""
        w = word.strip().strip("'\"")
        if not w:
            return ""
        # git+https://host/owner/repo.git 或 url 形式 → 取 repo 名
        if "://" in w or w.startswith("git+"):
            m = re.search(r"/([^/]+?)(?:\.git)?$", w.split("#")[0])
            return (m.group(1) if m else w).lower()
        # @scope/name@version 或 name@version
        if w.startswith("@"):
            m = re.match(r"@[^/]+/([^@/\s]+)", w)
            if m:
                return m.group(1).lower()
        # 去版本约束（= < > ~ ! ; [ ）与 @version
        base = re.split(r"[=<>~!;\[@]", w)[0]
        return base.lower()

    def _check_packages(self, tokens: list, blacklist: list, kind: str) -> bool:
        # 跳过包管理器命令本身与选项
        skip = {"install", "add", "i", "-r", "--requirement", "-e", "--editable"}
        for word in tokens:
            if word.startswith("-") or word in skip:
                continue
            pkg = self._extract_package_name(word)
            if pkg in blacklist:
                logger.warning(f"供应链防火墙拦截 {kind} 包: {pkg}")
                return False
        return True

    def check_install_command(self, command: str) -> bool:
        if not command or not command.strip():
            return True
        stripped = command.strip()

        # 词法切分（容忍引号包裹的包名）
        try:
            import shlex

            tokens = shlex.split(stripped, posix=True)
        except ValueError:
            tokens = stripped.split()

        is_pip = bool(self._PIP_INSTALL_RE.search(stripped))
        is_npm = bool(self._NPM_INSTALL_RE.search(stripped))
        if not is_pip and not is_npm:
            return True

        # pip install -r requirements.txt：递归检查依赖清单
        for i, tok in enumerate(tokens):
            if tok in ("-r", "--requirement") and i + 1 < len(tokens):
                req_file = tokens[i + 1]
                try:
                    p = Path(req_file)
                    if p.exists():
                        for line in p.read_text(
                            encoding="utf-8", errors="replace"
                        ).splitlines():
                            line = line.strip()
                            if not line or line.startswith(("#", "-", "git+")):
                                if line.startswith("git+") and not self._check_packages(
                                    [line], self._pip_blacklist, "pip"
                                ):
                                    return False
                                continue
                            if self._extract_package_name(line) in self._pip_blacklist:
                                logger.warning(
                                    f"供应链防火墙拦截 requirements 中的 pip 包: {line}"
                                )
                                return False
                    else:
                        # 文件不存在按保守处理：拒绝该 -r 引用
                        logger.warning(
                            f"供应链防火墙：无法读取依赖清单 {req_file}，拒绝执行"
                        )
                        return False
                except Exception as e:
                    logger.warning(f"供应链防火墙：读取依赖清单失败 {req_file}: {e}")
                    return False

        if is_pip:
            return self._check_packages(tokens, self._pip_blacklist, "pip")
        return self._check_packages(tokens, self._npm_blacklist, "npm")

    async def check(self, command: str) -> bool:
        return self.check_install_command(command)


supply_firewall = SupplyChainFirewall()
