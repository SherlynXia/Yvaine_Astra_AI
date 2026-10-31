# backend/core/chat_service.py
"""对话服务 — 编排层：记忆检索 + LLM 流式 + 动作/对白分离 + 情绪解析 + 记忆提取"""

import asyncio
import re
import uuid
from datetime import datetime

from llm.base import LLMProvider
from memory.short_term import ConversationStore
from memory import extractor, retriever, user_manager, relationship, database
from core.action_parser import ActionParser, map_action_to_live2d


class ChatService:
    """对话服务：注入 LLMProvider 即可工作"""

    _provider: LLMProvider | None = None
    _system_prompt: str = ""
    _relation_asked: dict[str, set[str]] = {}     # session_id → 问过的名字集合
    _relation_pending: dict[str, str] = {}        # session_id → 待回答的目标名字
    # key = f"{session_id}:{user_id}"
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

    # ========== 内部工具 ==========

    @classmethod
    def _get_or_create_conv(cls, session_id: str, user_id: str) -> ConversationStore:
        conv_key = f"{session_id}:{user_id}"
        if conv_key not in cls.conversations:
            conv = ConversationStore(
                max_turns=10, system_prompt=cls._system_prompt,
            )
            conv.bind(session_id, user_id)
            cls.conversations[conv_key] = conv
            print(f"[Chat] 🆕 新建会话: {conv_key[:16]}...", flush=True)
        return cls.conversations[conv_key]

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

        return prefix

    @classmethod
    def _build_relation_hint(cls, session_id: str, user_id: str, user_message: str) -> str:
        """两个触发场景：
        1. 有人对当前用户声称过关系，但当前用户还没确认（双向确认，优先）
        2. 用户提到 X 但关系未知（C 方案）
        """
        asked = cls._relation_asked.setdefault(session_id, set())

        # 场景 1：双向确认
        conn = database.get_conn()
        pending_claims = conn.execute(
            "SELECT c.claimant_id, u.name FROM relation_claims c "
            "JOIN users u ON c.claimant_id = u.user_id "
            "WHERE c.target_id = ? AND c.source = 'user_stated' "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM relation_claims c2 "
            "  WHERE c2.claimant_id = c.target_id AND c2.target_id = c.claimant_id "
            "  AND c2.source = 'user_stated'"
            ")",
            (user_id,),
        ).fetchall()

        for pc in pending_claims:
            name = pc["name"]
            if name in asked:
                continue
            asked.add(name)
            return (
                f"\n【关系确认】\n"
                f"「{name}」之前提到过和你有关系，但你还没确认。\n"
                f"如果对话中有合适的时机，自然地问一句：「对了，你和{name}是什么关系呀？」\n"
                f"只问这一次，不要强行插入。\n"
            )

        # 场景 2：用户提到 X 但关系未知
        users = conn.execute(
            "SELECT user_id, name FROM users WHERE user_id != ? AND name != ''",
            (user_id,),
        ).fetchall()

        for u in users:
            name = u["name"]
            if name not in user_message or name in asked:
                continue
            rel = database.get_user_user_relationship(user_id, u["user_id"])
            if rel and rel["confidence"] >= 0.5:
                continue
            asked.add(name)
            return (
                f"\n【关系确认】\n"
                f"用户提到了「{name}」，但你不知道他们是什么关系。\n"
                f"请在回复末尾自然地顺带问一句：「对了，你和{name}是什么关系呀？」\n"
                f"只问这一次，以后不用再问。\n"
            )
        return ""

    @classmethod
    def _try_resolve_pending(cls, session_id: str, user_id: str, user_message: str, target_name: str) -> None:
        """用户回答「朋友」「同事」这类简短词时，补上主语。"""
        relation_kws = {
            "好朋友": "friend", "朋友": "friend", "好友": "friend", "闺蜜": "friend",
            "同事": "colleague", "同学": "colleague", "老板": "colleague",
            "家人": "family", "妈妈": "family", "爸爸": "family",
            "男朋友": "partner", "女朋友": "partner", "恋人": "partner",
            "对象": "partner", "老公": "partner", "老婆": "partner",
            "对手": "rival", "敌人": "rival",
        }
        # 否定词优先
        if any(n in user_message for n in ("不是", "不算是", "没有", "不算")):
            for kw in relation_kws:
                if kw in user_message:
                    cls._relation_pending.pop(session_id, None)
                    print(f"[Chat] ⏭️ 用户否定关系: {target_name}", flush=True)
                    return

        for kw, rtype in relation_kws.items():
            if kw in user_message:
                relationship.update_from_relation_info(user_id, {
                    "target_name": target_name,
                    "relation_type": rtype,
                    "confidence": 0.85,
                    "evidence": user_message,
                })
                cls._relation_pending.pop(session_id, None)
                print(f"[Chat] ✅ 关系确认: → {target_name} ({rtype})", flush=True)
                return

        # 用户没回答关系，清 pending（不追问）
        cls._relation_pending.pop(session_id, None)

    @classmethod
    def _post_turn_tasks(cls, session_id: str, user_id: str, user_name: str, user_message: str, reply: str) -> None:
        """对话结束后的统一收尾"""
        # 1. 检查上一轮 pending 是否被回答
        pending = cls._relation_pending.get(session_id)
        if pending:
            cls._try_resolve_pending(session_id, user_id, user_message, pending)

        # 2. 检测 AI 这轮是否问了关系
        m = re.search(r"你和([^\s，。,.!！?？]{1,20})是什么关系", reply)
        if m:
            target = m.group(1).strip()
            cls._relation_pending[session_id] = target
            print(f"[Chat] 🤔 AI 询问关系: {target}（等待用户回答）", flush=True)

        # 3. 关系更新（每轮三维 + 正则兜底识别）
        try:
            relationship.update_after_turn(user_id, user_message, reply)
        except Exception as e:
            print(f"[Chat] ⚠️ 关系更新失败: {e}", flush=True)

        try:
            relationship.try_auto_detect_relation(user_id, user_message)
        except Exception as e:
            print(f"[Chat] ⚠️ 关系识别失败: {e}", flush=True)

        # 4. 异步任务
        asyncio.create_task(
            extractor.extract_and_store(cls._provider, user_id, user_message, reply)
        )
        asyncio.create_task(
            extractor.reflect_on_self(
                cls._provider, user_id, user_name, user_message, reply
            )
        )

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

        cls._post_turn_tasks(session_id, user_id, user_name, user_message, reply)

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

        # ---- 记忆检索（类型安全，失败兜底为空串） ----
        memory_block = ""
        try:
            raw = await asyncio.to_thread(
                retriever.build_memory_block, user_message, user_id, user_name, session_id
            )
            if isinstance(raw, str):
                memory_block = raw
            elif raw is not None:
                print(f"[Chat] ⚠️ build_memory_block 返回非 str: {type(raw).__name__}", flush=True)
        except Exception as e:
            import traceback
            print(f"[Chat] ⚠️ 记忆检索失败（继续对话）: {e}", flush=True)
            traceback.print_exc()

        identity_prefix = cls._build_identity_prefix(session_id, user_id, user_name) or ""
        relation_hint = cls._build_relation_hint(session_id, user_id, user_message)

        original_prompt = conv.system_prompt or ""
        conv.system_prompt = original_prompt + identity_prefix + relation_hint + memory_block

        if memory_block:
            print(f"[Chat] 🧠 注入记忆 {memory_block.count('- ')} 条", flush=True)
            print(f"[Chat] 📄 memory_block:\n{memory_block}", flush=True)
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

        cls._post_turn_tasks(session_id, user_id, user_name, user_message, reply)

        yield {
            "type": "final",
            "text": reply,
            "emotion": emotion,
            "session_id": session_id,
            "actions": collected_actions,
        }

    @classmethod
    async def _maybe_self_review(cls, session_id: str, user_id: str, user_name: str):
        """断开时检查：本次会话 >= 6 轮，触发主动回看"""
        conv_key = f"{session_id}:{user_id}"
        conv = cls.conversations.get(conv_key)
        if not conv or len(conv.history) < 12:
            return

        try:
            await extractor.self_review(
                cls._provider, user_id, user_name, conv.history[-12:]
            )
        except Exception as e:
            print(f"[Chat] ⚠️ 主动回看失败: {e}", flush=True)

    # ========== 工具方法 ==========

    @classmethod
    def clear_session(cls, session_id: str) -> None:
        """清理该 session 下所有用户的对话历史"""
        prefix = f"{session_id}:"
        keys = [k for k in cls.conversations if k.startswith(prefix)]
        for k in keys:
            del cls.conversations[k]
        if keys:
            print(f"[Chat] 🗑️ 清理会话: {session_id[:8]}... ({len(keys)} 个用户)", flush=True)