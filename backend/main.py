import os
import sys
import json
import asyncio
import base64
import uuid
from pathlib import Path

# 加载环境变量
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

# ========== 配置 ==========
PORT = int(os.getenv("PYTHON_PORT", "8000"))
HOST = os.getenv("PYTHON_HOST", "127.0.0.1")

VOLCANO_APPID = os.getenv("VOLCANO_APPID", "")
VOLCANO_TOKEN = os.getenv("VOLCANO_TOKEN", "")
VOLCANO_VOICE = os.getenv("VOLCANO_VOICE_TYPE", "zh_female_wanwanxiaohe_moon_bigtts")

# TTS 模式: http / websocket / bidi (双向流式，支持 phoneme 时间戳)
TTS_MODE = os.getenv("TTS_MODE", "bidi").lower()

DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")
USE_OLLAMA = os.getenv("USE_OLLAMA", "false").lower() == "true"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:3b")

# ========== 日志 ==========
def log(msg: str):
    print(msg, flush=True)

# ========== TTS 服务 ==========
from services.tts_ws_service import TTSWebSocketService
from services.tts_bidi_service import TTSBidirectionalService, TTSResult

class TTSService:
    @staticmethod
    async def initialize():
        """初始化 TTS 服务"""
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
        """仅返回音频 base64（兼容旧接口）"""
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
        """返回音频 + phoneme 时间轴（新接口）"""
        if not text or not VOLCANO_TOKEN:
            return TTSResult()

        if TTS_MODE == "bidi":
            return await TTSBidirectionalService.synthesize(text, emotion)
        else:
            # 非 bidi 模式下只返回音频，phonemes 为空
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

# ========== Chat 服务 ==========
class ChatService:
    @staticmethod
    async def chat(user_msg: str) -> tuple:
        system = """你是 Yvaine（伊文），一个温柔、聪明、略带调皮的 AI 女孩。
说话温柔，偶尔撒娇，喜欢用「呢」「呀」「~」。
回复末尾用 [情绪:xxx] 标注情绪，可选：开心、害羞、生气、难过、惊讶、疑惑、调皮、困倦"""
        
        if USE_OLLAMA:
            return await ChatService._ollama_chat(system, user_msg)
        elif DEEPSEEK_KEY:
            return await ChatService._deepseek_chat(system, user_msg)
        else:
            return "抱歉，我的大脑暂时离线了...", "难过"
    
    @staticmethod
    async def _ollama_chat(system: str, user_msg: str) -> tuple:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post("http://127.0.0.1:11434/api/generate", json={
                    "model": OLLAMA_MODEL,
                    "prompt": f"{system}\n\n用户：{user_msg}\nYvaine：",
                    "stream": False,
                    "options": {"temperature": 0.8, "num_predict": 500},
                })
                data = resp.json()
                content = data.get("response", "嗯...").strip()
                return ChatService._parse_emotion(content)
        except Exception as e:
            log(f"[Chat] Ollama 错误: {e}")
            return "哎呀，我的思绪有点乱...", "疑惑"
    
    @staticmethod
    async def _deepseek_chat(system: str, user_msg: str) -> tuple:
        import httpx
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                resp = await client.post("https://api.deepseek.com/v1/chat/completions", headers={
                    "Authorization": f"Bearer {DEEPSEEK_KEY}",
                    "Content-Type": "application/json",
                }, json={
                    "model": "deepseek-chat",
                    "messages": [
                        {"role": "system", "content": system},
                        {"role": "user", "content": user_msg},
                    ],
                    "temperature": 0.8,
                    "max_tokens": 500,
                })
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                return ChatService._parse_emotion(content)
        except Exception as e:
            log(f"[Chat] DeepSeek 错误: {e}")
            return "哎呀，我的思绪有点乱...", "疑惑"
    
    @staticmethod
    def _parse_emotion(text: str) -> tuple:
        emotion = "开心"
        if "[情绪:" in text or "[情绪：" in text:
            text = text.replace("[情绪：", "[情绪:")
            start = text.rfind("[情绪:") + 4
            end = text.rfind("]", start)
            if end > start:
                emotion = text[start:end].strip()
                text = text[:text.rfind("[情绪:")].strip()
        return text, emotion

