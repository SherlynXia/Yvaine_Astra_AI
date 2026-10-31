# backend/memory/reflection.py
"""AI 对用户的规律认知：从 user_memories 归纳 → 写入 ai_reflections"""

import json
import re
from . import database, vector_store
from llm.base import LLMProvider

REFLECTION_PROMPT = """下面是关于用户的 {n} 条记忆：

{memories}

请归纳出 3-5 条关于这个用户的**规律性认识**，而不是重复单条事实。

好的反思：
- "用户压力大时倾向于熬夜，第二天会说累"
- "用户对技术问题喜欢先自己试，卡住了才问"

坏的反思（只是复述）：
- "用户喜欢星空"

输出 JSON 数组：
[{{"content": "规律描述", "evidence_ids": ["支撑这条规律的记忆id前8位"], "importance": 0.0-1.0}}]
"""


def _parse_json_array(text: str) -> list:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < 0:
        return []
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError:
        return []


def should_reflect(user_id: str, min_new: int = 5) -> bool:
    """自上次反思以来，新增的 fact+event 是否 >= min_new"""
    conn = database.get_conn()
    last = conn.execute(
        "SELECT MAX(created_at) FROM ai_reflections WHERE user_id = ?",
        (user_id,),
    ).fetchone()[0]

    if last:
        count = conn.execute(
            "SELECT COUNT(*) FROM user_memories WHERE user_id = ? AND type IN ('fact','event') AND created_at > ?",
            (user_id, last),
        ).fetchone()[0]
    else:
        count = conn.execute(
            "SELECT COUNT(*) FROM user_memories WHERE user_id = ? AND type IN ('fact','event')",
            (user_id,),
        ).fetchone()[0]

    print(f"[Reflection] 新增 fact+event: {count} 条（阈值 {min_new}）", flush=True)
    return count >= min_new


async def generate_reflections(provider: LLMProvider, user_id: str, min_memories: int = 5) -> int:
    if not should_reflect(user_id, min_new=min_memories):
        print(f"[Reflection] 跳过：新增不足 {min_memories} 条", flush=True)
        return 0

    memories = database.list_user_memories(user_id, limit=50)
    facts = [m for m in memories if m["type"] in ("fact", "event")]
    if len(facts) < 3:
        print(f"[Reflection] 跳过：fact+event 总数不足 3 条", flush=True)
        return 0

    memories_text = "\n".join(f"[{m['memory_id'][:8]}] {m['content']}" for m in facts)
    prompt = REFLECTION_PROMPT.format(n=len(facts), memories=memories_text)

    try:
        raw = await provider.chat([{"role": "user", "content": prompt}], temperature=0.3)
        print(f"[Reflection] 🤖 LLM 返回: {raw[:300]}", flush=True)
    except Exception as e:
        print(f"[Reflection] ⚠️ 调用失败: {e}", flush=True)
        return 0

    items = _parse_json_array(raw)
    if not items:
        return 0

    saved = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        if not content or len(content) < 10:
            continue

        evidence_ids = item.get("evidence_ids", [])
        valid_ids = []
        for eid in evidence_ids:
            if not isinstance(eid, str):
                continue
            conn = database.get_conn()
            row = conn.execute(
                "SELECT memory_id FROM user_memories WHERE memory_id LIKE ?",
                (f"{eid}%",),
            ).fetchone()
            if row:
                valid_ids.append(row["memory_id"])

        # 证据不足时降级：用当前 fact+event 里最近的几条兜底
        if len(valid_ids) < 2:
            fallback = [m["memory_id"] for m in facts[-3:]]
            print(
                f"[Reflection] ⚠️ evidence 不足（{len(valid_ids)} 条），降级用最近 {len(fallback)} 条 fact",
                flush=True,
            )
            valid_ids = fallback

        if not valid_ids:
            print(f"[Reflection] ⏭️ 跳过: 完全无 evidence: {content}", flush=True)
            continue

        # 和已有反思比对：完全重复→强化；相近→衰减旧的；全新→新增
        similar = vector_store.query_reflections(content, user_id, top_k=1)
        if similar:
            dist = similar[0]["distance"]
            old_id = similar[0]["memory_id"]

            # 几乎一样：强化旧反思，不新增
            if dist < 0.1:
                old_imp, new_imp = database.reinforce_reflection(old_id, delta=0.05)
                print(
                    f"[Reflection] 📈 强化: {old_imp:.2f} → {new_imp:.2f} (dist={dist:.3f})",
                    flush=True,
                )
                continue

            # 相近但可能冲突：衰减旧反思（不删），新反思正常写入
            if dist < 0.25:
                old_imp, new_imp = database.decay_reflection(old_id, delta=0.15)
                print(
                    f"[Reflection] 📉 旧反思衰减: {old_imp:.2f} → {new_imp:.2f} "
                    f"(dist={dist:.3f})，新反思写入中",
                    flush=True,
                )
                # 不 continue，继续走下面的新增逻辑

            # dist >= 0.25：全新反思，直接新增

        try:
            imp = float(item.get("importance", 0.8))
        except (TypeError, ValueError):
            imp = 0.8
        imp = max(0.6, min(0.95, imp))

        rid = database.insert_reflection(user_id, content, imp, evidence_ids=",".join(valid_ids))
        vector_store.add_reflection(rid, content, user_id)
        saved += 1
        print(f"[Reflection] 💡 反思: {content}", flush=True)

    print(f"[Reflection] ✅ 本轮新增 {saved} 条反思", flush=True)
    return saved