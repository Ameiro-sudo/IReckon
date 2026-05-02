import asyncio, json, os
from pathlib import Path
from typing import Any, Dict, List, Optional
import aiosqlite
from cryptography.fernet import Fernet, InvalidToken
from loguru import logger
from .config import config_manager


class Database:
    _instance = None; _lock = asyncio.Lock()
    def __new__(cls):
        if cls._instance is None: cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self,"_init") and self._init: return
        self._init=True; self._conn=None; self._write_lock=asyncio.Lock(); self._connect_lock=asyncio.Lock(); self._fernet=None
        data_dir = Path(config_manager.get("system.data_dir","./data"))
        db_dir = data_dir / "db"; db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_dir / "ireckon.db"

    async def _get_cipher(self):
        if self._fernet is None:
            key_path = Path(config_manager.get("system.data_dir","./data")) / ".key"
            key_path.parent.mkdir(parents=True, exist_ok=True)
            if key_path.exists():
                with open(key_path,"rb") as f: key = f.read()
            else:
                key = Fernet.generate_key()
                with open(key_path,"wb") as f: f.write(key)
                if os.name=="posix":
                    try: key_path.chmod(0o600)
                    except: pass
            self._fernet = Fernet(key)
        return self._fernet

    async def connect(self):
        async with self._connect_lock:
            if self._conn is not None: return
            journal = config_manager.get("database.journal_mode","delete")
            timeout = config_manager.get("database.timeout",5.0)
            self._conn = await aiosqlite.connect(str(self.db_path), timeout=timeout, isolation_level=None)
            await self._conn.execute(f"PRAGMA journal_mode={journal}")
            await self._conn.execute("PRAGMA foreign_keys = ON")
            await self._create_tables()
            logger.info(f"DB connected {self.db_path} (journal={journal})")

    async def _create_tables(self):
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, user_request TEXT, status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, config_snapshot TEXT, output_dir TEXT);
            CREATE TABLE IF NOT EXISTS ai_instances (instance_id TEXT PRIMARY KEY, name TEXT, endpoint TEXT, model TEXT, api_key_encrypted TEXT, parameters TEXT, tags TEXT, cost_per_1k REAL, max_context INTEGER, enabled INTEGER);
            CREATE TABLE IF NOT EXISTS tool_parts (part_id TEXT PRIMARY KEY, name TEXT, description TEXT, language TEXT, code TEXT, input_schema TEXT, output_schema TEXT, tags TEXT, created_by TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS knowledge_entries (entry_id TEXT PRIMARY KEY, type TEXT, title TEXT, content TEXT, source TEXT, vector_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS conversation_messages (msg_id TEXT PRIMARY KEY, task_id TEXT, layer TEXT, sender_role TEXT, sender_id TEXT, content TEXT, metadata TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (task_id) REFERENCES tasks(task_id));
            CREATE TABLE IF NOT EXISTS task_board_states (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, state_json TEXT NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
        """)
        await self._conn.commit()

    async def close(self):
        if self._conn: await self._conn.close(); self._conn=None

    async def execute(self, sql, params=()):
        if self._conn is None: await self.connect()
        async with self._write_lock:
            async with self._conn.cursor() as cur:
                await cur.execute(sql, params); await self._conn.commit()
                return cur.lastrowid or 0

    async def fetch_one(self, sql, params=()):
        if self._conn is None: await self.connect()
        async with self._conn.cursor() as cur:
            await cur.execute(sql, params); return await cur.fetchone()

    async def fetch_all(self, sql, params=()):
        if self._conn is None: await self.connect()
        async with self._conn.cursor() as cur:
            await cur.execute(sql, params); return await cur.fetchall()

    async def save_ai_instance(self, instance: Dict):
        cipher = await self._get_cipher()
        enc = cipher.encrypt(instance.get("api_key","").encode()).decode() if instance.get("api_key") else ""
        await self.execute("INSERT OR REPLACE INTO ai_instances(instance_id,name,endpoint,model,api_key_encrypted,parameters,tags,cost_per_1k,max_context,enabled) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (instance["id"], instance["name"], instance["endpoint"], instance["model"], enc, json.dumps(instance.get("parameters",{})), json.dumps(instance.get("tags",[])), instance.get("cost_per_1k_tokens",0.0), instance.get("max_context",4096), 1 if instance.get("enabled",True) else 0))

    async def get_ai_instance(self, iid):
        row = await self.fetch_one("SELECT * FROM ai_instances WHERE instance_id=?",(iid,))
        if not row: return None
        try:
            cipher = await self._get_cipher()
            key = cipher.decrypt(row[4].encode()).decode() if row[4] else ""
        except: key=""
        return {"id":row[0],"name":row[1],"endpoint":row[2],"model":row[3],"api_key":key,"parameters":json.loads(row[5]),"tags":json.loads(row[6]),"cost_per_1k_tokens":row[7],"max_context":row[8],"enabled":bool(row[9])}

    async def get_all_ai_instances(self, enabled_only=True):
        sql = "SELECT instance_id FROM ai_instances" + (" WHERE enabled=1" if enabled_only else "")
        rows = await self.fetch_all(sql)
        instances = []
        for (iid,) in rows:
            inst = await self.get_ai_instance(iid)
            if inst: instances.append(inst)
        return instances

db = Database()
