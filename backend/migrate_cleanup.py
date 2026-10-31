# backend/migrate_cleanup.py
"""记忆库整理：删过期/重复/一次性、迁 workspace 素材、修 typo

用法：
    python migrate_cleanup.py            # dry-run，只打印计划
    python migrate_cleanup.py --apply    # 实际执行
"""

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from memory import database, vector_store

BACKUP_DIR = Path("data/backups")
PENDING_WORKSPACE = Path("data/pending_workspace.json")


# ========== 清理计划 ==========

DELETE_IDS = {
    # 凛
    "4cf23600-8673-42b7-b7ce-0950245be327": "凛约定明天再聊（已过期）",
    "899c8fbb-7b3e-400f-9ef2-d26448d3aa94": "凛刚刚得知…询问星星（一次性）",
    "7a9a665a-60c6-4cab-b122-dfb491f79e42": "凛主动打招呼（一次性寒暄）",
    # 夏凛
    "afed1c4b-7d6e-4fac-b852-2da9850df74f": "用户喜欢星空（与 383e20a9 重复）",
    "91c060de-b787-4b71-aa76-23daef373dab": "夏凛说明天7点半（已过期）",
    "4a232daa-ae38-41ce-b297-f9513456922a": "夏凛提醒对方不要忘记名字（一次性）",
    "821e74a1-6cbc-49b4-8754-a699093e317b": "夏凛表示没说过猎户座（对话澄清）",
    "ca1ef3da-3cef-4a25-94be-8169dad1467b": "夏凛要求转告某事（pending 过期）",
    "38c09e0f-caaa-40b2-9e0d-5f5f1bd03f63": "用户修好了渊鸢记忆（一次性完成）",
    "7bee6d73-04c9-4acb-9ef4-5232bede43a7": "Live2D 动作触发测试（一次性）",
}

WORKSPACE_EXPORTS = {
    "f6cca574-001a-44d3-8ffb-038ed2455658": {
        "content": "虚拟歌姬的家乡设定是绘星，并且那里有行星。",
        "note": "虚拟歌姬设定素材",
    },
}

SPLIT_UPDATES = {
    "36f48c60-1c5a-48b3-a5d2-d12745529ea4": {
        "new_content": "夏凛喜欢进行虚构世界观创作",
        "export_item": {
            "content": "夏凛正在构思一个恒星系设定，用于给虚拟歌姬做二创",
            "note": "恒星系设定构思",
        },
    },
}

TYPE_UPDATES = {
    "16341314-5345-412c-84cc-6fc3fed40592": "fact",  # 凛+夏凛帮 AI 研究记忆模块
    "8783e3a8-5bdf-4899-98f6-f8fdf8990e1d": "fact",  # 夏凛计划做天体物理模拟
}

CONTENT_FIXES = {
    "3e6cd37d-4899-47f5-8e8e-0b430bf7a2ba": {
        "old": "夏季大三季（大三角）",
        "new": "夏季大三角",
    },
}


# ========== 辅助 ==========

def _chroma_update_content(mid: str, content: str):
    col = vector_store._get_collection("user_memories")
    col.update(ids=[mid], documents=[content])


def _chroma_update_meta(mid: str, key: str, value):
    col = vector_store._get_collection("user_memories")
    metas = col.get(ids=[mid]).get("metadatas") or []
    if not metas or not metas[0]:
        return
    meta = metas[0]
    meta[key] = value
    col.update(ids=[mid], metadatas=[meta])


def backup_db():
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    dst = BACKUP_DIR / f"memory.db.bak.{ts}"
    shutil.copy2(database.DB_PATH, dst)
    print(f"[备份] {database.DB_PATH} → {dst}")
    return dst


def _print_summary():
    print(f"\n{'='*60}")
    print(f"  删除 {len(DELETE_IDS)} + 素材迁移 {len(WORKSPACE_EXPORTS)} + 拆分 {len(SPLIT_UPDATES)}")
    print(f"  类型变更 {len(TYPE_UPDATES)} + typo 修正 {len(CONTENT_FIXES)}")
    print(f"{'='*60}\n")


