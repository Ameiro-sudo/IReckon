import re
from loguru import logger


class MiningDetector:
    """挖矿检测：匹配矿机二进制特征与挖矿协议/矿池地址。"""

    def __init__(self):
        self.mining_patterns = [
            # 知名矿机/矿池
            r"\bxmrig\b",
            r"\bminerd\b",
            r"\bccminer\b",
            r"\bcpuminer\b",
            r"\bethminer\b",
            r"\bminergate\b",
            r"\bcgminer\b",
            r"\bbfgminer\b",
            r"\bnicehash\b",
            r"\bkawpow\b",
            r"\bcryptonight\b",
            # 知名矿机脚本/二进制文件名（含扩展名，避免误伤普通词 "miner"）
            r"\b(?:xmrig|minerd|ccminer|cpuminer|ethminer|cgminer|bfgminer|nheqminer)\.(?:py|pl|sh|rb|exe|bin)\b",
            r"\bminer\.(?:py|pl|sh|rb|exe)\b",
            # 挖矿协议与矿池地址
            r"stratum(?:\+tcp|\+ssl)?://",
            r"pool\.minexmr\.com",
            r"pool\.supportxmr\.com",
            r"nanopool\.org",
            r"ethermine\.org",
            r"f2pool\.com",
            # 典型挖矿参数组合（--algo + --url 指向矿池）
            r"--algo\s+\S+\s+--url\s+\S+",
        ]
        self.compiled = [re.compile(p, re.IGNORECASE) for p in self.mining_patterns]

    def scan_command_line(self, cmdline: str) -> bool:
        if not cmdline:
            return False
        for pattern in self.compiled:
            if pattern.search(cmdline):
                logger.warning(f"挖矿行为检测到: {cmdline[:200]}")
                return True
        return False

    async def scan_processes(self) -> list:
        """扫描本机进程命令行，返回命中挖矿特征的 (pid, cmdline) 列表。"""
        try:
            import psutil
        except ImportError:
            logger.debug("psutil 未安装，跳过进程扫描")
            return []
        hits = []
        for proc in psutil.process_iter(["pid", "cmdline"]):
            try:
                cmdline = " ".join(proc.info.get("cmdline") or [])
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                continue
            if cmdline and self.scan_command_line(cmdline):
                hits.append((proc.info["pid"], cmdline[:200]))
        return hits


mining_detector = MiningDetector()
