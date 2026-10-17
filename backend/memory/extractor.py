# backend/memory/extractor.py
"""从对话中提取记忆：规则预筛 + LLM 精提取"""

import json
import re
from . import database, vector_store
from llm.base import LLMProvider

FACT_TRIGGERS = ["我喜欢", "我不喜欢", "我是", "我叫", "我的", "记住", "以后", "下次", "讨厌", "爱吃", "住在"]
EVENT_TRIGGERS = ["今天", "昨天", "完成了", "失败了", "开始了", "结束了", "刚", "刚才"]

EXTRACT_PROMPT = """从下面这段对话中，提取关于"用户"的、值得长期记住的信息。

【必须提取的内容】
- 用户的名字、称呼、身份
- 用户的喜好/厌恶（喜欢什么、讨厌什么）
- 用户的个人情况（住在哪、做什么工作、在做什么项目）
- 明确发生的事件（完成了什么、开始了什么）

【不要提取】
- 推测性内容
- 寒暄、问候
- AI 自己的信息

【输出格式】
严格 JSON 数组。每个元素：
{{"type": "fact"|"event", "content": "一句话描述", "importance": 0.0-1.0}}
没有值得记的输出 []。

【示例 1】
对话：
用户：我是夏凛，你呢
渊鸢：你好夏凛，我是渊鸢。
输出：
[{{"type": "fact", "content": "用户叫夏凛", "importance": 0.9}}]

【示例 2】
对话：
用户：我喜欢喝冰美式
渊鸢：记下了。
输出：
[{{"type": "fact", "content": "用户喜欢喝冰美式", "importance": 0.7}}]

【示例 3】
对话：
用户：今天项目终于跑通了
渊鸢：恭喜。
输出：
[{{"type": "event", "content": "用户在 {today} 项目跑通了", "importance": 0.6}}]

【示例 4】
对话：
用户：今天天气不错
渊鸢：是啊。
输出：
[]

【实际对话】
{conversation}

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
    ai_reply: str,
):
    print(f"[Memory] 🔍 extract_and_store 被调用", flush=True)
    combined = f"{user_message}\n{ai_reply}"
    hit = _should_extract(combined)
    print(f"[Memory] 🔍 触发器命中={hit}", flush=True)
    if not hit:
        return

    conversation = f"用户：{user_message}\n渊鸢：{ai_reply}"
    from datetime import date
    prompt = EXTRACT_PROMPT.format(
        conversation=conversation,
        today=date.today().isoformat(),
    )

    print(f"[Memory] 🤖 调用 LLM 提取中...", flush=True)
    try:
        raw = await provider.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.2,   # 🔥 提取任务要服从指令，低温
        )
        print(f"[Memory] 🤖 LLM 返回: {raw[:300]}", flush=True)
    except Exception as e:
        print(f"[Memory] ⚠️ 提取调用失败: {e}", flush=True)
        return

    items = _parse_json_array(raw)
    print(f"[Memory] 🔍 解析出 {len(items)} 条候选", flush=True)
    if not items:
        return

    saved = 0
    for item in items:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content", "")).strip()
        mem_type = str(item.get("type", "fact")).strip()
        try:
            importance = float(item.get("importance", 0.5))
        except (TypeError, ValueError):
            importance = 0.5

        print(f"[Memory] 🔍 候选: type={mem_type}, importance={importance}, content={content}", flush=True)

        if not content or len(content) < 3:
            print(f"[Memory] ⏭️ 跳过: 内容太短", flush=True)
            continue
        if mem_type not in ("fact", "event", "emotion", "reflection"):
            mem_type = "fact"
        if importance < 0.5:
            print(f"[Memory] ⏭️ 跳过: importance {importance} < 0.5", flush=True)
            continue

        similar = vector_store.query_vectors(content, user_id, top_k=1)
        if similar and similar[0]["distance"] < 0.1:
            print(f"[Memory] ⏭️ 跳过: 与已有记忆重复 (distance={similar[0]['distance']:.3f})", flush=True)
            continue

        memory_id = database.insert_memory(user_id, mem_type, content, importance)
        vector_store.add_vector(memory_id, content, user_id)
        saved += 1
        print(f"[Memory] 💾 记住: [{mem_type}] {content}", flush=True)

    print(f"[Memory] ✅ 本轮新增 {saved} 条记忆", flush=True)