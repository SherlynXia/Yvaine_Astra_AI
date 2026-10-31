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
            decay_applied_at TEXT NOT NULL,
            expires_at       TEXT
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
        CREATE TABLE IF NOT EXISTS workspace_topics (
            topic_id        TEXT PRIMARY KEY,
            user_id         TEXT NOT NULL,
            subject_ids     TEXT DEFAULT '[]',
            title           TEXT NOT NULL,
            summary         TEXT DEFAULT '',
            status          TEXT DEFAULT 'active',
            ttl_days        INTEGER DEFAULT 7,
            created_at      TEXT NOT NULL,
            last_touched_at TEXT NOT NULL,
            item_count      INTEGER DEFAULT 0
        );
        CREATE INDEX IF NOT EXISTS idx_wt_user ON workspace_topics(user_id, status, last_touched_at);
        CREATE INDEX IF NOT EXISTS idx_wt_recent ON workspace_topics(status, last_touched_at);

        CREATE TABLE IF NOT EXISTS workspace_items (
            item_id         TEXT PRIMARY KEY,
            topic_id        TEXT NOT NULL,
            item_type       TEXT DEFAULT 'setting',
            content         TEXT NOT NULL,
            created_at      TEXT NOT NULL,
            last_touched_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_wi_topic ON workspace_items(topic_id, created_at);

        CREATE TABLE IF NOT EXISTS ai_user_relationships (
            user_id           TEXT PRIMARY KEY,
            familiarity       REAL DEFAULT 0,
            trust             REAL DEFAULT 0,
            intimacy          REAL DEFAULT 0,
            stage             TEXT DEFAULT 'stranger',
            interaction_count INTEGER DEFAULT 0,
            positive_count    INTEGER DEFAULT 0,
            negative_count    INTEGER DEFAULT 0,
            last_interaction  TEXT,
            created_at        TEXT NOT NULL,
            updated_at        TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS user_user_relationships (
            relation_id   TEXT PRIMARY KEY,
            user_a        TEXT NOT NULL,
            user_b        TEXT NOT NULL,
            relation_type TEXT DEFAULT 'unknown',
            closeness     REAL DEFAULT 0,
            confidence    REAL DEFAULT 0,
            evidence      TEXT DEFAULT '',
            is_mutual     INTEGER DEFAULT 0,
            created_at    TEXT NOT NULL,
            updated_at    TEXT NOT NULL,
            UNIQUE(user_a, user_b)
        );
        CREATE INDEX IF NOT EXISTS idx_uu_a ON user_user_relationships(user_a);
        CREATE INDEX IF NOT EXISTS idx_uu_b ON user_user_relationships(user_b);
        
        CREATE TABLE IF NOT EXISTS relation_claims (
            claim_id         TEXT PRIMARY KEY,
            claimant_id      TEXT NOT NULL,
            target_id        TEXT NOT NULL,
            relation_type    TEXT NOT NULL,
            stated_closeness REAL DEFAULT 0.3,
            confidence       REAL DEFAULT 0.9,
            evidence         TEXT DEFAULT '',
            source           TEXT DEFAULT 'user_stated',
            created_at       TEXT NOT NULL,
            updated_at       TEXT NOT NULL,
            UNIQUE(claimant_id, target_id, source)
        );
        CREATE INDEX IF NOT EXISTS idx_rc_claimant ON relation_claims(claimant_id);
        CREATE INDEX IF NOT EXISTS idx_rc_target ON relation_claims(target_id);

    """)

    conn.execute(
        "INSERT OR IGNORE INTO users (user_id, name, first_seen_at, last_seen_at) "
        "VALUES ('ai_self', '渊鸢', ?, ?)",
        (_now(), _now()),
    )
    # 迁移：为旧库补 expires_at 列
    try:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(user_memories)").fetchall()]
        if "expires_at" not in cols:
            conn.execute("ALTER TABLE user_memories ADD COLUMN expires_at TEXT")
            print("[Memory] 🔧 迁移：user_memories 新增 expires_at 列", flush=True)
    except Exception as e:
        print(f"[Memory] ⚠️ 迁移 expires_at 失败: {e}", flush=True)

    # 迁移：为旧库补 user_user_relationships 的观察字段
    try:
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(user_user_relationships)").fetchall()]
        for col, ddl in [
            ("observed_sentiment", "ALTER TABLE user_user_relationships ADD COLUMN observed_sentiment REAL DEFAULT 0"),
            ("observed_mentions", "ALTER TABLE user_user_relationships ADD COLUMN observed_mentions INTEGER DEFAULT 0"),
        ]:
            if col not in cols:
                conn.execute(ddl)
                print(f"[Memory] 🔧 迁移：user_user_relationships 新增 {col} 列", flush=True)
    except Exception as e:
        print(f"[Memory] ⚠️ 迁移 user_user_relationships 失败: {e}", flush=True)

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
    expires_at: str | None = None,
) -> str:
    conn = get_conn()
    mid = str(uuid.uuid4())
    now = _now()
    conn.execute(
        """INSERT INTO user_memories
           (memory_id, user_id, subject_id, type, content, scope, source_id,
            importance, created_at, last_accessed, access_count, decay_applied_at, expires_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
        (mid, user_id, subject_id or user_id, mem_type, content, scope,
         source_id or user_id, importance, now, now, now, expires_at),
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

def purge_expired_memories() -> list[str]:
    """删除已过期的事件记忆（expires_at 已到），返回删除条数"""
    conn = get_conn()
    now = _now()
    rows = conn.execute(
        "SELECT memory_id FROM user_memories WHERE expires_at IS NOT NULL AND expires_at < ?",
        (now,),
    ).fetchall()
    if not rows:
        return []
    ids = [r["memory_id"] for r in rows]
    placeholders = ",".join("?" * len(ids))
    conn.execute(f"DELETE FROM user_memories WHERE memory_id IN ({placeholders})", ids)
    conn.commit()
    return ids   # 返回 id 列表，供上层同步删 Chroma

def update_memory_content(memory_id: str, content: str):
    """融合/追加时更新记忆正文"""
    conn = get_conn()
    conn.execute(
        "UPDATE user_memories SET content = ?, last_accessed = ? WHERE memory_id = ?",
        (content, _now(), memory_id),
    )
    conn.commit()

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

def decay_reflection(reflection_id: str, delta: float = 0.15) -> tuple[float, float]:
    """降低反思 importance（用于新旧反思冲突时衰减旧反思）"""
    conn = get_conn()
    row = conn.execute(
        "SELECT importance FROM ai_reflections WHERE reflection_id = ?", (reflection_id,)
    ).fetchone()
    if not row:
        return 0.0, 0.0
    old_imp = row["importance"]
    new_imp = max(0.0, round(old_imp - delta, 3))
    conn.execute(
        "UPDATE ai_reflections SET importance = ?, last_accessed = ? WHERE reflection_id = ?",
        (new_imp, _now(), reflection_id),
    )
    conn.commit()
    return old_imp, new_imp


def reinforce_reflection(reflection_id: str, delta: float = 0.05) -> tuple[float, float]:
    """提升反思 importance（用于相近反思的重复强化）"""
    conn = get_conn()
    row = conn.execute(
        "SELECT importance FROM ai_reflections WHERE reflection_id = ?", (reflection_id,)
    ).fetchone()
    if not row:
        return 0.0, 0.0
    old_imp = row["importance"]
    new_imp = min(1.0, round(old_imp + delta, 3))
    conn.execute(
        "UPDATE ai_reflections SET importance = ?, last_accessed = ?, access_count = access_count + 1 WHERE reflection_id = ?",
        (new_imp, _now(), reflection_id),
    )
    conn.commit()
    return old_imp, new_imp

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

# ========== 工作记忆 · 话题 ==========

def insert_workspace_topic(
    user_id: str,
    title: str,
    summary: str = "",
    subject_ids: list[str] | None = None,
    ttl_days: int = 7,
) -> str:
    import json
    conn = get_conn()
    tid = str(uuid.uuid4())
    now = _now()
    conn.execute(
        "INSERT INTO workspace_topics "
        "(topic_id, user_id, subject_ids, title, summary, status, ttl_days, created_at, last_touched_at, item_count) "
        "VALUES (?, ?, ?, ?, ?, 'active', ?, ?, ?, 0)",
        (tid, user_id, json.dumps(subject_ids or [user_id], ensure_ascii=False),
         title, summary, ttl_days, now, now),
    )
    conn.commit()
    return tid


def get_workspace_topic(topic_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM workspace_topics WHERE topic_id = ?", (topic_id,)).fetchone()
    return dict(row) if row else None


def list_active_topics(user_id: str, limit: int = 10) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM workspace_topics WHERE user_id = ? AND status = 'active' "
        "ORDER BY last_touched_at DESC LIMIT ?",
        (user_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def touch_workspace_topic(topic_id: str):
    conn = get_conn()
    conn.execute(
        "UPDATE workspace_topics SET last_touched_at = ?, item_count = item_count + 1 WHERE topic_id = ?",
        (_now(), topic_id),
    )
    conn.commit()


def update_topic_summary(topic_id: str, summary: str):
    conn = get_conn()
    conn.execute(
        "UPDATE workspace_topics SET summary = ?, last_touched_at = ? WHERE topic_id = ?",
        (summary, _now(), topic_id),
    )
    conn.commit()


def archive_workspace_topic(topic_id: str):
    conn = get_conn()
    conn.execute(
        "UPDATE workspace_topics SET status = 'archived' WHERE topic_id = ?",
        (topic_id,),
    )
    conn.commit()


def reactivate_workspace_topic(topic_id: str):
    conn = get_conn()
    conn.execute(
        "UPDATE workspace_topics SET status = 'active', last_touched_at = ? WHERE topic_id = ?",
        (_now(), topic_id),
    )
    conn.commit()


def list_stale_topics(now: str | None = None) -> list[dict]:
    """列出应归档的话题：last_touched_at + ttl_days < now"""
    from datetime import timedelta
    if now is None:
        now = _now()
    conn = get_conn()
    rows = conn.execute("SELECT * FROM workspace_topics WHERE status = 'active'").fetchall()
    stale = []
    now_dt = datetime.fromisoformat(now)
    for r in rows:
        try:
            last = datetime.fromisoformat(r["last_touched_at"])
        except Exception:
            continue
        if now_dt > last + timedelta(days=r["ttl_days"]):
            stale.append(dict(r))
    return stale


# ========== 工作记忆 · 素材 ==========

def insert_workspace_item(topic_id: str, content: str, item_type: str = "setting") -> str:
    conn = get_conn()
    iid = str(uuid.uuid4())
    now = _now()
    conn.execute(
        "INSERT INTO workspace_items (item_id, topic_id, item_type, content, created_at, last_touched_at) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (iid, topic_id, item_type, content, now, now),
    )
    conn.execute(
        "UPDATE workspace_topics SET last_touched_at = ?, item_count = item_count + 1 WHERE topic_id = ?",
        (now, topic_id),
    )
    conn.commit()
    return iid


def get_workspace_item(item_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute("SELECT * FROM workspace_items WHERE item_id = ?", (item_id,)).fetchone()
    return dict(row) if row else None


def list_workspace_items(topic_id: str, limit: int = 50) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM workspace_items WHERE topic_id = ? ORDER BY created_at ASC LIMIT ?",
        (topic_id, limit),
    ).fetchall()
    return [dict(r) for r in rows]


def touch_workspace_item(item_id: str):
    conn = get_conn()
    conn.execute(
        "UPDATE workspace_items SET last_touched_at = ? WHERE item_id = ?",
        (_now(), item_id),
    )
    conn.commit()

# ========== AI ↔ 用户关系 ==========

def get_or_create_ai_user_relationship(user_id: str) -> dict:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM ai_user_relationships WHERE user_id = ?", (user_id,)
    ).fetchone()
    if row:
        return dict(row)
    now = _now()
    conn.execute(
        "INSERT INTO ai_user_relationships (user_id, created_at, updated_at) VALUES (?, ?, ?)",
        (user_id, now, now),
    )
    conn.commit()
    return {
        "user_id": user_id, "familiarity": 0.0, "trust": 0.0, "intimacy": 0.0,
        "stage": "stranger", "interaction_count": 0,
        "positive_count": 0, "negative_count": 0, "last_interaction": None,
    }


def get_ai_user_relationship(user_id: str) -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM ai_user_relationships WHERE user_id = ?", (user_id,)
    ).fetchone()
    return dict(row) if row else None


def update_ai_user_relationship(user_id: str, **fields) -> None:
    """只更新指定字段，安全白名单"""
    allowed = {
        "familiarity", "trust", "intimacy", "stage",
        "interaction_count", "positive_count", "negative_count", "last_interaction",
    }
    updates = {k: v for k, v in fields.items() if k in allowed}
    if not updates:
        return
    updates["updated_at"] = _now()
    cols = ", ".join(f"{k} = ?" for k in updates)
    conn = get_conn()
    conn.execute(
        f"UPDATE ai_user_relationships SET {cols} WHERE user_id = ?",
        list(updates.values()) + [user_id],
    )
    conn.commit()


# ========== 用户 ↔ 用户关系 ==========

def _normalize_pair(uid1: str, uid2: str) -> tuple[str, str]:
    return (uid1, uid2) if uid1 <= uid2 else (uid2, uid1)


def get_user_user_relationship(uid1: str, uid2: str) -> dict | None:
    a, b = _normalize_pair(uid1, uid2)
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM user_user_relationships WHERE user_a = ? AND user_b = ?", (a, b)
    ).fetchone()
    return dict(row) if row else None


def upsert_user_user_relationship(
    uid1: str,
    uid2: str,
    relation_type: str,
    confidence: float,
    evidence: str = "",
    is_mutual: int = 0,
    allow_overwrite: bool = False,
    closeness: float | None = None,
) -> str:
    """建立/更新关系。

    - 同类型：confidence 取 max（多次确认强化）
    - 类型不同 / allow_overwrite=True：覆盖（关系升级/降级/修正）
    - closeness=None 时保留旧值（INSERT 时默认 0）
    """
    a, b = _normalize_pair(uid1, uid2)
    now = _now()
    conn = get_conn()
    row = conn.execute(
        "SELECT relation_id, relation_type, confidence, is_mutual, closeness "
        "FROM user_user_relationships "
        "WHERE user_a = ? AND user_b = ?",
        (a, b),
    ).fetchone()

    if row:
        old_type = row["relation_type"]
        old_conf = row["confidence"]
        old_closeness = row["closeness"] or 0.0
        new_mutual = 1 if (is_mutual or row["is_mutual"]) else 0

        # closeness：传入值优先，没传保留旧值
        new_closeness = closeness if closeness is not None else old_closeness

        if allow_overwrite or old_type != relation_type:
            # 覆盖：关系变更
            if old_type != relation_type:
                print(
                    f"[Relation] 🔄 关系变更: {old_type} → {relation_type} "
                    f"(conf {old_conf:.2f} → {confidence:.2f})",
                    flush=True,
                )
            conn.execute(
                "UPDATE user_user_relationships SET relation_type = ?, confidence = ?, "
                "closeness = ?, evidence = ?, is_mutual = ?, updated_at = ? WHERE relation_id = ?",
                (relation_type, confidence, new_closeness, evidence,
                 new_mutual, now, row["relation_id"]),
            )
        else:
            # 同类型：强化 confidence
            new_conf = max(old_conf, confidence)
            conn.execute(
                "UPDATE user_user_relationships SET confidence = ?, closeness = ?, "
                "evidence = ?, is_mutual = ?, updated_at = ? WHERE relation_id = ?",
                (new_conf, new_closeness, evidence, new_mutual, now, row["relation_id"]),
            )
        conn.commit()
        return row["relation_id"]

    rid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO user_user_relationships "
        "(relation_id, user_a, user_b, relation_type, closeness, confidence, evidence, "
        "is_mutual, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (rid, a, b, relation_type,
         closeness if closeness is not None else 0.0,
         confidence, evidence, 1 if is_mutual else 0, now, now),
    )
    conn.commit()
    return rid


