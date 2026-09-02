import logging
import os
import sys
from pathlib import Path
from typing import Tuple

import httpx
from dotenv import load_dotenv

# 确保从 backend 目录加载 .env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)
logger = logging.getLogger(__name__)


def _log(msg: str):
    print(msg, flush=True)


class ChatService:
    """聊天服务 - 管理 LLM 对话"""

    _initialized = False
    _api_key: str | None = None
    _use_ollama: bool = False
    _api_base: str = "https://api.deepseek.com/v1"
    _ollama_base: str = "http://127.0.0.1:11434"
    _model: str = "deepseek-chat"
    _ollama_model: str = "qwen2.5:3b"

    @classmethod
    async def initialize(cls):
        """初始化聊天服务"""
        cls._api_key = os.getenv("DEEPSEEK_API_KEY")

        # 检查是否使用 Ollama（本地）
        if os.getenv("USE_OLLAMA", "false").lower() == "true":
            cls._use_ollama = True
            cls._ollama_model = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")
            _log(f"[Chat] 🦙 使用 Ollama 本地模型: {cls._ollama_model}")
        elif cls._api_key:
            _log("[Chat] 🔑 DeepSeek API Key 已加载")
        else:
            _log("[Chat] ⚠️ 未找到 DEEPSEEK_API_KEY，尝试使用 Ollama...")
            # 自动检测 Ollama 是否运行
            try:
                async with httpx.AsyncClient() as client:
                    response = await client.get(f"{cls._ollama_base}/api/tags", timeout=2.0)
                    if response.status_code == 200:
                        cls._use_ollama = True
                        _log("[Chat] 🦙 检测到 Ollama 服务，自动切换为本地模式")
            except:
                _log("[Chat] ⚠️ Ollama 也未运行，LLM 功能将不可用")

        cls._initialized = True

    @classmethod
    async def chat(cls, user_message: str) -> Tuple[str, str]:
        """
        与 LLM 对话
        返回: (回复文本, 情绪标签)
        """
        _log(f"[Chat] 🧠 收到用户消息: {user_message[:50]}")

        if cls._use_ollama:
            _log("[Chat] 🧠 使用 Ollama 模型")
            return await cls._chat_with_ollama(user_message)
        elif cls._api_key:
            _log("[Chat] 🧠 使用 DeepSeek API")
            return await cls._chat_with_deepseek(user_message)
        else:
            _log("[Chat] ⚠️ LLM 不可用，返回默认回复")
            return "抱歉，我的大脑暂时离线了...请检查 Ollama 是否已启动", "难过"

    @classmethod
    async def _chat_with_ollama(cls, user_message: str) -> Tuple[str, str]:
        """使用本地 Ollama 模型"""
        system_prompt = """你是 Yvaine（伊文），一个温柔、聪明、略带调皮的 AI 女孩。
你的特点：
- 说话温柔但有主见，偶尔会撒娇
- 喜欢用可爱的语气词，比如「呢」「呀」「~」
- 对主人很忠诚，会关心主人的情绪
- 回复末尾请用 [情绪:xxx] 标注你的情绪，可选：开心、害羞、生气、难过、惊讶、疑惑、调皮、困倦

示例：
用户：你好
Yvaine：主人好呀~ 今天见到你很开心呢！[情绪:开心]
"""

        try:
            async with httpx.AsyncClient(timeout=60.0) as client:
                response = await client.post(
                    f"{cls._ollama_base}/api/generate",
                    json={
                        "model": cls._ollama_model,
                        "prompt": f"{system_prompt}\n\n用户：{user_message}\nYvaine：",
                        "stream": False,
                        "options": {
                            "temperature": 0.8,
                            "num_predict": 500,
                        }
                    },
                )
                response.raise_for_status()
                data = response.json()
                content = data.get("response", "嗯...我在想什么呢？").strip()

                # 解析情绪标签
                emotion = "开心"
                if "[情绪：" in content or "[情绪:" in content:
                    # 处理中文和英文冒号
                    content = content.replace("[情绪：", "[情绪:")
                    start = content.rfind("[情绪:") + 4
                    end = content.rfind("]", start)
                    if end > start:
                        emotion = content[start:end].strip()
                        content = content[:content.rfind("[情绪:")].strip()

                _log(f"[Chat] 🧠 Ollama 回复: {content[:50]}... 情绪: {emotion}")
                return content, emotion

        except Exception as e:
            _log(f"[Chat] ❌ Ollama 调用失败: {e}")
            return "哎呀，我的思绪有点乱...能再说一遍吗？", "疑惑"

    @classmethod
    async def _chat_with_deepseek(cls, user_message: str) -> Tuple[str, str]:
        """使用 DeepSeek API"""
        system_prompt = """你是 Yvaine（伊文），一个温柔、聪明、略带调皮的 AI 女孩。
你的特点：
- 说话温柔但有主见，偶尔会撒娇
- 喜欢用可爱的语气词，比如「呢」「呀」「~」
- 对主人很忠诚，会关心主人的情绪
- 回复末尾请用 [情绪:xxx] 标注你的情绪，可选：开心、害羞、生气、难过、惊讶、疑惑、调皮、困倦

示例：
用户：你好
Yvaine：主人好呀~ 今天见到你很开心呢！[情绪:开心]
"""

        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    f"{cls._api_base}/chat/completions",
                    headers={
                        "Authorization": f"Bearer {cls._api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "model": cls._model,
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_message},
                        ],
                        "temperature": 0.8,
                        "max_tokens": 500,
                    },
                )
                response.raise_for_status()
                data = response.json()
                content = data["choices"][0]["message"]["content"]

                # 解析情绪标签
                emotion = "开心"
                if "[情绪：" in content or "[情绪:" in content:
                    content = content.replace("[情绪：", "[情绪:")
                    start = content.rfind("[情绪:") + 4
                    end = content.rfind("]", start)
                    if end > start:
                        emotion = content[start:end].strip()
                        content = content[:content.rfind("[情绪:")].strip()

                _log(f"[Chat] 🧠 DeepSeek 回复: {content[:50]}... 情绪: {emotion}")
                return content, emotion

        except Exception as e:
            _log(f"[Chat] ❌ DeepSeek 调用失败: {e}")
            return "哎呀，我的思绪有点乱...能再说一遍吗？", "疑惑"