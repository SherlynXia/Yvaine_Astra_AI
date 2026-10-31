import os
import sys
import json
import asyncio
import base64
import uuid
from pathlib import Path
from contextlib import asynccontextmanager

# 加载环境变量
from dotenv import load_dotenv
load_dotenv(Path(__file__).parent / ".env")

# ========== 配置 ==========
PORT = int(os.getenv("PYTHON_PORT", "8000"))
HOST = os.getenv("PYTHON_HOST", "127.0.0.1")

# TTS 模式: http / websocket / bidi (双向流式，支持 phoneme 时间戳)
USE_OLLAMA = os.getenv("USE_OLLAMA", "false").lower() == "true"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
DEEPSEEK_KEY = os.getenv("DEEPSEEK_API_KEY", "")

# ========== 日志 ==========
def log(msg: str):
    print(msg, flush=True)

# ========== 服务导入 ==========
from tts import TTSService, TTS_MODE, TTSWebSocketService, TTSBidirectionalService, TTSResult
from core.chat_service import ChatService
from memory import user_manager
from feedback.manager import save_feedback, get_feedback_stats
from llm import OllamaProvider, DeepSeekProvider

# ========== 句子切分 ==========
_SENTENCE_ENDINGS = "。！？!?."

# ========== 情绪映射 ==========
EMOTION_MAP = {
    "开心": "happy", "温柔": "neutral", "傲娇": "neutral",
    "冷静": "neutral", "担忧": "sad", "困倦": "neutral",
    "好奇": "surprised", "欣慰": "happy", "无奈": "sad",
    "生气": "angry", "难过": "sad", "惊讶": "surprised",
    "疑惑": "neutral", "调皮": "happy",
}

# ========== 待评分消息缓存 ==========
pending_feedback: dict[str, dict] = {}
_MAX_PENDING = 100  # 最多缓存 100 条未评分消息

class SentenceBuffer:
    """累积流式文本，遇到句末标点切出一个完整句子"""

    def __init__(self, min_len: int = 2):
        self.buffer = ""
        self.min_len = min_len

    def feed(self, text: str) -> list[str]:
        self.buffer += text
        sentences = []
        start = 0
        for i, ch in enumerate(self.buffer):
            if ch in _SENTENCE_ENDINGS:
                sentence = self.buffer[start:i + 1].strip()
                if len(sentence) >= self.min_len:
                    sentences.append(sentence)
                start = i + 1
        self.buffer = self.buffer[start:]
        return sentences

    def flush(self) -> str:
        result = self.buffer.strip()
        self.buffer = ""
        return result


# ========== FastAPI 应用 ==========
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

@asynccontextmanager
async def lifespan(app: FastAPI):
    # ===== startup =====

    # 1. 记忆生命周期任务
    if ChatService._provider is None:
        log("[Memory] ⚠️ LLM Provider 未配置，生命周期任务跳过")
    else:
        from memory.lifecycle import lifecycle_loop
        asyncio.create_task(lifecycle_loop(ChatService._provider, interval_hours=6.0))
        log("[Memory] 🧹 生命周期任务已启动（每 6 小时）")

    # 2. ChromaDB 异步预热
    async def _warmup():
        try:
            from memory import vector_store
            for name in ("user_memories", "ai_reflections", "ai_behaviors", "workspace_items"):
                await asyncio.to_thread(vector_store._get_collection, name)
            log("[Memory] ✅ ChromaDB 预热完成（4 个 collection）")
        except Exception as e:
            log(f"[Memory] ⚠️ ChromaDB 预热失败（首次聊天时会懒加载）: {e}")

    asyncio.create_task(_warmup())

    yield  # ← 应用运行中

    # ===== shutdown =====
    # 目前没有需要清理的资源，留空


app = FastAPI(lifespan=lifespan)
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


@app.get("/feedback/stats")
async def feedback_stats():
    """反馈统计"""
    return get_feedback_stats()

