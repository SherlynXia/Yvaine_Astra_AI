"""阶段1：给 memories 表加 subject_id / scope / source_id 三个字段"""

import sqlite3
from pathlib import Path

DB_PATH = Path(r"D:\Project\Yvaine_Astra_AI\backend\data\memory.db")

conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

# 1. 看现有列
cols = [r["name"] for r in conn.execute("PRAGMA table_info(memories)")]
print(f"现有列: {cols}")

# 2. 加字段（已存在则跳过）
for col, ddl in [
    ("subject_id", "ALTER TABLE memories ADD COLUMN subject_id TEXT"),
    ("scope", "ALTER TABLE memories ADD COLUMN scope TEXT DEFAULT 'private'"),
    ("source_id", "ALTER TABLE memories ADD COLUMN source_id TEXT"),
]:
    if col not in cols:
        conn.execute(ddl)
        print(f"✅ 已添加字段: {col}")
    else:
        print(f"⏭️ 字段已存在: {col}")

conn.commit()

# 3. 旧数据补齐：subject_id/source_id = user_id，scope = private
n = conn.execute("""
    UPDATE memories
    SET subject_id = COALESCE(subject_id, user_id),
        source_id  = COALESCE(source_id, user_id),
        scope      = COALESCE(scope, 'private')
    WHERE subject_id IS NULL OR source_id IS NULL OR scope IS NULL
""").rowcount
conn.commit()
print(f"✅ 补齐旧数据: {n} 行")

# 4. 验证
print("\n迁移后分布:")
for r in conn.execute(
    "SELECT user_id, subject_id, scope, source_id, COUNT(*) as n "
    "FROM memories GROUP BY user_id, subject_id, scope, source_id"
):
    print(f"  user={r['user_id'][:8]} subject={r['subject_id'][:8] if r['subject_id'] else None} "
          f"scope={r['scope']} source={r['source_id'][:8] if r['source_id'] else None} : {r['n']} 条")

conn.close()
print("\n✅ 数据库迁移完成")