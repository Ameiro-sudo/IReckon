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
from app.core.config import get


def _open_connection(*args, **kwargs) -> aiosqlite.Connection:
    """创建 aiosqlite 连接，并提前把后台工作线程标记为 daemon。

    aiosqlite 0.21+ 的工作线程非 daemon，连接未关闭时解释器退出会卡在
    线程回收阶段（先于 atexit 回调）；标记 daemon 后进程退出不再被阻塞。
    必须在 await 启动线程之前设置，之后设置会抛 RuntimeError。
    """
    conn = aiosqlite.connect(*args, **kwargs)
    conn._thread.daemon = True
    return conn


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
        data_dir = Path(get("system.data_dir", "./data"))
        db_dir = data_dir / "db"
        db_dir.mkdir(parents=True, exist_ok=True)
        self.db_path = db_dir / "ireckon.db"

    async def _get_cipher(self) -> Fernet:
        """
        获取或创建加密器～
        第一次会自动生成密钥，保存到 .key 文件里～
        """
        if self._fernet is None:
            key_path = Path(get("system.data_dir", "./data")) / ".key"
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
            journal = get("database.journal_mode", "wal")
            timeout = get("database.timeout", 5.0)

            self._conn = await _open_connection(
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
            CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, user_request TEXT, status TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP, config_snapshot TEXT, output_dir TEXT, budget_limit_usd REAL);
            CREATE TABLE IF NOT EXISTS ai_instances (instance_id TEXT PRIMARY KEY, name TEXT, endpoint TEXT, model TEXT, api_key_encrypted TEXT, parameters TEXT, tags TEXT, cost_per_1k REAL, max_context INTEGER, enabled INTEGER);
            CREATE TABLE IF NOT EXISTS tool_parts (part_id TEXT PRIMARY KEY, name TEXT, description TEXT, language TEXT, code TEXT, input_schema TEXT, output_schema TEXT, tags TEXT, created_by TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS knowledge_entries (entry_id TEXT PRIMARY KEY, type TEXT, title TEXT, content TEXT, source TEXT, vector_id TEXT, created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP);
            CREATE TABLE IF NOT EXISTS conversation_messages (msg_id TEXT PRIMARY KEY, task_id TEXT, layer TEXT, sender_role TEXT, sender_id TEXT, content TEXT, metadata TEXT, msg_type TEXT DEFAULT 'text', timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (task_id) REFERENCES tasks(task_id));
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
        # 兼容旧库：tasks 表新增 budget_limit_usd 列（任务级美元预算）
        try:
            await self._conn.execute(
                "ALTER TABLE tasks ADD COLUMN budget_limit_usd REAL"
            )
            logger.info("tasks 表已新增 budget_limit_usd 列")
        except Exception:
            pass
        # 兼容旧库：conversation_messages 表新增 msg_type 列（消息类型标记）
        try:
            await self._conn.execute(
                "ALTER TABLE conversation_messages ADD COLUMN msg_type TEXT DEFAULT 'text'"
            )
            logger.info("conversation_messages 表已新增 msg_type 列")
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
        """查询单条记录（缓存命中时返回元组快照，避免可变对象被外部污染）"""
        if self._conn is None:
            await self.connect()

        cache_key = f"{sql}:{params}"
        if cache_key in self._query_cache:
            cached_time, result = self._query_cache[cache_key]
            if time.time() - cached_time < self._cache_ttl:
                return result

        async with self._conn.cursor() as cur:
            await cur.execute(sql, params)
            row = await cur.fetchone()
            result = tuple(row) if row is not None else None
            self._query_cache[cache_key] = (time.time(), result)
            return result

    async def fetch_all(self, sql, params=()):
        """查询多条记录（不做缓存，避免 30s 一致性窗口内的脏读）"""
        if self._conn is None:
            await self.connect()

        async with self._conn.cursor() as cur:
            await cur.execute(sql, params)
            return await cur.fetchall()

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
        except Exception as e:
            logger.warning(f"AI 实例 {iid} API Key 解密失败，已置空: {e}")
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
        """删除任务及其关联数据（消息、看板、用量记录），单事务保证原子性。"""
        if self._conn is None:
            await self.connect()
        async with self._write_lock:
            try:
                await self._conn.execute("BEGIN")
                for sql in (
                    "DELETE FROM conversation_messages WHERE task_id=?",
                    "DELETE FROM task_board_states WHERE task_id=?",
                    "DELETE FROM usage_log WHERE task_id=?",
                    "DELETE FROM tasks WHERE task_id=?",
                ):
                    await self._conn.execute(sql, (task_id,))
                await self._conn.execute("COMMIT")
            except Exception:
                try:
                    await self._conn.execute("ROLLBACK")
                except Exception:
                    pass
                raise
            finally:
                self._invalidate_cache()

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
