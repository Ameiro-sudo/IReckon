from enum import Enum
from typing import List, Dict, Any
from loguru import logger
from app.core.config import config_manager

class CommandLevel(Enum): L1=1; L2=2; L3=3

class CommandFilter:
    def __init__(self):
        self.l1_auto = config_manager.get("security.local_command_levels.L1_auto_exec",True)
        self.l2_threshold = config_manager.get("security.local_command_levels.L2_vote_threshold",0.5)
        self.l3_block = config_manager.get("security.local_command_levels.L3_block",True)

    def classify(self, command: str) -> CommandLevel:
        dangerous = ["rm -rf","mkfs","dd if=",":(){ :|:& };:","chmod 777","> /dev/sda","shutdown","reboot"]
        for d in dangerous:
            if d in command: return CommandLevel.L3
        resource_heavy = ["pip install","npm install","apt-get","yum","docker run","systemctl","curl","wget"]
        for r in resource_heavy:
            if r in command: return CommandLevel.L2
        return CommandLevel.L1

    def filter(self, command: str, votes: List[bool]=None) -> Dict[str, Any]:
        level = self.classify(command)
        if level==CommandLevel.L1 and self.l1_auto: return {"executable":True,"level":"L1"}
        if level==CommandLevel.L2:
            if votes and sum(votes)/len(votes)>=self.l2_threshold: return {"executable":True,"level":"L2"}
            return {"executable":False,"level":"L2"}
        if level==CommandLevel.L3 and self.l3_block: return {"executable":False,"level":"L3"}
        return {"executable":False}

command_filter = CommandFilter()