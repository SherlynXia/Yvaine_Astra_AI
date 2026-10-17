import json
import httpx
from typing import AsyncIterator
from .base import LLMProvider


class OllamaProvider(LLMProvider):
    def __init__(self, model: str = "qwen2.5:7b", host: str = "http://127.0.0.1:11434",
                temperature: float = 0.8):
        self.model = model
        self.host = host
        self.temperature = temperature
        print(f"[LLM] 🦙 OllamaProvider: model={model}", flush=True)

    async def chat(self, messages: list[dict], temperature: float | None = None) -> str:
        result = ""
        async for chunk in self.chat_stream(messages, temperature=temperature):
            result += chunk
        return result

    async def chat_stream(self, messages: list[dict], temperature: float | None = None) -> AsyncIterator[str]:
        temp = temperature if temperature is not None else self.temperature
        # 优先 /api/chat 流式
        try:
            timeout = httpx.Timeout(60.0, read=None)
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST",
                    f"{self.host}/api/chat",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "stream": True,
                        "options": {"temperature": temp, "num_predict": 500},
                    },
                ) as resp:
                    if resp.status_code == 200:
                        async for line in resp.aiter_lines():
                            if not line.strip():
                                continue
                            try:
                                data = json.loads(line)
                            except json.JSONDecodeError:
                                continue
                            content = data.get("message", {}).get("content", "")
                            if content:
                                yield content
                            if data.get("done"):
                                return
        except Exception as e:
            print(f"[LLM] /api/chat 流式失败，回退 generate: {e}", flush=True)

        # 回退 /api/generate 流式
        async for chunk in self._stream_via_generate(messages):
            yield chunk

    async def _stream_via_generate(self, messages: list[dict]):
        parts = []
        for msg in messages:
            role, content = msg.get("role", ""), msg.get("content", "")
            if role == "system":
                parts.append(f"【设定】{content}")
            elif role == "user":
                parts.append(f"用户：{content}")
            elif role == "assistant":
                parts.append(f"渊鸢：{content}")
        parts.append("渊鸢：")
        prompt = "\n\n".join(parts)

        timeout = httpx.Timeout(60.0, read=None)
        async with httpx.AsyncClient(timeout=timeout) as client:
            async with client.stream(
                "POST",
                f"{self.host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": True,
                    "options": {"temperature": 0.8, "num_predict": 500},
                },
            ) as resp:
                resp.raise_for_status()
                async for line in resp.aiter_lines():
                    if not line.strip():
                        continue
                    try:
                        data = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    content = data.get("response", "")
                    if content:
                        yield content
                    if data.get("done"):
                        return