# ========== FastAPI 应用 ==========
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"])

@app.get("/")
async def root():
    return {"status": "ok", "message": "Yvaine is running!"}

@app.get("/health")
async def health():
    return {"status": "healthy"}

@app.get("/test-tts")
async def test_tts():
    """测试 TTS 合成"""
    audio = await TTSService.synthesize("你好，我是 Yvaine")
    return {"status": "ok" if audio else "error", "length": len(audio) if audio else 0, "mode": TTS_MODE}

@app.get("/test-tts-emotion")
async def test_tts_emotion():
    """测试带情感的 TTS 合成"""
    results = {}
    for emotion in ["happy", "sad", "angry", "surprised"]:
        audio = await TTSService.synthesize("你好，我是 Yvaine，今天心情怎么样？", emotion=emotion)
        results[emotion] = {"status": "ok" if audio else "error", "length": len(audio) if audio else 0}
    return {"mode": TTS_MODE, "results": results}

@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    await ws.accept()
    log("✨ WebSocket 连接建立")
    
    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)
            user_text = msg.get("text", "").strip()
            if not user_text:
                continue
            
            log(f"[User] {user_text}")
            
            # 获取回复
            reply, emotion = await ChatService.chat(user_text)
            log(f"[Yvaine] {reply[:50]}...")
            
            # 发送文本
            await ws.send_json({"type": "message", "text": reply, "emotion": emotion})
            
            # TTS - 根据情绪映射到语音情感参数
            emotion_map = {
                "开心": "happy",
                "害羞": "neutral",
                "生气": "angry",
                "难过": "sad",
                "惊讶": "surprised",
                "疑惑": "neutral",
                "调皮": "happy",
                "困倦": "neutral",
            }
            tts_emotion = emotion_map.get(emotion, "")

            # 使用新接口获取音频 + phoneme 时间轴
            tts_result = await TTSService.synthesize_with_phonemes(reply, emotion=tts_emotion)

            if tts_result.audio_base64:
                # 发送音频
                await ws.send_json({"type": "audio", "audioBase64": tts_result.audio_base64})

                # 如果有 phoneme 数据，一并发送给前端用于精确口型同步
                if tts_result.phonemes:
                    await ws.send_json({
                        "type": "phonemes",
                        "phonemes": [p.to_dict() for p in tts_result.phonemes],
                        "words": [w.to_dict() for w in tts_result.words],
                        "durationMs": tts_result.duration_ms,
                    })
                    log(f"🎵 音频+Phoneme 已发送 (情感: {tts_emotion or '默认'}, phonemes={len(tts_result.phonemes)})")
                else:
                    log(f"🎵 音频已发送 (情感: {tts_emotion or '默认'})")
            else:
                log("⚠️ TTS 失败")
    
    except WebSocketDisconnect:
        log("💫 WebSocket 断开")
    except Exception as e:
        log(f"❌ WebSocket 错误: {e}")

# ========== 启动 ==========
if __name__ == "__main__":
    try:
        import uvicorn

        # 初始化 TTS 服务
        asyncio.run(TTSService.initialize())

        log(f"🚀 启动 Yvaine 后端服务 {HOST}:{PORT}")
        log(f"   环境变量 PYTHON_PORT={os.getenv('PYTHON_PORT', '未设置')}")
        log(f"   工作目录: {os.getcwd()}")
        log(f"   TTS 模式: {TTS_MODE}")
        uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
    except KeyboardInterrupt:
        log("\n👋 收到退出信号，正在清理...")
        if TTS_MODE == "bidi":
            asyncio.run(TTSBidirectionalService.close())
        elif TTS_MODE == "websocket":
            asyncio.run(TTSWebSocketService.close())
        sys.exit(0)
    except Exception as e:
        sys.stderr.write(f"启动失败: {e}\n")
        sys.stderr.write(f"类型: {type(e).__name__}\n")
        import traceback
        traceback.print_exc()
        sys.exit(1)