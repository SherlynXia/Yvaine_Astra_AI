# backend/migrate_pending_workspace.py
"""把 pending_workspace.json 迁入指定话题（不走 LLM 匹配，避免误判）

用法：
    python migrate_pending_workspace.py                     # dry-run
    python migrate_pending_workspace.py --apply             # 执行
    python migrate_pending_workspace.py --apply --force     # 跳过去重强制插入
"""

import json
import shutil
import sys
from datetime import datetime
from pathlib import Path

from memory import database, vector_store

PENDING_JSON = Path("data/pending_workspace.json")

# ========== 配置 ==========

# 目标话题（现有「星体模拟故事构思」）
TARGET_TOPIC_ID = "3ff64197-efd2-4372-ba14-bfdf92894d91"

# 去重阈值（和 workspace.DEDUP_DIST 一致）
DEDUP_DIST = 0.1


def main(apply: bool, force: bool):
    print(f"\n{'='*60}")
    print(f"  {'执行模式' if apply else 'DRY-RUN（只打印）'}{' [FORCE]' if force else ''}")
    print(f"{'='*60}\n")

    # 1. 检查目标话题存在
    topic = database.get_workspace_topic(TARGET_TOPIC_ID)
    if not topic:
        print(f"❌ 目标话题不存在: {TARGET_TOPIC_ID}")
        return
    print(f"🎯 目标话题: {topic['title']} (user_id={topic['user_id'][:8]}, "
          f"items={topic['item_count']})\n")

    # 2. 读 pending
    if not PENDING_JSON.exists():
        print(f"❌ pending 文件不存在: {PENDING_JSON}")
        return

    try:
        pending = json.loads(PENDING_JSON.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"❌ 读取失败: {e}")
        return

    if not pending:
        print("⏭️ pending 为空，无需迁移")
        return

    print(f"📦 待迁移 {len(pending)} 条素材\n")

    # 3. 逐条处理
    to_insert = []
    for i, entry in enumerate(pending, 1):
        content = entry.get("content", "").strip()
        note = entry.get("note", "")
        user_id = entry.get("user_id", "")

        if not content:
            print(f"  [{i}] ⚠️ 空内容，跳过")
            continue

        # 用户 ID 必须匹配话题
        if user_id and user_id != topic["user_id"]:
            print(f"  [{i}] ⚠️ user_id 不匹配话题（pending={user_id[:8]} vs topic={topic['user_id'][:8]}），跳过")
            continue

        # 去重检查
        item_type = "idea" if ("构思" in note or "想法" in note) else "setting"
        similar = vector_store.query_workspace_items(content, TARGET_TOPIC_ID, top_k=1)
        dist = similar[0]["distance"] if similar else 1.0

        if not force and similar and dist < DEDUP_DIST:
            print(f"  [{i}] ⏭️ 与话题内已有素材重复 (dist={dist:.3f})，跳过")
            print(f"       {content[:60]}")
            continue

        print(f"  [{i}] ✅ 待插入 [{item_type}] (dist={dist:.3f})")
        print(f"       {content[:80]}")
        to_insert.append({
            "content": content,
            "item_type": item_type,
            "note": note,
        })

    print(f"\n{'='*60}")
    print(f"  将插入 {len(to_insert)} 条，跳过 {len(pending) - len(to_insert)} 条")
    print(f"{'='*60}\n")

    if not to_insert:
        print("没有需要插入的内容")
        return

    if not apply:
        print("💡 DRY-RUN 结束。确认后运行：python migrate_pending_workspace.py --apply\n")
        return

    # 4. 执行插入
    print("⚠️ 开始插入...\n")

    inserted = 0
    for entry in to_insert:
        try:
            item_id = database.insert_workspace_item(
                TARGET_TOPIC_ID, entry["content"], entry["item_type"]
            )
            vector_store.add_workspace_item(
                item_id, entry["content"], TARGET_TOPIC_ID, entry["item_type"]
            )
            inserted += 1
            print(f"  ✅ 插入 {item_id[:8]} | {entry['content'][:60]}")
        except Exception as e:
            print(f"  ❌ 插入失败: {e}")

    # 5. 备份 pending 文件
    if inserted > 0:
        backup = PENDING_JSON.with_suffix(".json.migrated")
        shutil.copy2(PENDING_JSON, backup)
        print(f"\n📄 pending 文件已备份 → {backup.name}")

    print(f"\n{'='*60}")
    print(f"  ✅ 完成，插入 {inserted} 条")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main(
        apply="--apply" in sys.argv,
        force="--force" in sys.argv,
    )