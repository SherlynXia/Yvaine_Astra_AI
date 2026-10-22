# backend/core/chat_service.py
"""对话服务 — 编排层：记忆检索 + LLM 流式 + 动作/对白分离 + 情绪解析 + 记忆提取"""

import asyncio
import uuid

from llm.base import LLMProvider
from memory.short_term import ConversationStore
from memory import extractor, retriever, user_manager
from core.action_parser import ActionParser, map_action_to_live2d


class ChatService:
    """对话服务：注入 LLMProvider 即可工作"""

    _provider: LLMProvider | None = None
    _system_prompt: str = ""
    conversations: dict[str, ConversationStore] = {}

    # ========== 配置 ==========

    @classmethod
    def configure(cls, provider: LLMProvider | None, system_prompt: str) -> None:
        cls._provider = provider
        cls._system_prompt = system_prompt
        if provider is None:
            print("[Chat] ⚠️ 未配置 LLM Provider，对话将不可用", flush=True)
        else:
            print(f"[Chat] ✅ LLM Provider 已就绪: {type(provider).__name__}", flush=True)

    # ========== 非流式对话（保留兼容） ==========

    @classmethod
    async def chat(cls, user_message: str, session_id: str = "") -> tuple:
        if not session_id:
            session_id = str(uuid.uuid4())

        if cls._provider is None:
            return "抱歉，我的大脑暂时离线了...", "难过", session_id

        if session_id not in cls.conversations:
            cls.conversations[session_id] = ConversationStore(
                max_turns=10, system_prompt=cls._system_prompt,
            )
            print(f"[Chat] 🆕 新建会话: {session_id[:8]}...", flush=True)

        conv = cls.conversations[session_id]
        conv.add("user", user_message)

        try:
            raw_reply = await cls._provider.chat(conv.get_messages())
        except Exception as e:
            print(f"[Chat] ❌ Provider 调用失败: {e}", flush=True)
            return "思绪有些混乱...能再说一遍吗？", "疑惑", session_id

        # 非流式也做一次动作剥离
        parser = ActionParser()
        clean, _ = parser.feed(raw_reply)
        tail, _ = parser.flush()
        clean += tail

        reply, emotion = cls._parse_emotion(clean)
        conv.add("assistant", reply)
        return reply, emotion, session_id

    # ========== 流式对话（核心） ==========

    @classmethod
    async def chat_stream(cls, user_message: str, session_id: str = ""):
        """
        yield {"type": "chunk", "text": "..."}
        yield {"type": "final", "text": "...", "emotion": "...",
               "session_id": "...", "actions": ["wave", ...]}
        """
        if not session_id:
            session_id = str(uuid.uuid4())

        if cls._provider is None:
            text = "抱歉，我的大脑暂时离线了..."
            yield {"type": "chunk", "text": text}
            yield {"type": "final", "text": text, "emotion": "难过",
                   "session_id": session_id, "actions": []}
            return

        if session_id not in cls.conversations:
            cls.conversations[session_id] = ConversationStore(
                max_turns=10, system_prompt=cls._system_prompt,
            )
            print(f"[Chat] 🆕 新建会话: {session_id[:8]}...", flush=True)

        conv = cls.conversations[session_id]
        user_id = await user_manager.identify_user(session_id=session_id)
        user_manager.get_current_user(user_id)
        

        # 🔥 注入长期记忆（放到线程，不阻塞事件循环）
        memory_block = ""
        try:
            memory_block = await asyncio.to_thread(
                retriever.build_memory_block, user_message, user_id
            )
        except Exception as e:
            print(f"[Chat] ⚠️ 记忆检索失败（继续对话）: {e}", flush=True)

        original_prompt = conv.system_prompt
        if memory_block:
            conv.system_prompt = original_prompt + memory_block
            print(f"[Chat] 🧠 注入记忆 {memory_block.count('- ')} 条", flush=True)
        else:
            print("[Chat] 🧠 注入记忆 0 条", flush=True)

        conv.add("user", user_message)

        # 🔥 动作解析器
        parser = ActionParser()
        collected_actions: list[str] = []
        full_clean = ""

        try:
            async for chunk in cls._provider.chat_stream(conv.get_messages()):
                clean, acts = parser.feed(chunk)
                for a in acts:
                    tag = map_action_to_live2d(a)
                    if tag and tag not in collected_actions:
                        collected_actions.append(tag)
                if clean:
                    full_clean += clean
                    yield {"type": "chunk", "text": clean}
        except Exception as e:
            print(f"[Chat] ❌ Stream 失败: {e}", flush=True)
            yield {"type": "final", "text": "思绪有些混乱...", "emotion": "疑惑",
                   "session_id": session_id, "actions": []}
            return
        finally:
            conv.system_prompt = original_prompt

        # 收尾：未闭合的残留
        tail, tail_acts = parser.flush()
        for a in tail_acts:
            tag = map_action_to_live2d(a)
            if tag and tag not in collected_actions:
                collected_actions.append(tag)
        if tail:
            full_clean += tail
            yield {"type": "chunk", "text": tail}

        print(f"[Chat] 🔍 原始输出: {full_clean!r}", flush=True)
        reply, emotion = cls._parse_emotion(full_clean)
        conv.add("assistant", reply)

        # 🔥 异步提取记忆（用干净的对白，动作不会污染记忆）
        asyncio.create_task(
            extractor.extract_and_store(cls._provider, user_id, user_message, reply)
        )

        yield {
            "type": "final",
            "text": reply,
            "emotion": emotion,
            "session_id": session_id,
            "actions": collected_actions,
        }

    # ========== 工具方法 ==========

    @staticmethod
    def _parse_emotion(text: str) -> tuple:
        """从回复文本中解析 [情绪:xxx] 标签"""
        emotion = "冷静"
        if "[情绪:" in text or "[情绪：" in text:
            text = text.replace("[情绪：", "[情绪:")
            start = text.rfind("[情绪:") + 4
            end = text.rfind("]", start)
            if end > start:
                emotion = text[start:end].strip()
                text = text[:text.rfind("[情绪:")].strip()
        return text, emotion

    @classmethod
    def clear_session(cls, session_id: str) -> None:
        """清理指定会话"""
        if session_id in cls.conversations:
            del cls.conversations[session_id]