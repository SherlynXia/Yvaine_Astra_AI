# backend/memory/retriever.py
"""检索相关记忆，拼成可注入 Prompt 的文本"""

from datetime import datetime
from . import database, vector_store


def _time_decay(created_at: str, half_life_days: float = 30.0) -> float:
    """老记忆权重降低，但不会归零"""
    try:
        created = datetime.fromisoformat(created_at)
        days = (datetime.now() - created).total_seconds() / 86400
        return 1.0 / (1.0 + days / half_life_days)
    except Exception:
        return 1.0


def retrieve_memories(
    query: str,
    user_id: str,
    top_k: int = 5,
    max_chars: int = 300,
) -> list[str]:
    """
    返回可直接注入 Prompt 的记忆文本列表。
    """
    candidates = vector_store.query_vectors(query, user_id, top_k=top_k * 2)
    if not candidates:
        return []

    scored = []
    for c in candidates:
        # cosine 距离 → 相似度
        similarity = 1.0 - c["distance"]
        if similarity < 0.4:
            continue

        meta = database.get_memory(c["memory_id"])
        if not meta:
            continue
        if meta.get("type") == "invalidated":
            continue

        decay = _time_decay(meta.get("created_at", ""))
        score = similarity * decay * (0.5 + meta.get("importance", 0.5))
        scored.append((score, meta))

    scored.sort(key=lambda x: x[0], reverse=True)

    result = []
    total_chars = 0
    for score, meta in scored:
        content = meta["content"]
        if total_chars + len(content) > max_chars:
            break
        result.append(content)
        total_chars += len(content)
        database.touch_memory(meta["memory_id"])

    return result


def build_memory_block(query: str, user_id: str) -> str:
    """生成可插入 System Prompt 的记忆段落"""
    memories = retrieve_memories(query, user_id)
    if not memories:
        return ""
    lines = "\n".join(f"- {m}" for m in memories)
    return f"\n\n【你记得的关于对方的事】\n{lines}\n"