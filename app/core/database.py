"""
数据库模块
负责 SQLite 数据库的连接、加密和 CRUD 操作。
数据安全很重要，所以加了 Fernet 加密。
"""

import asyncio
import json
import os
import time
from pathlib import Path
from typing import Dict, Optional
import aiosqlite
from cryptography.fernet import Fernet  # 数据加密小能手～
from loguru import logger
from .config import config_manager


class Database:
    """
    数据库管理器 (单例模式～)
    用 SQLite 存数据，支持加密，线程安全！
    """

    _instance: Optional["Database"] = None

    def __new__(cls):
        """单例模式，全局只有一个数据库实例～"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self):
        if hasattr(self, "_init") and self._init:
            return
        self._init = True
        self._conn = None  # 数据库连接
        self._fernet = None  # 加密器
        self._write_lock = asyncio.Lock()  # 写操作锁
        self._connect_lock = asyncio.Lock()  # 连接锁
        self._query_cache: Dict[str, tuple] = {}  # 查询缓存
        self._cache_ttl = 30  # 缓存过期时间(秒)

        # 确定数据库文件位置～
        data_dir = Path(config_manager.get("system.data_dir", "./data"))
        db_dir = data_dir / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_dir / "ireckon.db"

    async def _get_cipher(self) -> Fernet:
        """
        获取或创建加密器～
        第一次会自动生成密钥，保存到 .key 文件里～
        """
        if self._fernet is None:
            key_path = Path(config_manager.get("system.data_dir", "./data")) / ".key"
            key_path.parent.mkdir(parents=True, exist_ok=True)

            # 读取现有密钥 or 生成新密钥～
            if key_path.exists():
                with open(key_path, "rb") as f:
                    key = f.read()
            else:
                key = Fernet.generate_key()
                with open(key_path, "wb") as f:
                    f.write(key)
                # 在 Linux/Mac 上设置权限为 600，保护密钥～
                if os.name == "posix":
                    try:
                        await asyncio.to_thread(key_path.chmod, 0o600)
                    except Exception:
                        pass

            self._fernet = Fernet(key)
        return self._fernet

    async def connect(self):
        """连接到数据库，创建表结构～"""
        async with self._connect_lock:
            if self._conn is not None:
                return

            # 配置数据库参数～
            journal = config_manager.get("database.journal_mode", "wal")
            timeout = config_manager.get("database.timeout", 5.0)

            self._conn = await aiosqlite.connect(
                str(self.db_path), timeout=timeout, isolation_level=None
            )
            await self._conn.execute(f"PRAGMA journal_mode={journal}")
            await self._conn.execute("PRAGMA foreign_keys = ON")

            # 创建表～
            await self._create_tables()
            logger.info(f"DB connected {self.db_path} (journal={journal})")

    async def _create_tables(self):
        """创建所有需要的表～"""
        await self._conn.executescript("""
            CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, user_request TEXT, status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, config_snapshot TEXT, output_dir TEXT);
            CREATE TABLE IF NOT EXISTS ai_instances (instance_id TEXT PRIMARY KEY, name TEXT, endpoint TEXT, model TEXT, api_key_encrypted TEXT, parameters TEXT, tags TEXT, cost_per_1k REAL, max_context INTEGER, enabled INTEGER);
            CREATE TABLE IF NOT EXISTS tool_parts (part_id TEXT PRIMARY KEY, name TEXT, description TEXT, language TEXT, code TEXT, input_schema TEXT, output_schema TEXT, tags TEXT, created_by TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS knowledge_entries (entry_id TEXT PRIMARY KEY, type TEXT, title TEXT, content TEXT, source TEXT, vector_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS conversation_messages (msg_id TEXT PRIMARY KEY, task_id TEXT, layer TEXT, sender_role TEXT, sender_id TEXT, content TEXT, metadata TEXT, timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (task_id) REFERENCES tasks(task_id));
            CREATE TABLE IF NOT EXISTS task_board_states (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT NOT NULL, state_json TEXT NOT NULL, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS usage_log (id INTEGER PRIMARY KEY AUTOINCREMENT, task_id TEXT, tokens INTEGER, cost REAL, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
            CREATE INDEX IF NOT EXISTS idx_messages_task_layer ON conversation_messages(task_id, layer, timestamp);
            CREATE INDEX IF NOT EXISTS idx_board_task ON task_board_states(task_id, updated_at);
            CREATE INDEX IF NOT EXISTS idx_usage_task ON usage_log(task_id, created_at);
        """)
        # 兼容旧库：tasks 表新增 title 列（AI 生成/截断的简短标题）
        try:
            await self._conn.execute("ALTER TABLE tasks ADD COLUMN title TEXT")
            logger.info("tasks 表已新增 title 列")
        except Exception:
            pass
        # 兼容旧库：tasks 表新增 file_refs 列（上传的参考文件）
        try:
            await self._conn.execute("ALTER TABLE tasks ADD COLUMN file_refs TEXT")
            logger.info("tasks 表已新增 file_refs 列")
        except Exception:
            pass
        await self._conn.commit()

    async def close(self):
        """关闭数据库连接～"""
        if self._conn:
            await self._conn.close()
            self._conn = None

    async def execute(self, sql, params=()):
        """执行 SQL（增删改）"""
        if self._conn is None:
            await self.connect()
        async with self._write_lock:
            async with self._conn.cursor() as cur:
                await cur.execute(sql, params)
                await self._conn.commit()
                self._invalidate_cache()
                return cur.lastrowid or 0

    async def fetch_one(self, sql, params=()):
        """查询单条记录～"""
        if self._conn is None:
            await self.connect()
        
        cache_key = f"{sql}:{params}"
        if cache_key in self._query_cache:
            cached_time, result = self._query_cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                return result
        
        async with self._conn.cursor() as cur:
            await cur.execute(sql, params)
            result = await cur.fetchone()
            self._query_cache[cache_key] = (time.time(), result)
            return result

    async def fetch_all(self, sql, params=()):
        """查询多条记录～"""
        if self._conn is None:
            await self.connect()
        
        cache_key = f"{sql}:{params}"
        if cache_key in self._query_cache:
            cached_time, result = self._query_cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                return result
        
        async with self._conn.cursor() as cur:
            await cur.execute(sql, params)
            result = await cur.fetchall()
            self._query_cache[cache_key] = (time.time(), result)
            return result

    def _invalidate_cache(self):
        """清空查询缓存"""
        self._query_cache.clear()

    async def save_ai_instance(self, instance: Dict):
        """
        保存 AI 实例（加密存储 API Key！）
        """
        cipher = await self._get_cipher()
        enc = (
            cipher.encrypt(instance.get("api_key", "").encode()).decode()
            if instance.get("api_key")
            else ""
        )
        await self.execute(
            "INSERT OR REPLACE INTO ai_instances(instance_id,name,endpoint,model,api_key_encrypted,parameters,tags,cost_per_1k,max_context,enabled) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                instance["id"],
                instance["name"],
                instance["endpoint"],
                instance["model"],
                enc,
                json.dumps(instance.get("parameters", {})),
                json.dumps(instance.get("tags", [])),
                instance.get("cost_per_1k_tokens", 0.0),
                instance.get("max_context", 4096),
                1 if instance.get("enabled", True) else 0,
            ),
        )

    async def get_ai_instance(self, iid):
        """获取单个 AI 实例（自动解密 API Key）"""
        row = await self.fetch_one(
            "SELECT * FROM ai_instances WHERE instance_id=?", (iid,)
        )
        if not row:
            return None
        try:
            cipher = await self._get_cipher()
            key = cipher.decrypt(row[4].encode()).decode() if row[4] else ""
        except Exception:
            key = ""
        return {
            "id": row[0],
            "name": row[1],
            "endpoint": row[2],
            "model": row[3],
            "api_key": key,
            "parameters": json.loads(row[5]),
            "tags": json.loads(row[6]),
            "cost_per_1k_tokens": row[7],
            "max_context": row[8],
            "enabled": bool(row[9]),
        }

    async def get_all_ai_instances(self, enabled_only=True):
        """获取所有 AI 实例～"""
        sql = "SELECT instance_id FROM ai_instances" + (  # nosec B608: 仅拼接常量字符串
            " WHERE enabled=1" if enabled_only else ""
        )
        rows = await self.fetch_all(sql)
        instances = []
        for (iid,) in rows:
            inst = await self.get_ai_instance(iid)
            if inst:
                instances.append(inst)
        return instances

    async def delete_task(self, task_id: str) -> None:
        """删除任务及其关联数据（消息、看板、用量记录）。"""
        for sql in (
            "DELETE FROM conversation_messages WHERE task_id=?",
            "DELETE FROM task_board_states WHERE task_id=?",
            "DELETE FROM usage_log WHERE task_id=?",
            "DELETE FROM tasks WHERE task_id=?",
        ):
            await self.execute(sql, (task_id,))

    async def add_usage(self, task_id: str, tokens: int, cost: float) -> None:
        await self.execute(
            "INSERT INTO usage_log(task_id,tokens,cost) VALUES(?,?,?)",
            (task_id, tokens, cost),
        )

    async def get_usage_summary(self) -> Dict:
        row = await self.fetch_one(
            "SELECT COALESCE(SUM(tokens),0), COALESCE(SUM(cost),0) FROM usage_log"
        )
        month = await self.fetch_one(
            "SELECT COALESCE(SUM(tokens),0), COALESCE(SUM(cost),0) FROM usage_log "
            "WHERE strftime('%Y-%m', created_at) = strftime('%Y-%m','now')"
        )
        by_task = await self.fetch_all(
            "SELECT task_id, SUM(tokens), SUM(cost) FROM usage_log GROUP BY task_id ORDER BY SUM(tokens) DESC LIMIT 20"
        )
        return {
            "total_tokens": row[0] if row else 0,
            "total_cost": round(row[1] if row else 0, 4),
            "month_tokens": month[0] if month else 0,
            "month_cost": round(month[1] if month else 0, 4),
            "by_task": [
                {"task_id": t, "tokens": tok, "cost": round(c, 4)}
                for t, tok, c in by_task
            ],
        }


# 全局数据库实例～
db = Database()
