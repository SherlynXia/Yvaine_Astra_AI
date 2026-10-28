"""记忆管理 CLI

用法：
    python backend/memory_cli.py list
    python backend/memory_cli.py list --user cd4ad67b
    python backend/memory_cli.py delete 3ba1d754
    python backend/memory_cli.py delete-keyword 牛奶
    python backend/memory_cli.py clear-user cd4ad67b
    python backend/memory_cli.py clear-all
    python backend/memory_cli.py stats
"""

import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import argparse
import sqlite3
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "memory.db"
CHROMA_PATH = ROOT / "data" / "chroma"


def _conn():
    return sqlite3.connect(str(DB_PATH))


def _chroma():
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    try:
        return client.get_collection("memories")
    except Exception:
        return None


def _delete_many(ids: list[str]):
    if not ids:
        return 0
    conn = _conn()
    for mid in ids:
        conn.execute("DELETE FROM memories WHERE memory_id = ?", (mid,))
    conn.commit()
    conn.close()
    col = _chroma()
    if col:
        try:
            col.delete(ids=ids)
        except Exception as e:
            print(f"⚠️ ChromaDB 删除失败: {e}")
    return len(ids)


# ---------- 命令 ----------

def cmd_list(args):
    conn = _conn()
    sql = (
        "SELECT memory_id, user_id, subject_id, scope, source_id, "
        "type, importance, created_at, last_accessed, access_count, content "
        "FROM memories"
    )
    params = []
    if args.user:
        sql += " WHERE user_id LIKE ?"
        params.append(f"{args.user}%")
    sql += " ORDER BY created_at DESC"
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    if not rows:
        print("（没有记忆）")
        return

    print(f"共 {len(rows)} 条\n")
    for r in rows:
        print(
            f"{r[0][:8]}  user={r[1][:8]}  subject={(r[2] or '')[:8]}  "
            f"scope={r[3]:8}  source={(r[4] or '')[:8]}  {r[5]:10}  "
            f"imp={r[6]:.2f}  acc={r[9]}  {r[7][:10]}"
        )
        print(f"          {r[10]}")
        print()


def cmd_delete(args):
    conn = _conn()
    rows = conn.execute(
        "SELECT memory_id, content FROM memories WHERE memory_id LIKE ?",
        (f"{args.id}%",),
    ).fetchall()
    conn.close()

    if not rows:
        print(f"未找到 memory_id 以 '{args.id}' 开头的记忆")
        return
    if len(rows) > 1:
        print(f"匹配到 {len(rows)} 条，请用更长的前缀：")
        for mid, content in rows:
            print(f"  {mid} | {content[:40]}")
        return

    mid, content = rows[0]
    n = _delete_many([mid])
    print(f"✅ 已删除 {n} 条: {content}")


def cmd_delete_keyword(args):
    conn = _conn()
    rows = conn.execute(
        "SELECT memory_id, content FROM memories WHERE content LIKE ?",
        (f"%{args.keyword}%",),
    ).fetchall()
    conn.close()

    if not rows:
        print(f"未找到包含 '{args.keyword}' 的记忆")
        return

    print(f"匹配到 {len(rows)} 条：")
    for mid, content in rows:
        print(f"  {mid[:8]} | {content}")

    ans = input("确认删除？(y/N) ").strip().lower()
    if ans != "y":
        print("已取消")
        return

    n = _delete_many([mid for mid, _ in rows])
    print(f"✅ 已删除 {n} 条")


def cmd_clear_user(args):
    conn = _conn()
    rows = conn.execute(
        "SELECT memory_id FROM memories WHERE user_id LIKE ?",
        (f"{args.user}%",),
    ).fetchall()
    conn.close()
    ids = [r[0] for r in rows]

    if not ids:
        print("该用户下没有记忆")
        return

    ans = input(f"确认删除用户 {args.user} 名下的 {len(ids)} 条记忆？(y/N) ").strip().lower()
    if ans != "y":
        print("已取消")
        return

    n = _delete_many(ids)
    print(f"✅ 已删除 {n} 条")


def cmd_clear_all(args):
    conn = _conn()
    n = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
    conn.close()

    if n == 0:
        print("没有记忆")
        return

    ans = input(f"⚠️ 确认清空全部 {n} 条记忆？(yes/N) ").strip()
    if ans != "yes":
        print("已取消")
        return

    conn = _conn()
    conn.execute("DELETE FROM memories")
    conn.commit()
    conn.close()

    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    try:
        client.delete_collection("memories")
        print("✅ ChromaDB collection 已删除，下次启动会重建")
    except Exception:
        pass
    print(f"✅ 已清空 {n} 条记忆")


def cmd_stats(args):
    conn = _conn()
    print("按用户：")
    for uid, n in conn.execute("SELECT user_id, COUNT(*) FROM memories GROUP BY user_id"):
        print(f"  {uid} : {n} 条")
    print("\n按类型：")
    for mtype, n in conn.execute("SELECT type, COUNT(*) FROM memories GROUP BY type"):
        print(f"  {mtype} : {n} 条")
    avg = conn.execute("SELECT AVG(importance) FROM memories").fetchone()[0]
    print(f"\n平均重要度: {avg:.2f}" if avg else "\n（空）")
    conn.close()


# ---------- 入口 ----------

def main():
    p = argparse.ArgumentParser(description="记忆管理工具")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("list", help="列出记忆")
    sp.add_argument("--user", default="")
    sp.set_defaults(func=cmd_list)

    sp = sub.add_parser("delete", help="按 memory_id 前缀删除")
    sp.add_argument("id")
    sp.set_defaults(func=cmd_delete)

    sp = sub.add_parser("delete-keyword", help="按内容关键词删除")
    sp.add_argument("keyword")
    sp.set_defaults(func=cmd_delete_keyword)

    sp = sub.add_parser("clear-user", help="清空指定用户")
    sp.add_argument("user")
    sp.set_defaults(func=cmd_clear_user)

    sp = sub.add_parser("clear-all", help="清空全部")
    sp.set_defaults(func=cmd_clear_all)

    sp = sub.add_parser("stats", help="统计")
    sp.set_defaults(func=cmd_stats)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()