# backend/memory/reflection.py
"""从多条事实中归纳规律性认识"""

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


async def generate_reflections(
    provider: LLMProvider,
    user_id: str,
    min_memories: int = 10,
) -> int:
    memories = database.list_memories(user_id, limit=50)
    facts = [m for m in memories if m["type"] in ("fact", "event")]
    if len(facts) < min_memories:
        print(f"[Reflection] 记忆不足 {min_memories} 条（当前 {len(facts)}），跳过", flush=True)
        return 0

    memories_text = "\n".join(f"[{m['memory_id'][:8]}] {m['content']}" for m in facts)
    prompt = REFLECTION_PROMPT.format(n=len(facts), memories=memories_text)

    try:
        raw = await provider.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
        )
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

        # 🔥 校验 evidence_ids 真实存在
        evidence_ids = item.get("evidence_ids", [])
        valid_count = 0
        for eid in evidence_ids:
            if not isinstance(eid, str):
                continue
            conn = database.get_conn()
            row = conn.execute(
                "SELECT 1 FROM memories WHERE memory_id LIKE ?",
                (f"{eid}%",),
            ).fetchone()
            if row:
                valid_count += 1

        if valid_count < 2:
            print(f"[Reflection] ⏭️ 跳过: 支撑证据不足（{valid_count} 条）: {content}", flush=True)
            continue

        # 去重
        similar = vector_store.query_vectors(content, user_id, top_k=1)
        if similar and similar[0]["distance"] < 0.15:
            print(f"[Reflection] ⏭️ 跳过: 重复", flush=True)
            continue

        try:
            imp = float(item.get("importance", 0.8))
        except (TypeError, ValueError):
            imp = 0.8

        mid = database.insert_memory(user_id, "reflection", content, imp)
        vector_store.add_vector(mid, content, user_id)
        saved += 1
        print(f"[Reflection] 💡 反思: {content}", flush=True)

    print(f"[Reflection] ✅ 本轮新增 {saved} 条反思", flush=True)
    return saved