def main(apply: bool):
    conn = database.get_conn()
    mode = "执行模式" if apply else "DRY-RUN（只打印不执行）"
    print(f"\n{'='*60}\n  {mode}\n{'='*60}\n")

    # ---- 1. 删除 ----
    print(f"--- [1/5] 完全删除 {len(DELETE_IDS)} 条 ---")
    for mid, reason in DELETE_IDS.items():
        row = conn.execute("SELECT content FROM user_memories WHERE memory_id=?", (mid,)).fetchone()
        if row:
            print(f"  ❌ {mid[:8]} | {reason}")
            print(f"     {row['content'][:60]}")
        else:
            print(f"  ⚠️ {mid[:8]} 不存在（跳过）")

    # ---- 2. 素材迁移 ----
    print(f"\n--- [2/5] workspace 素材迁移 {len(WORKSPACE_EXPORTS)} 条 ---")
    for mid, info in WORKSPACE_EXPORTS.items():
        row = conn.execute("SELECT content FROM user_memories WHERE memory_id=?", (mid,)).fetchone()
        if row:
            print(f"  📦 {mid[:8]} | {info['note']}")
            print(f"     {row['content'][:60]}")
        else:
            print(f"  ⚠️ {mid[:8]} 不存在")

    # ---- 3. 拆分 ----
    print(f"\n--- [3/5] 拆分 {len(SPLIT_UPDATES)} 条 ---")
    for mid, info in SPLIT_UPDATES.items():
        row = conn.execute("SELECT content FROM user_memories WHERE memory_id=?", (mid,)).fetchone()
        if row:
            print(f"  🔀 {mid[:8]}")
            print(f"     原: {row['content']}")
            print(f"     改: {info['new_content']}")
            print(f"     导出: {info['export_item']['content']}")

    # ---- 4. 类型变更 ----
    print(f"\n--- [4/5] 类型变更 {len(TYPE_UPDATES)} 条 ---")
    for mid, new_type in TYPE_UPDATES.items():
        row = conn.execute("SELECT type, content FROM user_memories WHERE memory_id=?", (mid,)).fetchone()
        if row:
            print(f"  🔧 {mid[:8]} | {row['type']} → {new_type}")
            print(f"     {row['content'][:60]}")

    # ---- 5. typo 修正 ----
    print(f"\n--- [5/5] 内容修正 {len(CONTENT_FIXES)} 条 ---")
    for mid, fix in CONTENT_FIXES.items():
        row = conn.execute("SELECT content FROM user_memories WHERE memory_id=?", (mid,)).fetchone()
        if row:
            new_c = row["content"].replace(fix["old"], fix["new"])
            print(f"  ✏️ {mid[:8]}")
            print(f"     原: {row['content']}")
            print(f"     改: {new_c}")

    _print_summary()

    if not apply:
        print("💡 DRY-RUN 结束。确认后运行：python migrate_cleanup.py --apply\n")
        return

    # ================= 实际执行 =================
    print("⚠️ 开始执行，先备份数据库...\n")
    backup_db()

    pending = []

    # 1. 删除
    for mid in DELETE_IDS:
        if not conn.execute("SELECT 1 FROM user_memories WHERE memory_id=?", (mid,)).fetchone():
            continue
        conn.execute("DELETE FROM user_memories WHERE memory_id=?", (mid,))
        vector_store.delete_user_memory(mid)
        print(f"  ✅ 删除 {mid[:8]}")

    # 2. 素材迁移
    for mid, info in WORKSPACE_EXPORTS.items():
        row = conn.execute("SELECT user_id, subject_id, created_at FROM user_memories WHERE memory_id=?", (mid,)).fetchone()
        if not row:
            continue
        pending.append({
            "user_id": row["user_id"],
            "subject_id": row["subject_id"],
            "content": info["content"],
            "note": info["note"],
            "source_memory_id": mid,
            "source_created_at": row["created_at"],
            "extracted_at": datetime.now().isoformat(),
        })
        conn.execute("DELETE FROM user_memories WHERE memory_id=?", (mid,))
        vector_store.delete_user_memory(mid)
        print(f"  ✅ 迁移素材 {mid[:8]}")

    # 3. 拆分
    for mid, info in SPLIT_UPDATES.items():
        row = conn.execute("SELECT user_id, subject_id, created_at FROM user_memories WHERE memory_id=?", (mid,)).fetchone()
        if not row:
            continue
        pending.append({
            "user_id": row["user_id"],
            "subject_id": row["subject_id"],
            "content": info["export_item"]["content"],
            "note": info["export_item"]["note"],
            "source_memory_id": mid,
            "source_created_at": row["created_at"],
            "extracted_at": datetime.now().isoformat(),
        })
        conn.execute(
            "UPDATE user_memories SET content=?, last_accessed=? WHERE memory_id=?",
            (info["new_content"], datetime.now().isoformat(), mid),
        )
        _chroma_update_content(mid, info["new_content"])
        print(f"  ✅ 拆分 {mid[:8]}")

    # 4. 类型变更
    for mid, new_type in TYPE_UPDATES.items():
        if not conn.execute("SELECT 1 FROM user_memories WHERE memory_id=?", (mid,)).fetchone():
            continue
        conn.execute("UPDATE user_memories SET type=? WHERE memory_id=?", (new_type, mid))
        try:
            _chroma_update_meta(mid, "type", new_type)
        except Exception as e:
            print(f"  ⚠️ Chroma metadata 同步失败 {mid[:8]}: {e}")
        print(f"  ✅ 类型变更 {mid[:8]} → {new_type}")

    # 5. typo 修正
    for mid, fix in CONTENT_FIXES.items():
        row = conn.execute("SELECT content FROM user_memories WHERE memory_id=?", (mid,)).fetchone()
        if not row:
            continue
        new_c = row["content"].replace(fix["old"], fix["new"])
        if new_c == row["content"]:
            print(f"  ⚠️ typo 无需修正 {mid[:8]}（可能已是正确版本）")
            continue
        conn.execute("UPDATE user_memories SET content=? WHERE memory_id=?", (new_c, mid))
        _chroma_update_content(mid, new_c)
        print(f"  ✅ typo 修正 {mid[:8]}")

    conn.commit()

    # 保存 pending_workspace.json
    if pending:
        PENDING_WORKSPACE.parent.mkdir(parents=True, exist_ok=True)
        if PENDING_WORKSPACE.exists():
            old = json.loads(PENDING_WORKSPACE.read_text(encoding="utf-8"))
            pending = old + pending
        PENDING_WORKSPACE.write_text(
            json.dumps(pending, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        print(f"\n📦 workspace 素材已导出到 {PENDING_WORKSPACE}（共 {len(pending)} 条）")
        print(f"   任务 3 时从这里迁入 workspace_items\n")

    print(f"{'='*60}\n  ✅ 完成\n{'='*60}\n")


if __name__ == "__main__":
    main("--apply" in sys.argv)