def list_user_relations(user_id: str, min_confidence: float = 0.5) -> list[dict]:
    conn = get_conn()
    rows = conn.execute(
        "SELECT * FROM user_user_relationships "
        "WHERE (user_a = ? OR user_b = ?) AND confidence >= ? "
        "ORDER BY confidence DESC",
        (user_id, user_id, min_confidence),
    ).fetchall()
    return [dict(r) for r in rows]


def invalidate_user_user_relationship(uid1: str, uid2: str) -> int:
    """解除关系：双向删除所有声明 + 最终关系记录。"""
    a, b = _normalize_pair(uid1, uid2)
    conn = get_conn()

    # 1. 双向删除 claims（凛→夏凛、夏凛→凛）
    conn.execute(
        "DELETE FROM relation_claims WHERE "
        "(claimant_id = ? AND target_id = ?) OR (claimant_id = ? AND target_id = ?)",
        (a, b, b, a),
    )

    # 2. 删除最终关系记录
    n = conn.execute(
        "DELETE FROM user_user_relationships WHERE user_a = ? AND user_b = ?", (a, b)
    ).rowcount

    conn.commit()
    return n

# ========== 关系声明（单方） ==========

def upsert_relation_claim(
    claimant_id: str,
    target_id: str,
    relation_type: str,
    stated_closeness: float = 0.3,
    confidence: float = 0.9,
    evidence: str = "",
    source: str = "user_stated",
) -> str:
    """写入/更新一条单方声明。"""
    now = _now()
    conn = get_conn()
    row = conn.execute(
        "SELECT claim_id FROM relation_claims "
        "WHERE claimant_id = ? AND target_id = ? AND source = ?",
        (claimant_id, target_id, source),
    ).fetchone()
    if row:
        conn.execute(
            "UPDATE relation_claims SET relation_type = ?, stated_closeness = ?, "
            "confidence = ?, evidence = ?, updated_at = ? WHERE claim_id = ?",
            (relation_type, stated_closeness, confidence, evidence, now, row["claim_id"]),
        )
        conn.commit()
        return row["claim_id"]

    cid = str(uuid.uuid4())
    conn.execute(
        "INSERT INTO relation_claims "
        "(claim_id, claimant_id, target_id, relation_type, stated_closeness, "
        "confidence, evidence, source, created_at, updated_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (cid, claimant_id, target_id, relation_type, stated_closeness,
         confidence, evidence, source, now, now),
    )
    conn.commit()
    return cid


