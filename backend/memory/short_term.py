# backend/memory/short_term.py
"""短期记忆：单会话的对话历史"""


class ConversationStore:
    """管理单会话的对话历史（滑动窗口）"""

    def __init__(self, max_turns: int = 10, system_prompt: str = ""):
        self.history: list[dict] = []
        self.max_turns = max_turns
        self.system_prompt = system_prompt

    def add(self, role: str, content: str):
        self.history.append({"role": role, "content": content})
        max_len = self.max_turns * 2  # 每轮 = user + assistant
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

    def get_recent_text(self, turns: int = 1) -> str:
        """取最近 N 轮的纯文本，用于记忆提取"""
        recent = self.history[-turns * 2:]
        lines = []
        for msg in recent:
            role = "用户" if msg["role"] == "user" else "渊鸢"
            lines.append(f"{role}：{msg['content']}")
        return "\n".join(lines)