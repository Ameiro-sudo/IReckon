import re
from typing import List, Optional
from loguru import logger
from app.core.config import config_manager


class SupplyChainFirewall:
    def __init__(self):
        self._pip_blacklist = [
            "malicious-package", "pycrypto-demo", "secrethash",
            "thisisafakedpy", "urllib", "requests-fake"
        ]
        self._npm_blacklist = [
            "evil-package", "node-stealer", "fake-react"
        ]
        custom_blacklist = config_manager.get("security.supply_chain_blacklist", {})
        self._pip_blacklist.extend(custom_blacklist.get("pip", []))
        self._npm_blacklist.extend(custom_blacklist.get("npm", []))

    def _extract_package_name(self, word: str) -> str:
        return re.split(r'[=<>~!;\[]', word)[0]

    def check_install_command(self, command: str) -> bool:
        parts = command.split()
        if "pip" in parts and "install" in parts:
            for word in parts:
                if word.startswith("-") or word in ("pip", "install"):
                    continue
                pkg = self._extract_package_name(word)
                if pkg in self._pip_blacklist:
                    logger.warning(f"供应链防火墙拦截 pip 包: {pkg}")
                    return False
        elif "npm" in parts and ("install" in parts or "i" in parts):
            for word in parts:
                if word.startswith("-") or word in ("npm", "install", "i"):
                    continue
                pkg = self._extract_package_name(word)
                if pkg in self._npm_blacklist:
                    logger.warning(f"供应链防火墙拦截 npm 包: {pkg}")
                    return False
        return True

    async def check(self, command: str) -> bool:
        return self.check_install_command(command)