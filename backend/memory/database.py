# backend/memory/database.py
"""SQLite 存储：用户 + 记忆主体的元数据"""

import sqlite3
import uuid
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent.parent / "data" / "memory.db"
DB_PATH.parent.mkdir(parents=True, exist_ok=True)

_conn: sqlite3.Connection | None = None


def get_conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        _conn = sqlite3.connect(str(DB_PATH), check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _init_tables()
    return _conn


def _init_tables():
    conn = get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id       TEXT PRIMARY KEY,
            name          TEXT DEFAULT '',
            voiceprint    BLOB,
            first_seen_at TEXT,
            last_seen_at  TEXT,
            intimacy      INTEGER DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS memories (
            memory_id     TEXT PRIMARY KEY,
            user_id       TEXT NOT NULL,
            type          TEXT NOT NULL,      -- fact / event / emotion / reflection
            content       TEXT NOT NULL,
            importance    REAL DEFAULT 0.5,
            created_at    TEXT,
            last_accessed TEXT,
            access_count  INTEGER DEFAULT 0,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);
    """)
    conn.commit()


def _now() -> str:
    return datetime.now().isoformat()


# ========== 用户 ==========

def get_or_create_user(user_id: str, name: str = "") -> dict:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row:
        conn.execute(
            "UPDATE users SET last_seen_at = ? WHERE user_id = ?",
            (_now(), user_id),
        )
        conn.commit()
        return dict(row)

    conn.execute(
        "INSERT INTO users (user_id, name, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?)",
        (user_id, name, _now(), _now()),
    )
    conn.commit()
    return {"user_id": user_id, "name": name, "intimacy": 0}


# ========== 记忆 ==========

def insert_memory(user_id: str, mem_type: str, content: str, importance: float = 0.5) -> str:
    conn = get_conn()
    memory_id = str(uuid.uuid4())
    conn.execute(
        """INSERT INTO memories
           (memory_id, user_id, type, content, importance, created_at, last_accessed, access_count)
           VALUES (?, ?, ?, ?, ?, ?, ?, 0)""",
        (memory_id, user_id, mem_type, content, importance, _now(), _now()),
    )
    conn.commit()
    return memory_id


def get_memory(memory_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM memories WHERE memory_id = ?", (memory_id,)).fetchone()
    return dict(row) if row else None


def touch_memory(memory_id: str):
    """记录一次访问，影响时间衰减"""
    conn = get_conn()
    conn.execute(
        "UPDATE memories SET last_accessed = ?, access_count = access_count + 1 WHERE memory_id = ?",
        (_now(), memory_id),
    )
    conn.commit()


def list_memories(user_id: str, limit: int = 100) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT memory_id, user_id, type, content, importance, "
        "created_at, last_accessed, access_count "
        "FROM memories WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]