def get_relation_claim(claimant_id: str, target_id: str, source: str = "user_stated") -> dict | None:
    conn = get_conn()
    row = conn.execute(
        "SELECT * FROM relation_claims WHERE claimant_id = ? AND target_id = ? AND source = ?",
        (claimant_id, target_id, source),
    ).fetchone()
    return dict(row) if row else None


def delete_relation_claims(uid1: str, uid2: str) -> int:
    """解除关系时，双向删除所有声明。"""
    conn = get_conn()
    n = conn.execute(
        "DELETE FROM relation_claims WHERE "
        "(claimant_id = ? AND target_id = ?) OR (claimant_id = ? AND target_id = ?)",
        (uid1, uid2, uid2, uid1),
    ).rowcount
    conn.commit()
    return n


# ========== 观察信号 ==========

def update_observed_sentiment(uid1: str, uid2: str, sentiment: float) -> None:
    """记录一次"提到对方"的观察，滑动平均更新情感值。"""
    a, b = _normalize_pair(uid1, uid2)
    conn = get_conn()
    now = _now()
    row = conn.execute(
        "SELECT relation_id, observed_sentiment, observed_mentions "
        "FROM user_user_relationships WHERE user_a = ? AND user_b = ?",
        (a, b),
    ).fetchone()
    if not row:
        # 还没有关系记录，先建一条占位
        rid = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO user_user_relationships "
            "(relation_id, user_a, user_b, relation_type, closeness, confidence, "
            "observed_sentiment, observed_mentions, created_at, updated_at) "
            "VALUES (?, ?, ?, 'unknown', 0, 0, ?, 1, ?, ?)",
            (rid, a, b, sentiment, now, now),
        )
    else:
        # 滑动平均：0.8×旧 + 0.2×新
        new_sentiment = row["observed_sentiment"] * 0.8 + sentiment * 0.2
        conn.execute(
            "UPDATE user_user_relationships SET observed_sentiment = ?, "
            "observed_mentions = observed_mentions + 1, updated_at = ? "
            "WHERE relation_id = ?",
            (new_sentiment, now, row["relation_id"]),
        )
    conn.commit()


def get_observed(uid1: str, uid2: str) -> tuple[float, int]:
    """返回 (observed_sentiment, observed_mentions)。无记录时 (0.0, 0)。"""
    a, b = _normalize_pair(uid1, uid2)
    conn = get_conn()
    row = conn.execute(
        "SELECT observed_sentiment, observed_mentions "
        "FROM user_user_relationships WHERE user_a = ? AND user_b = ?",
        (a, b),
    ).fetchone()
    if not row:
        return 0.0, 0
    return row["observed_sentiment"] or 0.0, row["observed_mentions"] or 0