# backend/services/chat_service.py
"""对话服务 — 管理会话记忆 + 调用 LLM Provider"""

import uuid
from .llm.base import LLMProvider


class ConversationStore:
    """管理单会话的对话历史（短期记忆）"""

    def __init__(self, max_turns: int = 10, system_prompt: str = ""):
        self.history: list[dict] = []
        self.max_turns = max_turns
        self.system_prompt = system_prompt

    def add(self, role: str, content: str):
        self.history.append({"role": role, "content": content})
        max_len = self.max_turns * 2
        if len(self.history) > max_len:
            self.history = self.history[-max_len:]

    def get_messages(self) -> list[dict]:
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        messages.extend(self.history)
        return messages

    def clear(self):
        self.history = []


class ChatService:
    """对话服务：注入 LLMProvider 即可工作"""

    _provider: LLMProvider | None = None
    _system_prompt: str = ""
    conversations: dict[str, ConversationStore] = {}

    @classmethod
    def configure(cls, provider: LLMProvider | None, system_prompt: str) -> None:
        """由 main.py 调用，注入 Provider 和人格设定"""
        cls._provider = provider
        cls._system_prompt = system_prompt
        if provider is None:
            print("[Chat] ⚠️ 未配置 LLM Provider，对话将不可用", flush=True)
        else:
            print(f"[Chat] ✅ LLM Provider 已就绪: {type(provider).__name__}", flush=True)

    @classmethod
    async def chat(cls, user_message: str, session_id: str = "") -> tuple:
        """多轮对话，返回 (reply, emotion, session_id)"""
        if not session_id:
            session_id = str(uuid.uuid4())

        if cls._provider is None:
            return "抱歉，我的大脑暂时离线了...", "难过", session_id

        if session_id not in cls.conversations:
            cls.conversations[session_id] = ConversationStore(
                max_turns=10,
                system_prompt=cls._system_prompt,
            )
            print(f"[Chat] 🆕 新建会话: {session_id[:8]}...", flush=True)

        conv = cls.conversations[session_id]
        conv.add("user", user_message)

        try:
            raw_reply = await cls._provider.chat(conv.get_messages())
        except Exception as e:
            print(f"[Chat] ❌ Provider 调用失败: {e}", flush=True)
            return "思绪有些混乱...能再说一遍吗？", "疑惑", session_id

        reply, emotion = cls._parse_emotion(raw_reply)
        conv.add("assistant", reply)
        return reply, emotion, session_id

    @staticmethod
    def _parse_emotion(text: str) -> tuple:
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
        if session_id in cls.conversations:
            del cls.conversations[session_id]