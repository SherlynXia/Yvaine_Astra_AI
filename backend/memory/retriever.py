# backend/memory/retriever.py
"""检索相关记忆：自己的私有 + 所有共享 + AI 自我观察"""

from datetime import datetime
from . import database, vector_store

# 各类记忆的权重系数（影响最终排序）
SCOPE_WEIGHT = {
    "private": 1.0,   # 关于自己的，最相关
    "shared": 0.85,   # 共享的，稍降
    "ai_self": 0.75,  # 自己的观察，再降
}



def _relative_time(created_at: str) -> str:
    """把时间戳转成'3小时前'/'昨天'/'3天前'"""
    try:
        created = datetime.fromisoformat(created_at)
        delta = datetime.now() - created
        seconds = delta.total_seconds()

        if seconds < 60:
            return "刚刚"
        if seconds < 3600:
            return f"{int(seconds // 60)}分钟前"
        if seconds < 86400:
            return f"{int(seconds // 3600)}小时前"
        if seconds < 172800:
            return "昨天"
        if seconds < 604800:
            return f"{int(seconds // 86400)}天前"
        return created.strftime("%m月%d日")
    except Exception:
        return ""

def _get_user_name(user_id: str) -> str:
    """user_id → 显示名，查不到就用前 8 位"""
    if user_id == "ai_self":
        return "你自己"
    conn = database.get_conn()
    row = conn.execute(
        "SELECT name FROM users WHERE user_id = ?", (user_id,)
    ).fetchone()
    if row and row["name"]:
        return row["name"]
    return user_id[:8]

def retrieve_memories(
    query: str,
    current_user_id: str,
    top_k: int = 5,
    max_chars: int = 300,
) -> list[dict]:
    """
    返回 list[dict]，每个含：
        memory_id, content, scope, subject_id, source_id, similarity, importance
    """
    candidates = []

    # 1. 自己的私有记忆
    candidates += vector_store.query_vectors(
        query,
        where={"$and": [{"subject_id": current_user_id}, {"scope": "private"}]},
        top_k=top_k,
    )
    # 2. 所有 shared
    candidates += vector_store.query_vectors(
        query,
        where={"scope": "shared"},
        top_k=top_k,
    )
    # 3. AI 自我观察
    candidates += vector_store.query_vectors(
        query,
        where={"scope": "ai_self"},
        top_k=top_k,
    )

    if not candidates:
        return []

    # 按 memory_id 去重
    seen = set()
    unique = []
    for c in candidates:
        if c["memory_id"] in seen:
            continue
        seen.add(c["memory_id"])
        unique.append(c)

    scored = []
    for c in unique:
        similarity = 1.0 - c["distance"]
        if similarity < 0.4:
            continue

        meta = database.get_memory(c["memory_id"])
        if not meta:
            continue
        if meta.get("type") == "invalidated":
            continue

        scope = meta.get("scope") or "private"
        imp = meta.get("importance", 0.5)   # 库里的值已经是衰减后的
        scope_w = SCOPE_WEIGHT.get(scope, 0.85)
        score = similarity * (0.5 + imp) * scope_w

        scored.append({
            "memory_id": meta["memory_id"],
            "content": meta["content"],
            "scope": scope,
            "subject_id": meta.get("subject_id", ""),
            "source_id": meta.get("source_id", ""),
            "importance": imp,
            "created_at": meta.get("created_at", ""),
            "score": score,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)

    # 截断到 max_chars
    result = []
    total_chars = 0
    for item in scored:
        if total_chars + len(item["content"]) > max_chars:
            break
        result.append(item)
        total_chars += len(item["content"])
        database.touch_memory(item["memory_id"])

    return result


def _recent_activity_block(exclude_user_id: str, hours: int = 6) -> str:
    """最近 N 小时内其他用户说的 shared 记忆"""
    from datetime import timedelta

    cutoff = (datetime.now() - timedelta(hours=hours)).isoformat()
    conn = database.get_conn()
    rows = conn.execute(
        """
        SELECT user_id, subject_id, source_id, content, created_at
        FROM memories
        WHERE scope = 'shared'
          AND source_id != ?
          AND subject_id != 'ai_self'
          AND type != 'invalidated'
          AND created_at > ?
        ORDER BY created_at DESC
        LIMIT 20
        """,
        (exclude_user_id, cutoff),
    ).fetchall()

    if not rows:
        return ""

    lines = []
    for r in rows:
        source_id = r["source_id"] or r["user_id"]
        subject_id = r["subject_id"] or ""

        source_name = _get_user_name(source_id)
        subject_name = _get_user_name(subject_id) if subject_id else ""
        rel = _relative_time(r["created_at"])

        if subject_id and subject_id != source_id:
            lines.append(f"- [{rel}] {source_name} 提到 {subject_name}：{r['content']}")
        else:
            lines.append(f"- [{rel}] {source_name}：{r['content']}")

    return "【近期活动】\n" + "\n".join(lines)


def build_memory_block(
    query: str,
    current_user_id: str,
    current_user_name: str = "对方",
) -> str:
    """
    合并三部分：
      1. 核心身份记忆（无条件注入）
      2. 话题相关记忆（语义检索）
      3. 近期活动（其他用户的 shared 记忆）
    """
    parts = []

    # 1. 核心身份记忆
    core = database.get_core_memories(current_user_id, limit=5)
    if core:
        core_lines = "\n".join(
            f"- [{_relative_time(m['created_at'])}] {m['content']}" for m in core
        )
        parts.append(f"【关于「{current_user_name}」的核心事实】\n{core_lines}")

    # 2. 话题相关记忆
    core_ids = {m["memory_id"] for m in core}
    topic = [
        m for m in retrieve_memories(query, current_user_id)
        if m["memory_id"] not in core_ids
    ]

    if topic:
        own = [m for m in topic if m["scope"] == "private"]
        shared = [m for m in topic if m["scope"] == "shared"]
        ai_self = [m for m in topic if m["scope"] == "ai_self"]

        if own:
            parts.append("【相关记忆】\n" + "\n".join(
                f"- [{_relative_time(m['created_at'])}] {m['content']}" for m in own
            ))
        if shared:
            parts.append("【公共信息】\n" + "\n".join(
                f"- [{_relative_time(m['created_at'])}] {m['content']}" for m in shared
            ))
        if ai_self:
            parts.append("【你的观察】\n" + "\n".join(
                f"- [{_relative_time(m['created_at'])}] {m['content']}" for m in ai_self
            ))

    # 3. 近期活动
    recent = _recent_activity_block(current_user_id)
    if recent:
        parts.append(recent)

    if not parts:
        return ""
    return "\n\n" + "\n\n".join(parts) + "\n"

