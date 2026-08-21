import re
from pathlib import Path
from loguru import logger

from app.core.config import get


class SupplyChainFirewall:
    """供应链防火墙：解析 pip/npm/yarn/pnpm/uv/poetry/conda 安装命令并匹配包黑名单。"""

    _PIP_INSTALL_RE = re.compile(
        r"(?:^|\s)(?:python[32]?\s+-m\s+pip|pip3?|pipx|uv\s+pip|poetry|conda)\s+"
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
        custom = get("security.supply_chain_blacklist", {}) or {}
        self._pip_blacklist.extend(str(p).lower() for p in custom.get("pip", []))
        self._npm_blacklist.extend(str(p).lower() for p in custom.get("npm", []))
        # PEP 503 规范化：requests_fake / requests.fake / requests-fake 视为同一包
        self._pip_blacklist = list(
            dict.fromkeys(self._normalize_pip_name(p) for p in self._pip_blacklist)
        )
        self._npm_blacklist = list(dict.fromkeys(self._npm_blacklist))

    @staticmethod
    def _normalize_pip_name(name: str) -> str:
        """PEP 503 包名规范化：小写 + 连续 -/_/. 归一为单个 -。"""
        return re.sub(r"[-_.]+", "-", name.strip()).lower()

    @staticmethod
    def _extract_package_name(word: str) -> str:
        """从 token 中提取包名：去引号、去版本约束、去 @scope/@version 前缀。"""
        w = word.strip().strip("'\"")
        if not w:
            return ""
        # git+https://host/owner/repo.git 或 URL/wheel 直装形式
        if "://" in w or w.startswith("git+"):
            path = w.split("#")[0].split("?")[0]
            fname = re.sub(r"^.*/", "", path)
            # wheel/sdist 文件名（dist-1.0-py3-none-any.whl）→ 取首段 dist 名
            base = re.sub(r"\.(whl|tar\.gz|zip|egg)$", "", fname, flags=re.IGNORECASE)
            if base != fname:
                return SupplyChainFirewall._normalize_pip_name(base.split("-")[0])
            m = re.search(r"/([^/]+?)(?:\.git)?$", path)
            return SupplyChainFirewall._normalize_pip_name(m.group(1) if m else w)
        # @scope/name@version 或 name@version
        if w.startswith("@"):
            m = re.match(r"@[^/]+/([^@/\s]+)", w)
            if m:
                return m.group(1).lower()
        # 去版本约束（= < > ~ ! ; [ ）与 @version
        base = re.split(r"[=<>~!;\[@]", w)[0]
        return SupplyChainFirewall._normalize_pip_name(base)

    def _check_packages(self, tokens: list, blacklist: list, kind: str) -> bool:
        # 跳过包管理器命令本身与选项
        skip = {"install", "add", "i", "-r", "--requirement"}
        for word in tokens:
            if word.startswith("-") or word in skip:
                continue
            pkg = self._extract_package_name(word)
            if pkg in blacklist:
                logger.warning(f"供应链防火墙拦截 {kind} 包: {pkg}")
                return False
        return True

    def _check_requirements_line(self, line: str) -> bool:
        """检查 requirements 单行：含 -e/--editable 与 http 明文源拦截。"""
        line = line.strip()
        if not line or line.startswith("#"):
            return True
        if line.startswith("-"):
            parts = line.split(None, 1)
            flag = parts[0].lower()
            arg = parts[1].strip() if len(parts) > 1 else ""
            if flag in ("-e", "--editable"):
                # 可编辑安装同样指向具体包/仓库，必须纳入黑名单检查
                return self._check_packages([arg], self._pip_blacklist, "pip")
            if flag in ("-i", "--index-url", "--extra-index-url"):
                # 明文 http 源可被中间人投毒，直接拒绝；https 镜像放行
                if arg.startswith("http://"):
                    logger.warning(f"供应链防火墙：拒绝明文 HTTP 包索引源: {arg}")
                    return False
                return True
            # 其余选项行（--trusted-host 等）不携带包名，放行
            return True
        if self._extract_package_name(line) in self._pip_blacklist:
            logger.warning(f"供应链防火墙拦截 requirements 中的 pip 包: {line}")
            return False
        return True

    def check_install_command(self, command: str) -> bool:
        if not command or not command.strip():
            return True
        stripped = command.strip()

        # 词法切分（容忍引号包裹的包名）。
        # Windows 下必须用非 posix 模式：posix 会把路径反斜杠当转义符吞掉，
        # 导致 `pip install -r C:\path\reqs.txt` 的清单被误判不存在而拒绝。
        try:
            import os
            import shlex

            tokens = shlex.split(stripped, posix=os.name != "nt")
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
                        for raw_line in p.read_text(
                            encoding="utf-8", errors="replace"
                        ).splitlines():
                            line = raw_line.strip()
                            if not self._check_requirements_line(line):
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
