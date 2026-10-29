# backend/memory/database.py
"""SQLite 存储：用户 / 用户记忆 / AI 反思 / AI 行为 / 对话历史 / 反馈"""

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

        CREATE TABLE IF NOT EXISTS user_memories (
            memory_id        TEXT PRIMARY KEY,
            user_id          TEXT NOT NULL,
            subject_id       TEXT NOT NULL,
            type             TEXT NOT NULL,
            content          TEXT NOT NULL,
            scope            TEXT NOT NULL,
            source_id        TEXT NOT NULL,
            importance       REAL DEFAULT 0.5,
            created_at       TEXT NOT NULL,
            last_accessed    TEXT NOT NULL,
            access_count     INTEGER DEFAULT 0,
            decay_applied_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_um_user ON user_memories(user_id);
        CREATE INDEX IF NOT EXISTS idx_um_recent ON user_memories(scope, created_at);

        CREATE TABLE IF NOT EXISTS ai_reflections (
            reflection_id TEXT PRIMARY KEY,
            user_id       TEXT NOT NULL,
            content       TEXT NOT NULL,
            importance    REAL DEFAULT 0.8,
            evidence_ids  TEXT,
            created_at    TEXT NOT NULL,
            last_accessed TEXT NOT NULL,
            access_count  INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_ar_user ON ai_reflections(user_id);

        CREATE TABLE IF NOT EXISTS ai_behaviors (
            behavior_id   TEXT PRIMARY KEY,
            user_id       TEXT NOT NULL,
            content       TEXT NOT NULL,
            importance    REAL DEFAULT 0.7,
            source        TEXT NOT NULL,
            created_at    TEXT NOT NULL,
            last_accessed TEXT NOT NULL,
            access_count  INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_ab_user ON ai_behaviors(user_id);

        CREATE TABLE IF NOT EXISTS conversation_history (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id  TEXT NOT NULL,
            user_id     TEXT NOT NULL,
            role        TEXT NOT NULL,
            content     TEXT NOT NULL,
            created_at  TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_conv_session_user ON conversation_history(session_id, user_id, id);

        CREATE TABLE IF NOT EXISTS feedback (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            message_id   TEXT NOT NULL,
            session_id   TEXT NOT NULL,
            user_id      TEXT NOT NULL,
            user_message TEXT NOT NULL,
            ai_reply     TEXT NOT NULL,
            emotion      TEXT,
            tts_emotion  TEXT,
            rating       TEXT NOT NULL,
            created_at   TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_feedback_rating ON feedback(rating, created_at);
    """)

    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, name, first_seen_at, last_seen_at) "
        "VALUES ('ai_self', '渊鸢', ?, ?)",
        (_now(), _now()),
    )
    conn.commit()


def _now() -> str:
    return datetime.now().isoformat()


# ========== 用户 ==========

def get_or_create_user(user_id: str, name: str = "") -> dict:
    conn = get_conn()
    row = conn.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row:
        conn.execute("UPDATE users SET last_seen_at = ? WHERE user_id = ?", (_now(), user_id))
        conn.commit()
        return dict(row)
    conn.execute(
        "INSERT INTO users (user_id, name, first_seen_at, last_seen_at) VALUES (?, ?, ?, ?)",
        (user_id, name, _now(), _now()),
    )
    conn.commit()
    return {"user_id": user_id, "name": name, "intimacy": 0}


# ========== 用户记忆 ==========

def insert_user_memory(
    user_id: str,
    mem_type: str,
    content: str,
    importance: float = 0.5,
    subject_id: str | None = None,
    scope: str = "private",
    source_id: str | None = None,
) -> str:
    conn = get_conn()
    mid = str(uuid.uuid4())
    now = _now()
    conn.execute(
        """INSERT INTO user_memories
           (memory_id, user_id, subject_id, type, content, scope, source_id,
            importance, created_at, last_accessed, access_count, decay_applied_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?)""",
        (mid, user_id, subject_id or user_id, mem_type, content, scope,
         source_id or user_id, importance, now, now, now),
    )
    conn.commit()
    return mid


def get_user_memory(memory_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM user_memories WHERE memory_id = ?", (memory_id,)).fetchone()
    return dict(row) if row else None


def touch_user_memory(memory_id: str):
    conn = get_conn()
    conn.execute(
        "UPDATE user_memories SET last_accessed = ?, access_count = access_count + 1 WHERE memory_id = ?",
        (_now(), memory_id),
    )
    conn.commit()


def list_user_memories(user_id: str, limit: int = 100) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM user_memories WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def get_core_memories(user_id: str, limit: int = 5) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT memory_id, content, importance, scope, subject_id, created_at FROM user_memories "
        "WHERE user_id = ? AND type = 'fact' AND importance >= 0.6 "
        "ORDER BY importance DESC, created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def reinforce_user_memory(memory_id: str, delta: float, reset_decay: bool = True) -> tuple[float, float]:
    conn = get_conn()
    row = conn.execute("SELECT importance FROM user_memories WHERE memory_id = ?", (memory_id,)).fetchone()
    if not row:
        return 0.0, 0.0
    old_imp = row["importance"]
    new_imp = max(0.1, min(0.95, round(old_imp + delta, 3)))
    now = _now()
    if reset_decay:
        conn.execute(
            "UPDATE user_memories SET importance = ?, last_accessed = ?, decay_applied_at = ? WHERE memory_id = ?",
            (new_imp, now, now, memory_id),
        )
    else:
        conn.execute(
            "UPDATE user_memories SET importance = ?, last_accessed = ? WHERE memory_id = ?",
            (new_imp, now, memory_id),
        )
    conn.commit()
    return old_imp, new_imp


# ========== AI 反思 ==========

def insert_reflection(user_id: str, content: str, importance: float = 0.8, evidence_ids: str = "") -> str:
    conn = get_conn()
    rid = str(uuid.uuid4())
    now = _now()
    conn.execute(
        "INSERT INTO ai_reflections (reflection_id, user_id, content, importance, evidence_ids, created_at, last_accessed, access_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
        (rid, user_id, content, importance, evidence_ids, now, now),
    )
    conn.commit()
    return rid


def list_reflections(user_id: str, limit: int = 20) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM ai_reflections WHERE user_id = ? ORDER BY importance DESC, created_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


# ========== AI 行为经验 ==========

def insert_behavior(user_id: str, content: str, importance: float = 0.7, source: str = "user_feedback") -> str:
    conn = get_conn()
    bid = str(uuid.uuid4())
    now = _now()
    conn.execute(
        "INSERT INTO ai_behaviors (behavior_id, user_id, content, importance, source, created_at, last_accessed, access_count) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
        (bid, user_id, content, importance, source, now, now),
    )
    conn.commit()
    return bid


def list_behaviors(limit: int = 20) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM ai_behaviors ORDER BY importance DESC, created_at DESC LIMIT ?",
        (limit,),
    ).fetchall()
    return [dict(r) for r in rows]


# ========== 对话历史（短期记忆） ==========

def append_conversation(session_id: str, user_id: str, role: str, content: str):
    conn = get_conn()
    conn.execute(
        "INSERT INTO conversation_history (session_id, user_id, role, content, created_at) VALUES (?, ?, ?, ?, ?)",
        (session_id, user_id, role, content, _now()),
    )
    conn.commit()


def load_conversation(session_id: str, user_id: str, limit: int = 20) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT role, content FROM conversation_history "
        "WHERE session_id = ? AND user_id = ? ORDER BY id DESC LIMIT ?",
        (session_id, user_id, limit),
    ).fetchall()
    return [{"role": r["role"], "content": r["content"]} for r in reversed(rows)]


def load_recent_conversations(session_id: str, days: int = 3, limit: int = 40) -> list[dict]:
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conn = get_conn()
    rows = conn.execute(
        "SELECT c.user_id, c.role, c.content, c.created_at, u.name AS user_name "
        "FROM conversation_history c LEFT JOIN users u ON c.user_id = u.user_id "
        "WHERE c.session_id = ? AND c.created_at > ? ORDER BY c.id DESC LIMIT ?",
        (session_id, cutoff, limit),
    ).fetchall()
    return [dict(r) for r in reversed(rows)]


def purge_old_conversations(days: int = 3) -> int:
    from datetime import timedelta
    cutoff = (datetime.now() - timedelta(days=days)).isoformat()
    conn = get_conn()
    n = conn.execute("DELETE FROM conversation_history WHERE created_at < ?", (cutoff,)).rowcount
    conn.commit()
    return n


# ========== 反馈 ==========

def insert_feedback(
    message_id: str,
    session_id: str,
    user_id: str,
    user_message: str,
    ai_reply: str,
    emotion: str,
    tts_emotion: str,
    rating: str,
):
    conn = get_conn()
    conn.execute(
        "INSERT INTO feedback (message_id, session_id, user_id, user_message, ai_reply, emotion, tts_emotion, rating, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (message_id, session_id, user_id, user_message, ai_reply, emotion, tts_emotion, rating, _now()),
    )
    conn.commit()


def get_feedback_stats() -> dict:
    conn = get_conn()
    total = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
    good = conn.execute("SELECT COUNT(*) FROM feedback WHERE rating = 'good'").fetchone()[0]
    bad = conn.execute("SELECT COUNT(*) FROM feedback WHERE rating = 'bad'").fetchone()[0]
    return {"total": total, "good": good, "bad": bad}


def export_feedback_jsonl(filepath: str = "") -> int:
    """导出 good 反馈为训练用 JSONL"""
    import json
    if not filepath:
        filepath = str(Path(__file__).parent.parent / "training" / "feedback_good.jsonl")
    conn = get_conn()
    rows = conn.execute("SELECT * FROM feedback WHERE rating = 'good' ORDER BY created_at").fetchall()
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    with open(filepath, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps({
                "user_message": r["user_message"],
                "ai_reply": r["ai_reply"],
                "emotion": r["emotion"],
                "user_id": r["user_id"],
            }, ensure_ascii=False) + "\n")
    return len(rows)