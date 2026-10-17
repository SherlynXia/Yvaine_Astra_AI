import json
import httpx
from typing import AsyncIterator
from .base import LLMProvider


class DeepSeekProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "deepseek-flash",
                 temperature: float = 0.8):
        self.api_key = api_key
        self.model = model
        self.temperature = temperature
        print(f"[LLM] 🐋 DeepSeekProvider: model={model}", flush=True)

    async def chat(self, messages: list[dict], temperature: float | None = None) -> str:
        result = ""
        async for chunk in self.chat_stream(messages, temperature=temperature):
            result += chunk
        return result

    async def chat_stream(self, messages: list[dict], temperature: float | None = None) -> AsyncIterator[str]:
        temp = temperature if temperature is not None else self.temperature
        timeout = httpx.Timeout(60.0, read=None)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                "https://api.deepseek.com/v1/chat/completions",
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": self.model,
                    "messages": messages,
                    "temperature": temp,
                    "max_tokens": 500,
                    "stream": True,
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.startswith("data:"):
                        continue
                    payload = line[5:].strip()
                    if payload == "[DONE]":
                        return
                    try:
                        data = json.loads(payload)
                    except json.JSONDecodeError:
                        continue
                    delta = data.get("choices", [{}])[0].get("delta", {})
                    content = delta.get("content", "")
                    if content:
                        yield content