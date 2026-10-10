from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """LLM 提供方抽象接口"""

    @abstractmethod
    async def chat(self, messages: list[dict]) -> str:
        """
        输入消息列表，返回纯文本回复（含 [情绪:xxx] 标签）

        messages 格式:
            [{"role": "system"/"user"/"assistant", "content": "..."}]
        """
        ...