"""表结构重构：memories 按 type 分流到 user_memories / ai_reflections / ai_behaviors"""
import json
import sqlite3
from pathlib import Path
from datetime import datetime

DB_PATH = Path(__file__).parent / "data" / "memory.db"
conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
now = datetime.now().isoformat()

# 1. 建新表
conn.executescript("""
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
""")
conn.commit()

# 2. 检查旧 memories 表是否存在
tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
if "memories" not in tables:
    print("✅ 旧 memories 表不存在，跳过迁移")
    conn.close()
    raise SystemExit

# 3. 分流迁移
rows = conn.execute("SELECT * FROM memories").fetchall()
print(f"旧 memories: {len(rows)} 条")

um_count = ar_count = ab_count = 0
invalid_ids = []

for r in rows:
    mtype = r["type"]
    if mtype == "invalidated":
        invalid_ids.append(r["memory_id"])
        continue

    if mtype in ("fact", "event", "emotion"):
        conn.execute(
            "INSERT OR IGNORE INTO user_memories "
            "(memory_id, user_id, subject_id, type, content, scope, source_id, importance, "
            "created_at, last_accessed, access_count, decay_applied_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                r["memory_id"], r["user_id"], r["subject_id"] or r["user_id"],
                mtype, r["content"], r["scope"] or "private",
                r["source_id"] or r["user_id"], r["importance"] or 0.5,
                r["created_at"] or now, r["last_accessed"] or now,
                r["access_count"] or 0, r["decay_applied_at"] or now,
            ),
        )
        um_count += 1

    elif mtype == "reflection":
        conn.execute(
            "INSERT OR IGNORE INTO ai_reflections "
            "(reflection_id, user_id, content, importance, evidence_ids, created_at, last_accessed, access_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                r["memory_id"], r["user_id"], r["content"],
                r["importance"] or 0.8, "",
                r["created_at"] or now, r["last_accessed"] or now,
                r["access_count"] or 0,
            ),
        )
        ar_count += 1

    elif mtype == "behavior":
        conn.execute(
            "INSERT OR IGNORE INTO ai_behaviors "
            "(behavior_id, user_id, content, importance, source, created_at, last_accessed, access_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                r["memory_id"], r["user_id"] or "ai_self", r["content"],
                r["importance"] or 0.7, r["source_id"] or "user_feedback",
                r["created_at"] or now, r["last_accessed"] or now,
                r["access_count"] or 0,
            ),
        )
        ab_count += 1

conn.commit()
print(f"✅ user_memories: {um_count}, ai_reflections: {ar_count}, ai_behaviors: {ab_count}")
if invalid_ids:
    print(f"⏭️ 跳过 invalidated: {len(invalid_ids)} 条")

# 4. 迁移 feedback.jsonl 到表
fb_file = Path(__file__).parent / "data" / "feedback.jsonl"
if fb_file.exists():
    fb_count = 0
    with open(fb_file, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            conn.execute(
                "INSERT INTO feedback (message_id, session_id, user_id, user_message, ai_reply, emotion, tts_emotion, rating, created_at) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    rec.get("message_id", ""), rec.get("session_id", ""),
                    rec.get("user_id", "default"), rec.get("user_message", ""),
                    rec.get("ai_reply", ""), rec.get("emotion", ""),
                    rec.get("tts_emotion", ""), rec.get("rating", ""),
                    rec.get("rated_at", now),
                ),
            )
            fb_count += 1
    conn.commit()
    print(f"✅ feedback 迁移: {fb_count} 条")

# 5. 删旧表
conn.execute("DROP TABLE IF EXISTS memories")
conn.commit()
print("✅ 已删除旧 memories 表")

# 6. 查结果
tables2 = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
print("剩余表:", tables2)
conn.close()