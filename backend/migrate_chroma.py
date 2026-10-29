"""ChromaDB 重构：memories collection 分流到 user_memories / ai_reflections / ai_behaviors"""
import os
os.environ["HF_HUB_OFFLINE"] = "1"
os.environ["TRANSFORMERS_OFFLINE"] = "1"

import sqlite3
import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from pathlib import Path

ROOT = Path(__file__).parent
DB_PATH = ROOT / "data" / "memory.db"
CHROMA_PATH = ROOT / "data" / "chroma"
MODEL_PATH = ROOT / "models" / "bge-small-zh"

# 1. 读 SQLite 新表
conn = sqlite3.connect(str(DB_PATH))
conn.row_factory = sqlite3.Row

um_rows = [dict(r) for r in conn.execute("SELECT * FROM user_memories")]
ar_rows = [dict(r) for r in conn.execute("SELECT * FROM ai_reflections")]
ab_rows = [dict(r) for r in conn.execute("SELECT * FROM ai_behaviors")]
conn.close()
print(f"SQLite: user_memories={len(um_rows)}, ai_reflections={len(ar_rows)}, ai_behaviors={len(ab_rows)}")

# 2. 构造 embedding
print(f"加载本地模型: {MODEL_PATH}")
embedding_fn = SentenceTransformerEmbeddingFunction(
    model_name=str(MODEL_PATH),
    device="cpu",
)

client = chromadb.PersistentClient(path=str(CHROMA_PATH))

# 3. 删旧 collection
for name in ("memories", "user_memories", "ai_reflections", "ai_behaviors"):
    try:
        client.delete_collection(name)
        print(f"✅ 删除 collection: {name}")
    except Exception:
        pass

# 4. 重建三个 collection
def _build(name, rows, id_key, meta_fn):
    if not rows:
        print(f"⏭️ {name}: 0 条，跳过")
        return
    col = client.create_collection(
        name=name,
        embedding_function=embedding_fn,
        metadata={"hnsw:space": "cosine"},
    )
    col.add(
        ids=[r[id_key] for r in rows],
        documents=[r["content"] for r in rows],
        metadatas=[meta_fn(r) for r in rows],
    )
    print(f"✅ {name}: {col.count()} 条")

_build(
    "user_memories", um_rows, "memory_id",
    lambda r: {
        "user_id": r["user_id"],
        "subject_id": r["subject_id"],
        "scope": r["scope"],
        "source_id": r["source_id"],
        "type": r["type"],
    },
)

_build(
    "ai_reflections", ar_rows, "reflection_id",
    lambda r: {"user_id": r["user_id"], "type": "reflection"},
)

_build(
    "ai_behaviors", ab_rows, "behavior_id",
    lambda r: {"user_id": r["user_id"], "type": "behavior", "source": r["source"]},
)

print("✅ ChromaDB 重建完成")