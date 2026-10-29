# backend/memory/vector_store.py
"""ChromaDB 向量存储：user_memories / ai_reflections / ai_behaviors 三个独立 collection"""
from __future__ import annotations

import chromadb
from chromadb.utils.embedding_functions import SentenceTransformerEmbeddingFunction
from pathlib import Path

MODEL_PATH = Path(__file__).parent.parent / "models" / "bge-small-zh"
CHROMA_PATH = Path(__file__).parent.parent / "data" / "chroma"
CHROMA_PATH.mkdir(parents=True, exist_ok=True)

_client: chromadb.PersistentClient | None = None
_embedding_fn = None
_collections: dict[str, any] = {}


def _get_embedding_fn():
    global _embedding_fn
    if _embedding_fn is not None:
        return _embedding_fn
    if MODEL_PATH.exists() and (MODEL_PATH / "model.safetensors").exists():
        print(f"[Memory] 📂 使用本地模型: {MODEL_PATH}", flush=True)
        try:
            _embedding_fn = SentenceTransformerEmbeddingFunction(model_name=str(MODEL_PATH), device="cpu")
            return _embedding_fn
        except Exception as e:
            print(f"[Memory] ⚠️ 本地模型加载失败，回退 hub: {e}", flush=True)
    print("[Memory] 🌐 回退到 HuggingFace 下载 BAAI/bge-small-zh-v1.5", flush=True)
    _embedding_fn = SentenceTransformerEmbeddingFunction(model_name="BAAI/bge-small-zh-v1.5", device="cpu")
    return _embedding_fn


def _get_collection(name: str):
    global _client
    if name in _collections:
        return _collections[name]
    if _client is None:
        _client = chromadb.PersistentClient(path=str(CHROMA_PATH))
    fn = _get_embedding_fn()
    col = _client.get_or_create_collection(name=name, embedding_function=fn, metadata={"hnsw:space": "cosine"})
    print(f"[Memory] 📚 collection [{name}] 已就绪: {col.count()} 条", flush=True)
    _collections[name] = col
    return col


def _add(name: str, id_: str, content: str, metadata: dict):
    col = _get_collection(name)
    col.add(ids=[id_], documents=[content], metadatas=[metadata])


def _query(name: str, query_text: str, where: dict, top_k: int) -> list[dict]:
    col = _get_collection(name)
    try:
        results = col.query(query_texts=[query_text], n_results=top_k, where=where)
    except Exception as e:
        print(f"[Memory] ⚠️ 检索失败 [{name}]: {e}", flush=True)
        return []
    out = []
    ids = results.get("ids", [[]])[0]
    docs = results.get("documents", [[]])[0]
    dists = results.get("distances", [[]])[0]
    metas = results.get("metadatas", [[]])[0]
    for i, mid in enumerate(ids):
        out.append({
            "memory_id": mid,
            "content": docs[i] if i < len(docs) else "",
            "distance": dists[i] if i < len(dists) else 1.0,
            "metadata": metas[i] if i < len(metas) else {},
        })
    return out


def _delete(name: str, id_: str):
    try:
        _get_collection(name).delete(ids=[id_])
    except Exception:
        pass


# ========== user_memories ==========

def add_user_memory(memory_id: str, content: str, user_id: str, metadata: dict | None = None):
    meta = {"user_id": user_id}
    if metadata:
        meta.update(metadata)
    _add("user_memories", memory_id, content, meta)


def query_user_memories(query_text: str, where: dict, top_k: int = 5) -> list[dict]:
    return _query("user_memories", query_text, where, top_k)


def delete_user_memory(memory_id: str):
    _delete("user_memories", memory_id)


# ========== ai_reflections ==========

def add_reflection(reflection_id: str, content: str, user_id: str):
    _add("ai_reflections", reflection_id, content, {"user_id": user_id, "type": "reflection"})


def query_reflections(query_text: str, user_id: str, top_k: int = 3) -> list[dict]:
    return _query("ai_reflections", query_text, {"user_id": user_id}, top_k)


def delete_reflection(reflection_id: str):
    _delete("ai_reflections", reflection_id)


# ========== ai_behaviors ==========

def add_behavior(behavior_id: str, content: str, source: str = "user_feedback"):
    _add("ai_behaviors", behavior_id, content, {"source": source, "type": "behavior"})


def query_behaviors(query_text: str, top_k: int = 5) -> list[dict]:
    col = _get_collection("ai_behaviors")
    try:
        results = col.query(query_texts=[query_text], n_results=top_k)
    except Exception as e:
        print(f"[Memory] ⚠️ 行为检索失败: {e}", flush=True)
        return []
    out = []
    ids = results.get("ids", [[]])[0]
    docs = results.get("documents", [[]])[0]
    dists = results.get("distances", [[]])[0]
    for i, mid in enumerate(ids):
        out.append({
            "memory_id": mid,
            "content": docs[i] if i < len(docs) else "",
            "distance": dists[i] if i < len(dists) else 1.0,
        })
    return out


def delete_behavior(behavior_id: str):
    _delete("ai_behaviors", behavior_id)