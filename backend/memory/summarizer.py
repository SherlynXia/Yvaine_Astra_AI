# backend/memory/summarizer.py
"""上下文压缩：把溢出窗口的对话压缩成摘要"""

from . import database

_COMPRESS_PROMPT = """把下面这段对话压缩成 2-3 句话的摘要，保留：
- 聊了什么话题
- 用户的情绪/状态
- 有没有值得记住的结论

对话：
{conversation}

摘要（直接输出摘要文本，不要 JSON、不要前缀）："""


async def compress_to_memory(conv, overflow_messages: list[dict]):
    """压缩溢出对话，存进 ConversationStore.summaries（内存）"""
    from core.chat_service import ChatService

    provider = ChatService._provider
    if provider is None or not overflow_messages:
        return

    conversation = "\n".join(
        f"{'用户' if m['role'] == 'user' else '渊鸢'}：{m['content']}"
        for m in overflow_messages
    )

    prompt = _COMPRESS_PROMPT.format(conversation=conversation)

    try:
        summary = await provider.chat(
            [{"role": "user", "content": prompt}],
            temperature=0.3,
        )
        summary = (summary or "").strip()
        if not summary or len(summary) < 10:
            return

        conv.summaries.append(summary[:300])
        print(f"[Memory] 📦 上下文压缩（内存）: {summary[:60]}...", flush=True)
    except Exception as e:
        print(f"[Memory] ⚠️ 压缩失败: {e}", flush=True)