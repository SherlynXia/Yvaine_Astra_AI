# backend/tts/facade.py
import os
import json
import uuid
import httpx

from .websocket import TTSWebSocketService
from .bidi import TTSBidirectionalService, TTSResult

VOLCANO_APPID = os.getenv("VOLCANO_APPID", "")
VOLCANO_TOKEN = os.getenv("VOLCANO_TOKEN", "")
VOLCANO_VOICE = os.getenv("VOLCANO_VOICE_TYPE", "zh_female_wanwanxiaohe_moon_bigtts")
TTS_MODE = os.getenv("TTS_MODE", "bidi").lower()


def log(msg: str):
    print(msg, flush=True)


class TTSService:
    @staticmethod
    async def initialize():
        if TTS_MODE == "bidi":
            await TTSBidirectionalService.initialize()
            log("[TTS] 使用双向流式模式 (支持 phoneme 时间戳)")
        elif TTS_MODE == "websocket":
            await TTSWebSocketService.initialize()
            log("[TTS] 使用 WebSocket 单向流式模式")
        else:
            log("[TTS] 使用 HTTP V3 模式")

    @staticmethod
    async def synthesize(text: str, emotion: str = "") -> str:
        if not text or not VOLCANO_TOKEN:
            return ""
        if TTS_MODE == "bidi":
            result = await TTSBidirectionalService.synthesize(text, emotion)
            return result.audio_base64
        elif TTS_MODE == "websocket":
            return await TTSWebSocketService.synthesize(text, emotion)
        else:
            return await TTSService._http_synthesize(text, emotion)

    @staticmethod
    async def synthesize_with_phonemes(text: str, emotion: str = "") -> TTSResult:
        if not text or not VOLCANO_TOKEN:
            return TTSResult()
        if TTS_MODE == "bidi":
            return await TTSBidirectionalService.synthesize(text, emotion)
        result = TTSResult()
        result.audio_base64 = await TTSService.synthesize(text, emotion)
        return result

    @staticmethod
    async def _http_synthesize(text: str, emotion: str = "") -> str:
        """HTTP V3 备用方案"""
        import httpx

        reqid = str(uuid.uuid4())
        payload = {
            "app": {"appid": VOLCANO_APPID, "token": VOLCANO_TOKEN, "cluster": "volcano_tts"},
            "user": {"uid": "yvaine"},
            "audio": {
                "voice_type": VOLCANO_VOICE,
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

        if emotion:
            payload["audio"]["emotion"] = emotion

        headers = {
            "Authorization": f"Bearer;{VOLCANO_TOKEN}",
            "Content-Type": "application/json",
            "X-Api-App-Id": VOLCANO_APPID,
            "X-Api-Access-Key": VOLCANO_TOKEN,
            "X-Api-Resource-Id": "volc.service_type.10029",
            "X-Api-Request-Id": reqid,
        }

        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post("https://openspeech.bytedance.com/api/v3/tts/unidirectional", json=payload, headers=headers)

        audio_chunks = []
        async for line in resp.aiter_lines():
            if not line.strip():
                continue
            try:
                chunk_data = json.loads(line)
                chunk_code = chunk_data.get("code", -1)
                if chunk_code != 3000:
                    log(f"[TTS] 错误: {chunk_data}")
                    return ""
                chunk_audio = chunk_data.get("data", "")
                if chunk_audio:
                    audio_chunks.append(chunk_audio)
            except json.JSONDecodeError:
                continue

        if not audio_chunks:
            log("[TTS] 合成返回空音频数据")
            return ""

        return "".join(audio_chunks)