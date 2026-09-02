import asyncio
import base64
import io
import json
import os
import sys
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

# 确保从 backend 目录加载 .env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv=env_path)


def _log(msg: str):
    print(msg, flush=True)


class TTSService:
    """语音合成服务 - 使用火山引擎豆包语音合成 2.0 (Seed-TTS-2.0) V3 API"""

    _initialized = False
    _appid: str = ""
    _token: str = ""
    _cluster: str = "volcano_tts"
    _voice_type: str = "zh_female_wanwanxiaohe_moon_bigtts"
    _api_url: str = "https://openspeech.bytedance.com/api/v3/tts/unidirectional"
    _emotion: str = ""

    @classmethod
    async def initialize(cls):
        """初始化 TTS 服务"""
        cls._appid = os.getenv("VOLCANO_APPID", "")
        cls._token = os.getenv("VOLCANO_TOKEN", "")
        cls._voice_type = os.getenv("VOLCANO_VOICE_TYPE", cls._voice_type)
        cls._emotion = os.getenv("VOLCANO_EMOTION", "")

        if not cls._appid or not cls._token:
            _log("[TTS] ⚠️ 未配置火山引擎 AppID 或 Token，TTS 将不可用")
            _log("[TTS] ⚠️ 请在 .env 中设置 VOLCANO_APPID 和 VOLCANO_TOKEN")
        else:
            _log(f"[TTS] 🔊 火山引擎 TTS V3 已准备就绪 (豆包语音合成 2.0)")
            _log(f"[TTS] 🔊 使用音色: {cls._voice_type}")
            if cls._emotion:
                _log(f"[TTS] 🔊 使用情感: {cls._emotion}")

        cls._initialized = True

    @classmethod
    async def synthesize(cls, text: str, emotion: str = "") -> str:
        """
        将文本转为语音 (使用 V3 单向流式接口)
        返回: base64 编码的音频数据，失败时返回空字符串
        """
        if not text or not text.strip():
            _log("[TTS] ⚠️ 文本为空，跳过合成")
            return ""

        if not cls._appid or not cls._token:
            _log("[TTS] ❌ 火山引擎未配置，无法合成")
            return ""

        _log(f"[TTS] 🔊 开始合成: '{text[:50]}...'")
        _log(f"[TTS] 🔊 使用音色: {cls._voice_type}")

        try:
            reqid = str(uuid.uuid4())

            # V3 接口请求体
            payload = {
                "app": {
                    "appid": cls._appid,
                    "token": cls._token,
                    "cluster": cls._cluster,
                },
                "user": {"uid": "yvaine_user"},
                "audio": {
                    "voice_type": cls._voice_type,
                    "encoding": "mp3",
                    "speed_ratio": 1.0,
                    "volume_ratio": 1.0,
                    "pitch_ratio": 1.0,
                },
                "request": {
                    "reqid": reqid,
                    "text": text,
                    "operation": "query",
                },
            }

            # 如果配置了情感参数，添加到请求中
            target_emotion = emotion or cls._emotion
            if target_emotion:
                payload["audio"]["emotion"] = target_emotion

            # V3 接口请求头
            headers = {
                "Authorization": f"Bearer;{cls._token}",
                "Content-Type": "application/json",
                "X-Api-App-Id": cls._appid,
                "X-Api-Access-Key": cls._token,
                "X-Api-Resource-Id": "volc.service_type.10029",
                "X-Api-Request-Id": reqid,
            }

            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.post(
                    cls._api_url,
                    json=payload,
                    headers=headers,
                )
                response.raise_for_status()

            # V3 流式响应处理
            audio_chunks = []
            async for line in response.aiter_lines():
                if not line.strip():
                    continue
                try:
                    chunk_data = json.loads(line)
                    chunk_code = chunk_data.get("code", -1)
                    if chunk_code != 3000:
                        message = chunk_data.get("message", "未知错误")
                        _log(f"[TTS] ❌ 火山引擎返回错误: code={chunk_code}, message={message}")
                        return ""
                    chunk_audio = chunk_data.get("data", "")
                    if chunk_audio:
                        audio_chunks.append(chunk_audio)
                except json.JSONDecodeError:
                    continue

            if not audio_chunks:
                _log("[TTS] ⚠️ 合成返回空音频数据")
                return ""

            audio_base64 = "".join(audio_chunks)

            # 解码检查
            audio_data = base64.b64decode(audio_base64)
            if len(audio_data) == 0:
                _log("[TTS] ⚠️ 解码后音频数据为空")
                return ""

            _log(f"[TTS] 🎵 合成完成: {len(text)} 字符, {len(audio_data)} 字节, base64长度: {len(audio_base64)}")
            return audio_base64

        except httpx.HTTPStatusError as e:
            _log(f"[TTS] ❌ HTTP 错误: {e.response.status_code} - {e.response.text}")
            return ""
        except Exception as e:
            _log(f"[TTS] ❌ 合成失败: {e}")
            import traceback
            _log(traceback.format_exc())
            return ""