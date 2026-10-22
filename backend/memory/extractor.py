# backend/memory/extractor.py
"""从对话中提取记忆：规则预筛 + LLM 精提取"""

import json
import re
from . import database, vector_store
from llm.base import LLMProvider

FACT_TRIGGERS = ["我喜欢", "我不喜欢", "我是", "我叫", "我的", "记住", "以后", "下次", "讨厌", "爱吃", "住在"]
EVENT_TRIGGERS = ["今天", "昨天", "完成了", "失败了", "开始了", "结束了", "刚", "刚才"]

EXTRACT_PROMPT = """从下面【用户说的话】中，提取关于用户的明确事实，并判断它对已有记忆的影响。

⚠️ 严格规则：
1. 只提取用户**亲口说出来**的内容。
2. 不要推测、不要补全。
3. 如果用户只是提问，不是事实，不要提取。
4. evidence 必须是【用户说的话】里**原样出现**的片段。

【已有记忆（可能为空）】
{existing_memories}

【用户说的话】
{user_message}

输出严格 JSON 数组，每个元素：
{{
  "action": "add" | "invalidate" | "update",
  "type": "fact" | "event" | "emotion",
  "content": "一句话描述",
  "evidence": "用户原话中的证据片段",
  "target_memory_id": "action 为 invalidate/update 时填，指被推翻的旧记忆 id，否则为空字符串",
  "importance": 0.0-1.0
}}

action 判断：
- "add"：用户说了新事实，与已有记忆不冲突
- "invalidate"：用户明确否定旧记忆（"我不喜欢牛奶了"）
- "update"：用户修正旧记忆（"我其实叫夏凛，不是夏林"）

没有值得记的，输出 []。

JSON："""

def _should_extract(text: str) -> bool:
    return any(t in text for t in FACT_TRIGGERS + EVENT_TRIGGERS)


def _parse_json_array(text: str) -> list:
    text = text.strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
    start = text.find("[")
    end = text.rfind("]")
    if start < 0 or end < 0:
        print(f"[Memory] ❌ 未找到 JSON 数组，LLM 原始输出: {text[:200]}", flush=True)
        return []
    try:
        return json.loads(text[start:end + 1])
    except json.JSONDecodeError as e:
        print(f"[Memory] ❌ JSON 解析失败: {e}，原文: {text[start:end+1][:200]}", flush=True)
        return []


async def extract_and_store(
    provider: LLMProvider,
    user_id: str,
    user_message: str,
    ai_reply: str = "",
):
    print(f"[Memory] 🔍 extract_and_store 被调用", flush=True)

    # 1. 触发器预筛
    if not _should_extract(user_message):
        print(f"[Memory] 🔍 触发器未命中，跳过", flush=True)
        return

    # 2. 检索可能冲突的已有记忆（只在含否定/修正词时查，省算力）
    existing_text = ""
    negation_words = ["不", "不再", "没有", "其实", "改成", "以前", "曾经"]
    if any(w in user_message for w in negation_words):
        candidates = vector_store.query_vectors(user_message, user_id, top_k=3)
        lines = []
        for c in candidates:
            if c["distance"] < 0.6:  # 只保留相关的
                lines.append(f"[{c['memory_id']}] {c['content']}")
        existing_text = "\n".join(lines)
        if lines:
            print(f"[Memory] 🔍 检索到 {len(lines)} 条可能冲突的记忆", flush=True)

    prompt = EXTRACT_PROMPT.format(
        user_message=user_message,
        existing_memories=existing_text or "（无）",
    )

    try:
        raw = await provider.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.2,
        )
        print(f"[Memory] 🤖 LLM 返回: {raw[:300]}", flush=True)
    except Exception as e:
        print(f"[Memory] ⚠️ 提取调用失败: {e}", flush=True)
        return

    items = _parse_json_array(raw)
    if not items:
        return

    saved = 0
    for item in items:
        if not isinstance(item, dict):
            continue

        action = str(item.get("action", "add")).strip()
        content = str(item.get("content", "")).strip()
        mem_type = str(item.get("type", "fact")).strip()
        evidence = str(item.get("evidence", "")).strip()
        target_id = str(item.get("target_memory_id", "")).strip()
        try:
            importance = float(item.get("importance", 0.5))
        except (TypeError, ValueError):
            importance = 0.5

        print(f"[Memory] 🔍 候选: action={action}, content={content}, evidence={evidence!r}", flush=True)

        if not content or len(content) < 3:
            continue
        if not evidence or evidence not in user_message:
            print(f"[Memory] ⏭️ 跳过: evidence 不在用户原话中", flush=True)
            continue
        if mem_type not in ("fact", "event", "emotion", "reflection"):
            mem_type = "fact"
        if importance < 0.5:
            continue

        # ---------- invalidate：软删除旧记忆 ----------
        if action in ("invalidate", "update") and target_id:
            conn = database.get_conn()
            row = conn.execute(
                "SELECT memory_id, content FROM memories WHERE memory_id LIKE ?",
                (f"{target_id}%",),
            ).fetchone()
            if row:
                full_id, old_content = row["memory_id"], row["content"]
                conn.execute(
                    "UPDATE memories SET importance = 0.1, type = 'invalidated' WHERE memory_id = ?",
                    (full_id,),
                )
                conn.commit()
                vector_store.delete_vector(full_id)
                print(f"[Memory] 🗑️ 失效旧记忆: {old_content}", flush=True)
            else:
                print(f"[Memory] ⚠️ 找不到目标记忆: {target_id}", flush=True)

        # ---------- add / update：写入新记忆 ----------
        similar = vector_store.query_vectors(content, user_id, top_k=1)
        if similar and similar[0]["distance"] < 0.1:
            print(f"[Memory] ⏭️ 跳过: 重复", flush=True)
            continue

        memory_id = database.insert_memory(user_id, mem_type, content, importance)
        vector_store.add_vector(memory_id, content, user_id)
        saved += 1
        print(f"[Memory] 💾 记住: [{mem_type}] {content}", flush=True)

    print(f"[Memory] ✅ 本轮新增 {saved} 条记忆", flush=True)