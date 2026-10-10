import httpx
from .base import LLMProvider


class OllamaProvider(LLMProvider):
    """本地 Ollama 模型提供方"""

    def __init__(self, model: str = "qwen2.5:7b", host: str = "http://127.0.0.1:11434"):
        self.model = model
        self.host = host
        print(f"[LLM] 🦙 OllamaProvider: model={model}, host={host}", flush=True)

    async def chat(self, messages: list[dict]) -> str:
        # 优先尝试新版 /api/chat 接口
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{self.host}/api/chat",
                    json={
                        "model": self.model,
                        "messages": messages,
                        "stream": False,
                        "options": {"temperature": 0.8, "num_predict": 500},
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    content = data.get("message", {}).get("content", "").strip()
                    if content:
                        return content
        except Exception as e:
            print(f"[LLM] /api/chat 失败，回退 /api/generate: {e}", flush=True)

        # 回退：手动拼接 prompt 到 /api/generate
        return await self._chat_via_generate(messages)

    async def _chat_via_generate(self, messages: list[dict]) -> str:
        parts = []
        for msg in messages:
            role = msg.get("role", "")
            content = msg.get("content", "")
            if role == "system":
                parts.append(content)
            elif role == "user":
                parts.append(f"用户：{content}")
            elif role == "assistant":
                parts.append(f"渊鸢：{content}")
        parts.append("渊鸢：")
        prompt = "\n\n".join(parts)

        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(
                f"{self.host}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.8, "num_predict": 500},
                },
            )
            resp.raise_for_status()
            return resp.json().get("response", "嗯...").strip()