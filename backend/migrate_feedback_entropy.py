# backend/migrate_feedback_entropy.py
"""给 feedback 表幂等地加 entropy_score / value_tier 两列。可重复运行。"""

import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "memory.db"

def column_exists(conn, table: str, column: str) -> bool:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return any(r[1] == column for r in rows)

def main():
    if not DB_PATH.exists():
        print(f"❌ 数据库文件不存在: {DB_PATH}")
        return

    conn = sqlite3.connect(str(DB_PATH))
    try:
        # 先确认表存在
        tables = [
            r[0] for r in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            ).fetchall()
        ]
        if "feedback" not in tables:
            print(f"❌ feedback 表不存在。现有表: {tables}")
            return

        print("当前 feedback 列：")
        for r in conn.execute("PRAGMA table_info(feedback)").fetchall():
            print(f"  {r[1]:20} {r[2]}")

        # 加 entropy_score
        if not column_exists(conn, "feedback", "entropy_score"):
            conn.execute("ALTER TABLE feedback ADD COLUMN entropy_score REAL")
            print("✅ 已添加 entropy_score REAL")
        else:
            print("⏭️ entropy_score 已存在，跳过")

        # 加 value_tier
        if not column_exists(conn, "feedback", "value_tier"):
            conn.execute(
                "ALTER TABLE feedback ADD COLUMN value_tier TEXT DEFAULT 'manual'"
            )
            print("✅ 已添加 value_tier TEXT DEFAULT 'manual'")
        else:
            print("⏭️ value_tier 已存在，跳过")

        conn.commit()

        print("\n迁移后 feedback 列：")
        for r in conn.execute("PRAGMA table_info(feedback)").fetchall():
            print(f"  {r[1]:20} {r[2]}")

        n = conn.execute("SELECT COUNT(*) FROM feedback").fetchone()[0]
        print(f"\nfeedback 现有 {n} 行，value_tier 默认值检查：")
        for r in conn.execute(
            "SELECT value_tier, COUNT(*) FROM feedback GROUP BY value_tier"
        ):
            print(f"  {r[0]!r}: {r[1]} 行")

    finally:
        conn.close()

if __name__ == "__main__":
    main()