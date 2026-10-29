# backend/memory/short_term.py
"""短期记忆：内存滑动窗口 + SQLite 持久化 + 上下文压缩"""

from . import database


class ConversationStore:
    def __init__(self, max_turns: int = 10, system_prompt: str = ""):
        self.history: list[dict] = []
        self.summaries: list[str] = []  
        self.max_turns = max_turns
        self.system_prompt = system_prompt
        self.session_id: str = ""
        self.user_id: str = ""

    def bind(self, session_id: str, user_id: str):
        self.session_id = session_id
        self.user_id = user_id
        try:
            loaded = database.load_conversation(
                session_id, user_id, limit=self.max_turns * 2
            )
            self.history = loaded
            if loaded:
                print(
                    f"[Chat] 📂 从库加载对话历史: {len(loaded)} 条 "
                    f"({session_id[:8]}:{user_id[:8]})",
                    flush=True,
                )
        except Exception as e:
            print(f"[Chat] ⚠️ 加载对话历史失败: {e}", flush=True)

    def add(self, role: str, content: str):
        self.history.append({"role": role, "content": content})
        max_len = self.max_turns * 2

        # 超过上限 4 条（2 轮）才触发压缩
        if len(self.history) > max_len + 4:
            overflow = self.history[:4]
            self.history = self.history[4:]

            try:
                import asyncio
                from . import summarizer
                loop = asyncio.get_running_loop()
                loop.create_task(
                    summarizer.compress_to_memory(self, overflow)
                )
            except Exception as e:
                print(f"[Chat] ⚠️ 触发压缩失败: {e}", flush=True)

        # 持久化到 conversation_history
        if self.session_id and self.user_id:
            try:
                database.append_conversation(
                    self.session_id, self.user_id, role, content
                )
            except Exception as e:
                print(f"[Chat] ⚠️ 写入对话历史失败: {e}", flush=True)

    def get_messages(self) -> list[dict]:
        messages = []
        if self.system_prompt:
            messages.append({"role": "system", "content": self.system_prompt})
        if self.summaries:
            summary_text = (
                "【之前的对话摘要】\n"
                + "\n".join(f"- {s}" for s in self.summaries[-5:])
            )
            messages.append({"role": "system", "content": summary_text})
        messages.extend(self.history)
        return messages

    def clear(self):
        self.history = []
        self.summaries = []