# backend/memory/vector_store.py
"""ChromaDB 向量存储：语义检索"""
from __future__ import annotations

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from pathlib import Path

MODEL_PATH = Path(__file__).parent.parent / "models" / "bge-small-zh"

embedding_fn = SentenceTransformerEmbeddingFunction(
    model_name=str(MODEL_PATH),
    device="cpu",
)

CHROMA_PATH = Path(__file__).parent.parent / "data" / "chroma"
CHROMA_PATH.mkdir(parents=True, exist_ok=True)

_client: chromadb.PersistentClient | None = None
_collection = None


def get_collection():
    global _client, _collection
    if _collection is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
        embedding_fn = SentenceTransformerEmbeddingFunction(
            model_name="BAAI/bge-small-zh-v1.5",
            device="cpu",
        )
        _collection = _client.get_or_create_collection(
            name="memories",
            embedding_function=embedding_fn,
            metadata={"hnsw:space": "cosine"},
        )
        print(f"[Memory] 📚 ChromaDB 集合已就绪: {_collection.count()} 条记忆", flush=True)
    return _collection


def add_vector(memory_id: str, content: str, user_id: str):
    col = get_collection()
    col.add(
        ids=[memory_id],
        documents=[content],
        metadatas=[{"user_id": user_id}],
    )


def query_vectors(query_text: str, user_id: str, top_k: int = 5) -> list[dict]:
    """
    返回: [{"memory_id": ..., "content": ..., "distance": ...}, ...]
    distance 越小越相似（cosine 距离）
    """
    col = get_collection()
    try:
        results = col.query(
            query_texts=[query_text],
            n_results=top_k,
            where={"user_id": user_id},
        )
    except Exception as e:
        print(f"[Memory] ⚠️ 向量检索失败: {e}", flush=True)
        return []

    out = []
    ids = results.get("ids", [[]])[0]
    docs = results.get("documents", [[]])[0]
    dists = results.get("distances", [[]])[0]
    for i, memory_id in enumerate(ids):
        out.append({
            "memory_id": memory_id,
            "content": docs[i] if i < len(docs) else "",
            "distance": dists[i] if i < len(dists) else 1.0,
        })
    return out


def delete_vector(memory_id: str):
    col = get_collection()
    try:
        col.delete(ids=[memory_id])
    except Exception:
        pass