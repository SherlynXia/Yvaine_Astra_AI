# backend/core/chat_service.py
"""对话服务 — 编排层：记忆检索 + LLM 流式 + 动作/对白分离 + 情绪解析 + 记忆提取"""

import asyncio
import uuid
from collections import deque
from datetime import datetime

from llm.base import LLMProvider
from memory.short_term import ConversationStore
from memory import extractor, retriever, user_manager
from core.action_parser import ActionParser, map_action_to_live2d


class ChatService:
    """对话服务：注入 LLMProvider 即可工作"""

    _provider: LLMProvider | None = None
    _system_prompt: str = ""
    # key = f"{session_id}:{user_id}"
    conversations: dict[str, ConversationStore] = {}

    # 场景活动流：session_id -> deque
    scene_recent: dict[str, deque] = {}
    SCENE_MAX = 20

    # ========== 配置 ==========

    @classmethod
    def configure(cls, provider: LLMProvider | None, system_prompt: str) -> None:
        cls._provider = provider
        cls._system_prompt = system_prompt
        if provider is None:
            print("[Chat] ⚠️ 未配置 LLM Provider，对话将不可用", flush=True)
        else:
            print(f"[Chat] ✅ LLM Provider 已就绪: {type(provider).__name__}", flush=True)

    # ========== 内部工具 ==========

    @classmethod
    def _get_or_create_conv(cls, session_id: str, user_id: str) -> ConversationStore:
        conv_key = f"{session_id}:{user_id}"
        if conv_key not in cls.conversations:
            cls.conversations[conv_key] = ConversationStore(
                max_turns=10, system_prompt=cls._system_prompt,
            )
            print(f"[Chat] 🆕 新建会话: {conv_key[:16]}...", flush=True)
        return cls.conversations[conv_key]

    @classmethod
    def _append_scene(cls, session_id: str, user_id: str, user_name: str, role: str, text: str):
        buf = cls.scene_recent.setdefault(session_id, deque(maxlen=cls.SCENE_MAX))
        buf.append({
            "user_id": user_id,
            "user_name": user_name,
            "role": role,
            "text": text,
            "ts": datetime.now().isoformat(),
        })

    @classmethod
    def _build_scene_block(cls, session_id: str, current_user_id: str) -> str:
        buf = cls.scene_recent.get(session_id)
        if not buf:
            return ""

        try:
            from memory.retriever import _relative_time
        except Exception:
            def _relative_time(_):
                return "刚才"

        lines = []
        for item in buf:
            if item["user_id"] == current_user_id:
                continue
            rel = _relative_time(item["ts"])
            if item["role"] == "assistant":
                lines.append(f"- [{rel}] 你（对{item['user_name']}）：{item['text'][:60]}")
            else:
                lines.append(f"- [{rel}] {item['user_name']}：{item['text'][:60]}")

        if not lines:
            return ""
        return "\n\n【本场景近期活动（其他人在场时）】\n" + "\n".join(lines)

    @classmethod
    def clear_scene(cls, session_id: str):
        cls.scene_recent.pop(session_id, None)

    @classmethod
    def _build_identity_prefix(
        cls,
        session_id: str,
        user_id: str,
        user_name: str,
    ) -> str:
        now = datetime.now()
        weekday = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"][now.weekday()]
        time_str = now.strftime(f"%Y-%m-%d %H:%M，{weekday}")

        # 🔥 查已知用户（排除当前说话人），用 user_manager 现成接口
        try:
            all_users = user_manager.list_users()
            known_names = [
                u["name"] for u in all_users
                if u.get("name") and u["user_id"] != user_id
            ]
        except Exception:
            known_names = []

        known_text = "、".join(known_names) if known_names else "（还没有认识其他人）"

        prefix = (
            f"\n\n【当前时间】{time_str}\n"
            f"如果对方问'现在几点'或'今天几号'，用这个时间回答。\n"
            f"\n【当前对话对象】名字：{user_name}\n"
            f"如果对方问'我是谁'，直接回答「{user_name}」。\n"
            f"\n【你已经认识的人】{known_text}\n"
            f"规则：如果对方提到一个不在这份名单里的名字，"
            f"**不要假装认识**，自然地追问一句「（那个名字）是谁呀？」。\n"
            f"如果对方回答了身份（比如'是我朋友'），你可以记住这条关系。\n"
        )

        scene_block = cls._build_scene_block(session_id, user_id)
        if scene_block:
            prefix += scene_block
            prefix += "\n（近期活动里提到的人可能在同一个场景中，你可以自然地提起，不用假装不知道。）\n"

        return prefix

    # ========== 非流式对话（保留兼容） ==========

    @classmethod
    async def chat(cls, user_message: str, session_id: str = "") -> tuple:
        if not session_id:
            session_id = str(uuid.uuid4())

        if cls._provider is None:
            return "抱歉，我的大脑暂时离线了...", "难过", session_id

        user_id = await user_manager.identify_user(session_id=session_id)
        user = user_manager.get_current_user(user_id)
        user_name = user.get("name") or "对方"

        conv = cls._get_or_create_conv(session_id, user_id)

        identity_prefix = cls._build_identity_prefix(session_id, user_id, user_name)
        original_prompt = conv.system_prompt
        conv.system_prompt = original_prompt + identity_prefix
        conv.add("user", user_message)

        try:
            raw_reply = await cls._provider.chat(conv.get_messages())
        except Exception as e:
            print(f"[Chat] ❌ Provider 调用失败: {e}", flush=True)
            conv.system_prompt = original_prompt
            return "思绪有些混乱...能再说一遍吗？", "疑惑", session_id
        finally:
            conv.system_prompt = original_prompt

        parser = ActionParser()
        clean, _ = parser.feed(raw_reply)
        tail, _ = parser.flush()
        clean += tail

        reply = clean.strip()
        emotion = parser.emotion or "冷静"
        conv.add("assistant", reply)

        cls._append_scene(session_id, user_id, user_name, "user", user_message)
        cls._append_scene(session_id, user_id, user_name, "assistant", reply)

        return reply, emotion, session_id

    # ========== 流式对话（核心） ==========

    @classmethod
    async def chat_stream(cls, user_message: str, session_id: str = ""):
        if not session_id:
            session_id = str(uuid.uuid4())

        if cls._provider is None:
            text = "抱歉，我的大脑暂时离线了..."
            yield {"type": "chunk", "text": text}
            yield {"type": "final", "text": text, "emotion": "难过",
                   "session_id": session_id, "actions": []}
            return

        user_id = await user_manager.identify_user(session_id=session_id)
        user = user_manager.get_current_user(user_id)
        user_name = user.get("name") or "对方"

        conv = cls._get_or_create_conv(session_id, user_id)

        # 检索记忆（失败不影响对话）
        memory_block = ""
        try:
            memory_block = await asyncio.to_thread(
                retriever.build_memory_block, user_message, user_id, user_name
            )
        except Exception as e:
            print(f"[Chat] ⚠️ 记忆检索失败（继续对话）: {e}", flush=True)

        identity_prefix = cls._build_identity_prefix(session_id, user_id, user_name)

        original_prompt = conv.system_prompt
        conv.system_prompt = original_prompt + identity_prefix + memory_block
        if memory_block:
            print(f"[Chat] 🧠 注入记忆 {memory_block.count('- ')} 条", flush=True)
        else:
            print("[Chat] 🧠 注入记忆 0 条", flush=True)

        conv.add("user", user_message)

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

        tail, tail_acts = parser.flush()
        for a in tail_acts:
            tag = map_action_to_live2d(a)
            if tag and tag not in collected_actions:
                collected_actions.append(tag)
        if tail:
            full_clean += tail
            yield {"type": "chunk", "text": tail}

        reply = full_clean.strip()
        emotion = parser.emotion or "冷静"
        conv.add("assistant", reply)

        # 写入场景活动流
        cls._append_scene(session_id, user_id, user_name, "user", user_message)
        cls._append_scene(session_id, user_id, user_name, "assistant", reply)

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
        """清理该 session 下所有用户的对话历史"""
        prefix = f"{session_id}:"
        keys = [k for k in cls.conversations if k.startswith(prefix)]
        for k in keys:
            del cls.conversations[k]
        if keys:
            print(f"[Chat] 🗑️ 清理会话: {session_id[:8]}... ({len(keys)} 个用户)", flush=True)