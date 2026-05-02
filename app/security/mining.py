import re
from typing import List
from loguru import logger


class MiningDetector:
    def __init__(self):
        self.mining_patterns = [
            r"pool\.minexmr\.com",
            r"stratum\+tcp://",
            r"xmrig",
            r"minergate",
            r"cryptonight",
            r"ethminer",
            r"cpuminer",
            r"cgminer",
            r"bfgminer",
            r"-u\s+\w+\.\w+",
        ]
        self.compiled = [re.compile(p, re.IGNORECASE) for p in self.mining_patterns]

    def scan_command_line(self, cmdline: str) -> bool:
        for pattern in self.compiled:
            if pattern.search(cmdline):
                logger.warning(f"挖矿行为检测到: {cmdline}")
                return True
        return False

    async def scan_processes(self, process_list: List[str]) -> bool:
        for proc_info in process_list:
            if self.scan_command_line(proc_info):
                return True
        return False


mining_detector = MiningDetector()