@app.websocket("/ws/chat")
async def ws_chat(ws: WebSocket):
    await ws.accept()
    session_id = ws.query_params.get("session_id") or str(uuid.uuid4())
    current_user_id = "default" 
    current_user_name = "对方" 

    log(f"✨ WebSocket 连接建立 | 会话: {session_id[:8]}...")

    try:
        while True:
            data = await ws.receive_text()
            msg = json.loads(data)

            # ---------- 登录 ----------
            if msg.get("type") == "login":
                user_id = msg.get("userId", "default")
                user_manager.bind_session(session_id, user_id)
                user = user_manager.get_current_user(user_id)
                log(f"[Auth] 登录: {user.get('name')} ({user_id[:8]})")
                current_user_id = user_id
                current_user_name = user.get("name") or "对方"
                await ws.send_json({
                    "type": "login_ack",
                    "userId": user_id,
                    "name": user.get("name", ""),
                })
                continue

            # ---------- 获取用户列表 ----------
            if msg.get("type") == "list_users":
                await ws.send_json({
                    "type": "user_list",
                    "users": user_manager.list_users(),
                })
                continue

            # ---------- 新建用户 ----------
            if msg.get("type") == "create_user":
                name = msg.get("name", "").strip()
                if name:
                    user = user_manager.create_user(name)
                    log(f"[Auth] 新建用户: {name}")
                    await ws.send_json({"type": "user_created", **user})
                continue

            # ---------- 评分消息 ----------
            if msg.get("type") == "feedback":
                message_id = msg.get("messageId", "")
                rating = msg.get("rating", "")
                if message_id and rating in ("good", "bad"):
                    context = pending_feedback.pop(message_id, None)
                    if context:
                        ok = save_feedback(context, rating)
                        log(f"[Feedback] {'✅' if ok else '❌'} {rating}: {message_id[:8]}")
                        await ws.send_json({
                            "type": "feedback_ack",
                            "status": "ok" if ok else "save_failed",
                            "messageId": message_id,
                        })
                    else:
                        await ws.send_json({
                            "type": "feedback_ack",
                            "status": "not_found",
                            "messageId": message_id,
                        })
                continue

            # ---------- 聊天消息 ----------
            user_text = msg.get("text", "").strip()
            if not user_text:
                continue

            # 同步当前用户（防止未登录直接聊的场景）
            if current_user_id == "default":
                current_user_id = await user_manager.identify_user(session_id=session_id)
                user = user_manager.get_current_user(current_user_id)
                current_user_name = user.get("name") or "对方"

            log(f"[User] {user_text}")

            # 流式接收 + 句子切分
            sentence_buf = SentenceBuffer()
            sentences: list[str] = []
            emotion = "冷静"
            actions: list[str] = []
            message_id = str(uuid.uuid4())

            async for event in ChatService.chat_stream(user_text, session_id):
                if event["type"] == "chunk":
                    sentences.extend(sentence_buf.feed(event["text"]))
                elif event["type"] == "final":
                    emotion = event["emotion"]
                    actions = event.get("actions", [])
                    tail = sentence_buf.flush()
                    if tail:
                        sentences.append(tail)

            full_reply = "".join(sentences) if sentences else ""
            log(f"[渊鸢] {full_reply[:50]}... | 情绪: {emotion}")

            # 情绪映射
            tts_emotion = EMOTION_MAP.get(emotion, "")

            # 缓存反馈上下文
            pending_feedback[message_id] = {
                "message_id": message_id,
                "session_id": session_id,
                "user_id": current_user_id,
                "user_message": user_text,
                "ai_reply": full_reply,
                "emotion": emotion,
                "tts_emotion": tts_emotion,
            }
            while len(pending_feedback) > _MAX_PENDING:
                oldest = next(iter(pending_feedback))
                del pending_feedback[oldest]

            # 发送完整文本（前端一次性显示）
            await ws.send_json({
                "type": "message",
                "text": full_reply,
                "emotion": emotion,
                "actions": actions,
                "sessionId": session_id,
                "messageId": message_id,
            })

            # 逐句合成 TTS 并按顺序发送
            total = len(sentences)
            for idx, sentence in enumerate(sentences):
                tts_result = await TTSService.synthesize_with_phonemes(
                    sentence, emotion=tts_emotion
                )
                if tts_result.audio_base64:
                    await ws.send_json({
                        "type": "audio",
                        "audioBase64": tts_result.audio_base64,
                        "phonemes": [p.to_dict() for p in tts_result.phonemes] if tts_result.phonemes else None,
                        "words": [w.to_dict() for w in tts_result.words] if tts_result.words else None,
                        "durationMs": tts_result.duration_ms,
                        "sequenceIndex": idx,
                        "isLastChunk": idx == total - 1,
                    })
                    log(f"🎵 句子 {idx+1}/{total} 音频已发送 ({len(sentence)} 字)")
                else:
                    log(f"⚠️ 句子 {idx+1}/{total} TTS 失败")

    except WebSocketDisconnect:
        log(f"💫 WebSocket 断开 | 会话: {session_id[:8]}...")
        try:
            await ChatService._maybe_self_review(
                session_id, current_user_id, current_user_name
            )
        except Exception as e:
            log(f"⚠️ 主动回看失败: {e}")
        user_manager.unbind_session(session_id)
        ChatService.clear_session(session_id)
    except Exception as e:
        log(f"❌ WebSocket 错误: {e}")
        user_manager.unbind_session(session_id)
        ChatService.clear_session(session_id)


# ========== 启动 ==========
if __name__ == "__main__":
    try:
        import uvicorn

        # 1. 初始化 TTS
        asyncio.run(TTSService.initialize())

        # 2. 选择并配置 LLM Provider
        if USE_OLLAMA:
            _provider = OllamaProvider(model=OLLAMA_MODEL)
        elif DEEPSEEK_KEY:
            _provider = DeepSeekProvider(api_key=DEEPSEEK_KEY)
        else:
            _provider = None
            log("⚠️ 未配置任何 LLM（USE_OLLAMA=false 且 DEEPSEEK_API_KEY 为空）")

        # 3. 加载人格设定
        _personality_path = Path(__file__).parent / "personality" / "system_prompt.txt"
        try:
            _system_prompt = _personality_path.read_text(encoding="utf-8")
            log(f"[Chat] ✅ 已加载人格设定: {_personality_path}")
        except Exception as e:
            log(f"[Chat] ⚠️ 人格设定加载失败: {e}")
            _system_prompt = "你是渊鸢（Yvaine Astra），一个理性而温柔的 AI 旅伴。回复末尾用 [情绪:冷静] 标注情绪。"

        # 4. 注入 ChatService
        ChatService.configure(provider=_provider, system_prompt=_system_prompt)


        log(f"🚀 启动 Yvaine 后端服务 {HOST}:{PORT}")
        log(f"   环境变量 PYTHON_PORT={os.getenv('PYTHON_PORT', '未设置')}")
        log(f"   工作目录: {os.getcwd()}")
        log(f"   TTS 模式: {TTS_MODE}")
        uvicorn.run(app, host=HOST, port=PORT, reload=False)

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