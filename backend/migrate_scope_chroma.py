"""阶段1：给已有向量补 subject_id / scope / source_id（只改 metadata，不重算向量）"""

import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import sqlite3
import chromadb
from pathlib import Path

DB_PATH = Path(r"D:\Project\Yvaine_Astra_AI\backend\data\memory.db")
CHROMA_PATH = Path(r"D:\Project\Yvaine_Astra_AI\backend\data\chroma")

# 从 SQLite 读完整字段
conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row
rows = conn.execute(
    "SELECT memory_id, user_id, subject_id, scope, source_id FROM memories"
).fetchall()
conn.close()
print(f"SQLite 记忆: {len(rows)} 条")

# 构造 memory_id -> metadata 映射
meta_map = {
    r["memory_id"]: {
        "user_id": r["user_id"],
        "subject_id": r["subject_id"] or r["user_id"],
        "scope": r["scope"] or "private",
        "source_id": r["source_id"] or r["user_id"],
    }
    for r in rows
}

client = chromadb.PersistentClient(path=str(CHROMA_PATH))
col = client.get_collection("memories")
data = col.get()
print(f"ChromaDB 向量: {len(data['ids'])} 条")

# 找出需要更新的（缺 subject_id 或 scope）
need_update = []
new_metas = []
for mid, meta in zip(data["ids"], data["metadatas"]):
    m = meta or {}
    if "subject_id" not in m or "scope" not in m:
        need_update.append(mid)
        # 优先用 SQLite 的值，SQLite 没有就兜底
        new_metas.append(meta_map.get(mid, {
            "user_id": m.get("user_id", ""),
            "subject_id": m.get("user_id", ""),
            "scope": "private",
            "source_id": m.get("user_id", ""),
        }))

print(f"待更新 metadata: {len(need_update)} 条")

if need_update:
    col.update(ids=need_update, metadatas=new_metas)
    print("✅ metadata 更新完成")

# 验证
data2 = col.get()
print("\n更新后采样:")
for mid, meta in zip(data2["ids"][:5], data2["metadatas"][:5]):
    print(f"  {mid[:8]} | user={meta.get('user_id', '')[:8]} "
          f"subject={meta.get('subject_id', '')[:8]} scope={meta.get('scope')}")