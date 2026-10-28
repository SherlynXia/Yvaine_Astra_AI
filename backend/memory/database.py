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
            memory_id        TEXT PRIMARY KEY,
            user_id          TEXT NOT NULL,
            type             TEXT NOT NULL,
            content          TEXT NOT NULL,
            importance       REAL DEFAULT 0.5,
            subject_id       TEXT,
            scope            TEXT DEFAULT 'private',
            source_id        TEXT,
            created_at       TEXT,
            last_accessed    TEXT,
            access_count     INTEGER DEFAULT 0,
            decay_applied_at TEXT,
            FOREIGN KEY (user_id) REFERENCES users(user_id)
        );

        CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);
        CREATE INDEX IF NOT EXISTS idx_memories_recent ON memories(scope, created_at);
    """)

    # 兼容老库：缺列就补
    _ensure_column(conn, "memories", "subject_id", "TEXT")
    _ensure_column(conn, "memories", "scope", "TEXT DEFAULT 'private'")
    _ensure_column(conn, "memories", "source_id", "TEXT")
    _ensure_column(conn, "memories", "decay_applied_at", "TEXT")

    conn.commit()


def _ensure_column(conn, table: str, column: str, ddl_type: str):
    cols = {r["name"] for r in conn.execute(f"PRAGMA table_info({table})")}
    if column not in cols:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")
        print(f"[DB] ✅ 已添加列: {table}.{column}", flush=True)


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

def insert_memory(
    user_id: str,
    mem_type: str,
    content: str,
    importance: float = 0.5,
    subject_id: str | None = None,
    scope: str = "private",
    source_id: str | None = None,
) -> str:
    conn = get_conn()
    memory_id = str(uuid.uuid4())
    now = _now()
    conn.execute(
        """INSERT INTO memories
           (memory_id, user_id, type, content, importance,
            subject_id, scope, source_id,
            created_at, last_accessed, access_count, decay_applied_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
        (
            memory_id, user_id, mem_type, content, importance,
            subject_id or user_id, scope, source_id or user_id,
            now, now, now,
        ),
    )
    conn.commit()
    return memory_id

def update_importance(memory_id: str, new_importance: float, decay_at: str):
    conn = get_conn()
    conn.execute(
        "UPDATE memories SET importance = ?, decay_applied_at = ? WHERE memory_id = ?",
        (new_importance, decay_at, memory_id),
    )
    conn.commit()


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

def get_core_memories(user_id: str, limit: int = 5) -> list[dict]:
    """取当前用户的核心身份记忆：fact 类型、importance >= 0.6"""
    conn = get_conn()
    rows = conn.execute(
        "SELECT memory_id, content, importance, scope, subject_id, created_at "
        "FROM memories "
        "WHERE user_id = ? AND type = 'fact' AND importance >= 0.6 "
        "AND type != 'invalidated' "
        "ORDER BY importance DESC, created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]