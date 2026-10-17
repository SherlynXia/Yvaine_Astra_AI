from abc import ABC, abstractmethod
from typing import AsyncIterator


class LLMProvider(ABC):
    """LLM 提供方抽象接口"""

    @abstractmethod
    async def chat(
        self,
        messages: list[dict],
        temperature: float | None = None,
    ) -> str:
        """非流式：返回完整回复。temperature 为 None 时用 Provider 默认值"""
        ...

    @abstractmethod
    def chat_stream(
        self,
        messages: list[dict],
        temperature: float | None = None,
    ) -> AsyncIterator[str]:
        """流式：逐个 yield 文本块"""
        ...