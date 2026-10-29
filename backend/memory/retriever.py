# backend/memory/retriever.py
"""检索：用户记忆（private + shared）/ AI 反思 / AI 行为 / 短期记忆"""

from datetime import datetime
from . import database, vector_store

SCOPE_WEIGHT = {
    "private": 1.0,
    "shared": 0.85,
}


def _relative_time(created_at: str) -> str:
    try:
        created = datetime.fromisoformat(created_at)
        seconds = (datetime.now() - created).total_seconds()
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
    if user_id == "ai_self":
        return "你自己"
    conn = database.get_conn()
    row = conn.execute("SELECT name FROM users WHERE user_id = ?", (user_id,)).fetchone()
    if row and row["name"]:
        return row["name"]
    return user_id[:8]


# ========== 用户记忆 ==========
def retrieve_user_memories(
    query: str,
    current_user_id: str,
    top_k: int = 5,
    max_chars: int = 300,
) -> list[dict]:
    """用户记忆：自己的 private + 与他相关的 shared"""
    candidates = []

    # 1. 自己的私密
    candidates += vector_store.query_user_memories(
        query,
        where={"$and": [{"subject_id": current_user_id}, {"scope": "private"}]},
        top_k=top_k,
    )
    # 2. 与他相关的 shared（关于他，或他说的）
    candidates += vector_store.query_user_memories(
        query,
        where={"$and": [
            {"scope": "shared"},
            {"$or": [
                {"subject_id": current_user_id},
                {"source_id": current_user_id},
            ]},
        ]},
        top_k=top_k,
    )

    if not candidates:
        return []

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
        meta = database.get_user_memory(c["memory_id"])
        if not meta:
            continue
        scope = meta.get("scope") or "private"
        imp = meta.get("importance", 0.5)
        score = similarity * (0.5 + imp) * SCOPE_WEIGHT.get(scope, 0.85)
        scored.append({
            "memory_id": meta["memory_id"],
            "content": meta["content"],
            "scope": scope,
            "subject_id": meta.get("subject_id", ""),
            "source_id": meta.get("source_id", ""),
            "importance": imp,
            "created_at": meta.get("created_at", ""),
            "score": score,
            "type": meta.get("type", ""),
        })

    scored.sort(key=lambda x: x["score"], reverse=True)

    result = []
    total_chars = 0
    for item in scored:
        if total_chars + len(item["content"]) > max_chars:
            break
        result.append(item)
        total_chars += len(item["content"])
        database.touch_user_memory(item["memory_id"])

    return result


# ========== AI 反思 ==========
def retrieve_reflections(query: str, current_user_id: str, top_k: int = 3) -> list[dict]:
    """AI 对当前用户的规律认知，独立 collection，不衰减"""
    candidates = vector_store.query_reflections(query, current_user_id, top_k=top_k * 2)
    if not candidates:
        return []

    result = []
    for c in candidates:
        similarity = 1.0 - c["distance"]
        if similarity < 0.35:   # 反思是规律，太宽会注入无关内容
            continue
        conn = database.get_conn()
        row = conn.execute(
            "SELECT * FROM ai_reflections WHERE reflection_id = ?", (c["memory_id"],)
        ).fetchone()
        if not row:
            continue
        result.append(dict(row))
        if len(result) >= top_k:
            break
    return result


# ========== AI 行为经验 ==========
def retrieve_behaviors(query: str, top_k: int = 5) -> list[dict]:
    """AI 通用的行为经验，不区分用户"""
    candidates = vector_store.query_behaviors(query, top_k=top_k * 2)
    if not candidates:
        return []

    result = []
    for c in candidates:
        similarity = 1.0 - c["distance"]
        if similarity < 0.3:
            continue
        conn = database.get_conn()
        row = conn.execute(
            "SELECT * FROM ai_behaviors WHERE behavior_id = ?", (c["memory_id"],)
        ).fetchone()
        if not row:
            continue
        result.append(dict(row))
        if len(result) >= top_k:
            break
    return result


# ========== 短期记忆 ==========
def _short_term_block(
    session_id: str,
    current_user_id: str,
    days: int = 3,
    max_chars: int = 500,
) -> str:
    if not session_id:
        return ""
    try:
        rows = database.load_recent_conversations(session_id, days=days, limit=40)
    except Exception as e:
        print(f"[Memory] ⚠️ 加载短期记忆失败: {e}", flush=True)
        return ""
    if not rows:
        return ""

    lines = []
    total = 0
    for r in rows:
        name = r["user_name"] or (r["user_id"][:8] if r["user_id"] != "ai_self" else "渊鸢")
        speaker = name if r["role"] == "user" else "渊鸢"
        rel = _relative_time(r["created_at"])
        line = f"- [{rel}] {speaker}：{r['content'][:60]}"
        if total + len(line) > max_chars:
            break
        lines.append(line)
        total += len(line)

    if not lines:
        return ""
    return "【近期对话】\n" + "\n".join(lines)


# ========== 组装 ==========
def build_memory_block(
    query: str,
    current_user_id: str,
    current_user_name: str = "对方",
    session_id: str = "",
) -> str:
    """
    四段独立注入：
      1. 关于用户的核心事实
      2. 话题相关用户记忆
      3. 你对这个人的理解（反思）
      4. 你学到的经验（行为）
      5. 近期对话（短期记忆）
    """
    parts = []

    # 1. 核心事实
    core = database.get_core_memories(current_user_id, limit=5)
    if core:
        core_lines = "\n".join(
            f"- [{_relative_time(m['created_at'])}] {m['content']}" for m in core
        )
        parts.append(f"【关于「{current_user_name}」的核心事实】\n{core_lines}")

    # 2. 话题相关用户记忆
    core_ids = {m["memory_id"] for m in core}
    topic = [
        m for m in retrieve_user_memories(query, current_user_id)
        if m["memory_id"] not in core_ids
    ]
    if topic:
        own = [m for m in topic if m["scope"] == "private"]
        shared = [m for m in topic if m["scope"] == "shared"]
        if own:
            parts.append("【相关记忆】\n" + "\n".join(
                f"- [{_relative_time(m['created_at'])}] {m['content']}" for m in own
            ))
        if shared:
            parts.append("【公共信息】\n" + "\n".join(
                f"- [{_relative_time(m['created_at'])}] {m['content']}" for m in shared
            ))

    # 3. AI 对这个人的理解
    reflections = retrieve_reflections(query, current_user_id)
    if reflections:
        parts.append("【你对这个人的理解】\n" + "\n".join(
            f"- {r['content']}" for r in reflections
        ))

    # 4. AI 学到的经验
    behaviors = retrieve_behaviors(query)
    if behaviors:
        parts.append("【你从过往学到的经验】\n" + "\n".join(
            f"- {b['content']}" for b in behaviors
        ))

    # 5. 短期记忆
    short_term = _short_term_block(session_id, current_user_id)
    if short_term:
        parts.append(short_term)

    if not parts:
        return ""
    return "\n\n" + "\n\n".join(parts) + "\n"