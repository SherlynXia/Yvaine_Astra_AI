"""记忆管理 CLI（适配 user_memories / ai_behaviors / ai_reflections）

用法：
    python backend/memory_cli.py list
    python backend/memory_cli.py list --user cd4ad67b
    python backend/memory_cli.py delete 3ba1d754
    python backend/memory_cli.py delete-keyword 牛奶
    python backend/memory_cli.py clear-user cd4ad67b
    python backend/memory_cli.py clear-all
    python backend/memory_cli.py stats
    python backend/memory_cli.py list-nearby --threshold 0.25
    python backend/memory_cli.py list-nearby --user cd4ad67b --threshold 0.3
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

TABLE = "user_memories"
COLLECTION = "user_memories"


def _conn():
    return sqlite3.connect(str(DB_PATH))


def _chroma():
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    try:
        return client.get_collection(COLLECTION)
    except Exception:
        return None


def _delete_many(ids: list[str]):
    if not ids:
        return 0
    conn = _conn()
    for mid in ids:
        conn.execute(f"DELETE FROM {TABLE} WHERE memory_id = ?", (mid,))
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
        f"FROM {TABLE}"
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
        f"SELECT memory_id, content FROM {TABLE} WHERE memory_id LIKE ?",
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
        f"SELECT memory_id, content FROM {TABLE} WHERE content LIKE ?",
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
        f"SELECT memory_id FROM {TABLE} WHERE user_id LIKE ?",
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
    n = conn.execute(f"SELECT COUNT(*) FROM {TABLE}").fetchone()[0]
    conn.close()

    if n == 0:
        print("没有记忆")
        return

    ans = input(f"⚠️ 确认清空全部 {n} 条记忆？(yes/N) ").strip()
    if ans != "yes":
        print("已取消")
        return

    conn = _conn()
    conn.execute(f"DELETE FROM {TABLE}")
    conn.commit()
    conn.close()

    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    try:
        client.delete_collection(COLLECTION)
        print(f"✅ ChromaDB collection '{COLLECTION}' 已删除，下次启动会重建")
    except Exception:
        pass
    print(f"✅ 已清空 {n} 条记忆")


def cmd_stats(args):
    conn = _conn()
    print("按用户：")
    for uid, n in conn.execute(
        f"SELECT user_id, COUNT(*) FROM {TABLE} GROUP BY user_id"
    ):
        print(f"  {uid} : {n} 条")
    print("\n按类型：")
    for mtype, n in conn.execute(
        f"SELECT type, COUNT(*) FROM {TABLE} GROUP BY type"
    ):
        print(f"  {mtype} : {n} 条")
    avg = conn.execute(f"SELECT AVG(importance) FROM {TABLE}").fetchone()[0]
    print(f"\n平均重要度: {avg:.2f}" if avg else "\n（空）")
    conn.close()


def cmd_list_nearby(args):
    """列出 distance < threshold 的相近记忆对，用来验证融合效果。"""
    import chromadb
    client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    try:
        col = client.get_collection(COLLECTION)
    except Exception:
        print(f"collection '{COLLECTION}' 不存在")
        return

    conn = _conn()
    sql = f"SELECT memory_id, user_id, content FROM {TABLE}"
    params = []
    if args.user:
        sql += " WHERE user_id LIKE ?"
        params.append(f"{args.user}%")
    rows = conn.execute(sql, params).fetchall()
    conn.close()

    if not rows:
        print("（没有记忆）")
        return

    threshold = args.threshold
    content_map = {mid: content for mid, _, content in rows}
    pairs: dict[tuple, float] = {}

    for mid, uid, content in rows:
        try:
            res = col.query(query_texts=[content], n_results=3)
        except Exception as e:
            print(f"⚠️ 查询失败 {mid[:8]}: {e}")
            continue
        ids = (res.get("ids") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        for other_id, d in zip(ids, dists):
            if other_id == mid or other_id not in content_map:
                continue
            key = tuple(sorted([mid, other_id]))
            if key not in pairs or d < pairs[key]:
                pairs[key] = d

    near = [(k, d) for k, d in pairs.items() if d < threshold]
    near.sort(key=lambda x: x[1])

    if not near:
        print(f"没有 distance < {threshold} 的相近对 ✅")
        return

    print(f"找到 {len(near)} 对相近记忆（distance < {threshold}）\n")
    for (a, b), d in near:
        print(f"dist={d:.3f}")
        print(f"  [{a[:8]}] {content_map[a]}")
        print(f"  [{b[:8]}] {content_map[b]}")
        print()


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

    sp = sub.add_parser("list-nearby", help="列出相近记忆对")
    sp.add_argument("--user", default="")
    sp.add_argument("--threshold", type=float, default=0.25)
    sp.set_defaults(func=cmd_list_nearby)

    args = p.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()