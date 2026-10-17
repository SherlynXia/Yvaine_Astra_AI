import asyncio
import base64
import json
import os
import struct
import uuid
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable

import websockets

print("websockets version:", websockets.__version__)

from dotenv import load_dotenv

env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


def _log(msg: str):
    print(msg, flush=True)


class PhonemeInfo:
    """音素信息"""
    def __init__(self, phoneme: str, start_time: float, end_time: float, confidence: float = 1.0):
        self.phoneme = phoneme
        self.start_time = start_time  # 秒
        self.end_time = end_time      # 秒
        self.confidence = confidence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "phoneme": self.phoneme,
            "startTime": self.start_time,
            "endTime": self.end_time,
            "confidence": self.confidence,
        }


class WordInfo:
    """字级信息"""
    def __init__(self, word: str, start_time: float, end_time: float, confidence: float = 1.0):
        self.word = word
        self.start_time = start_time
        self.end_time = end_time
        self.confidence = confidence

    def to_dict(self) -> Dict[str, Any]:
        return {
            "word": self.word,
            "startTime": self.start_time,
            "endTime": self.end_time,
            "confidence": self.confidence,
        }


class TTSResult:
    """TTS 合成结果"""
    def __init__(self):
        self.audio_base64: str = ""
        self.phonemes: List[PhonemeInfo] = []
        self.words: List[WordInfo] = []
        self.duration_ms: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "audioBase64": self.audio_base64,
            "phonemes": [p.to_dict() for p in self.phonemes],
            "words": [w.to_dict() for w in self.words],
            "durationMs": self.duration_ms,
        }


class TTSBidirectionalService:
    """火山引擎 TTS 2.0 双向流式 WebSocket 服务（支持 phoneme 级时间戳）"""

    _initialized = False
    _app_id: str = ""
    _api_key: str = ""
    _voice_type: str = "zh_female_wanwanxiaohe_moon_bigtts"
    _ws_url: str = "wss://openspeech.bytedance.com/api/v3/tts/bidirection"
    _resource_id: str = ""
    _emotion: str = ""
    _model_type: int = 0  # 复刻音色需要: 1=ICL1.0, 2=DiT标准, 3=DiT还原, 4=ICL2.0, 5=ICL3.0

    @classmethod
    def _detect_resource_id(cls, voice_type: str) -> str:
        """根据音色 ID 自动推断 resource-id"""
        if not voice_type:
            return "volcano_tts"
        # 复刻音色: ICL_ 前缀或 S_ 前缀
        if voice_type.startswith("ICL_") or voice_type.startswith("S_"):
            return "seed-icl-2.0"
        # Seed-TTS 2.0 音色
        if voice_type.startswith("BV"):
            return "seed-tts-2.0"
        # 默认普通 TTS
        return "volcano_tts"

    # 音素到口型映射表（中文拼音 + 英文音素）
    # 基于 Viseme 标准，映射到 Live2D 口型参数
    PHONEME_TO_MOUTH: Dict[str, Dict[str, float]] = {
        # 中文元音 - 大口型
        "a": {"open": 1.0, "form": 0.0},    # 啊 - 嘴巴大张
        "o": {"open": 0.6, "form": 0.5},    # 哦 - 嘴唇圆
        "e": {"open": 0.5, "form": 0.0},    # 呃 - 半开
        "i": {"open": 0.2, "form": -0.8},   # 衣 - 嘴角拉宽
        "u": {"open": 0.2, "form": 1.0},    # 乌 - 嘴唇撮圆
        "v": {"open": 0.2, "form": 0.8},    # 迂 - 撮圆略扁
        "ai": {"open": 0.8, "form": -0.3},  # 爱
        "ei": {"open": 0.5, "form": -0.5},  # 诶
        "ao": {"open": 0.7, "form": 0.3},   # 奥
        "ou": {"open": 0.5, "form": 0.6},   # 欧
        "an": {"open": 0.7, "form": 0.0},   # 安
        "en": {"open": 0.4, "form": 0.0},   # 恩
        "ang": {"open": 0.8, "form": 0.0},  # 昂
        "eng": {"open": 0.4, "form": 0.0},  # 鞥
        "ong": {"open": 0.5, "form": 0.5},  # 轰的韵母
        "er": {"open": 0.4, "form": 0.0},   # 儿

        # 英文元音
        "aa": {"open": 1.0, "form": 0.0},   # father
        "ae": {"open": 0.9, "form": -0.2},  # cat
        "ah": {"open": 0.8, "form": 0.0},   # cut
        "ao_e": {"open": 0.7, "form": 0.4}, # caught
        "eh": {"open": 0.5, "form": -0.3},  # bed
        "er_e": {"open": 0.4, "form": 0.0}, # bird
        "ih": {"open": 0.3, "form": -0.5},  # bit
        "iy": {"open": 0.3, "form": -0.7},  # bee
        "uh": {"open": 0.3, "form": 0.3},   # book
        "uw": {"open": 0.25, "form": 0.9},  # boot

        # 辅音 - 闭嘴或微开
        "b": {"open": 0.0, "form": 0.0},    # 玻
        "p": {"open": 0.0, "form": 0.0},    # 坡
        "m": {"open": 0.0, "form": 0.0},    # 摸
        "f": {"open": 0.1, "form": 0.0},    # 佛
        "d": {"open": 0.1, "form": 0.0},    # 得
        "t": {"open": 0.1, "form": 0.0},    # 特
        "n": {"open": 0.15, "form": 0.0},   # 讷
        "l": {"open": 0.2, "form": 0.0},    # 勒
        "g": {"open": 0.1, "form": 0.0},    # 哥
        "k": {"open": 0.1, "form": 0.0},    # 科
        "h": {"open": 0.2, "form": 0.0},    # 喝
        "j": {"open": 0.15, "form": -0.3},  # 基
        "q": {"open": 0.15, "form": -0.3},  # 期
        "x": {"open": 0.2, "form": -0.3},   # 西
        "zh": {"open": 0.1, "form": 0.0},   # 知
        "ch": {"open": 0.1, "form": 0.0},   # 吃
        "sh": {"open": 0.2, "form": 0.0},   # 诗
        "r": {"open": 0.2, "form": 0.0},    # 日
        "z": {"open": 0.1, "form": 0.0},    # 资
        "c": {"open": 0.1, "form": 0.0},    # 雌
        "s": {"open": 0.15, "form": 0.0},   # 思
        "y": {"open": 0.2, "form": -0.5},   # 医
        "w": {"open": 0.15, "form": 0.6},   # 屋

        # 英文辅音
        "th": {"open": 0.15, "form": 0.0},  # think
        "dh": {"open": 0.15, "form": 0.0},  # this
        "ng": {"open": 0.2, "form": 0.0},   # sing
        "hh": {"open": 0.2, "form": 0.0},   # hat
        "jh": {"open": 0.15, "form": -0.2}, # jump
        "ch_e": {"open": 0.1, "form": 0.0}, # chin
    }

    @classmethod
    async def initialize(cls):
        cls._app_id = os.getenv("VOLCANO_APPID", "")
        cls._api_key = os.getenv("VOLCANO_TOKEN", "")
        cls._voice_type = os.getenv("VOLCANO_VOICE_TYPE", cls._voice_type)
        cls._emotion = os.getenv("VOLCANO_EMOTION", "")
        model_type_str = os.getenv("VOLCANO_MODEL_TYPE", "")
        if model_type_str:
            try:
                cls._model_type = int(model_type_str)
            except ValueError:
                cls._model_type = 0

        # 强制要求用户显式指定 Resource-ID，或根据音色自动推断但拒绝 volcano_tts
        env_resource_id = os.getenv("VOLCANO_RESOURCE_ID", "")
        detected = cls._detect_resource_id(cls._voice_type)

        if env_resource_id:
            cls._resource_id = env_resource_id
        else:
            # 自动推断，但如果是 volcano_tts 则报错
            if detected == "volcano_tts":
                _log("[TTS-BiDi] ❌ 自动推断出的 Resource-ID 为 'volcano_tts'，这不是 V3 双向流合法 ID。")
                _log("[TTS-BiDi] ❌ 请在 .env 中显式设置 VOLCANO_RESOURCE_ID (如 seed-tts-2.0 或 seed-icl-2.0)")
                cls._resource_id = ""  # 置空，后续合成会失败
            else:
                cls._resource_id = detected

        # 如果复刻音色但 resource_id 不是 seed-icl-2.0，给出警告
        if (cls._voice_type.startswith("S_") or cls._voice_type.startswith("ICL_")) and cls._resource_id != "seed-icl-2.0":
            _log(f"[TTS-BiDi] ⚠️ 复刻音色建议使用 seed-icl-2.0，当前为 {cls._resource_id}")

        if not cls._api_key:
            _log("[TTS-BiDi] ⚠️ 未配置火山引擎 Token，双向流式 TTS 将不可用")
        else:
            _log(f"[TTS-BiDi] 🔊 火山引擎 TTS 双向流式已准备就绪")
            _log(f"[TTS-BiDi] 🔊 使用音色: {cls._voice_type}")
            _log(f"[TTS-BiDi] 🔊 使用 Resource-ID: {cls._resource_id}")
            if cls._model_type:
                _log(f"[TTS-BiDi] 🔊 使用 Model-Type: {cls._model_type}")

        cls._initialized = True

    @classmethod
    def get_mouth_shape(cls, phoneme: str) -> Dict[str, float]:
        """获取音素对应的口型参数"""
        phoneme = phoneme.lower().strip()
        # 直接匹配
        if phoneme in cls.PHONEME_TO_MOUTH:
            return cls.PHONEME_TO_MOUTH[phoneme]
        # 尝试去掉声调数字
        phoneme_no_tone = "".join(c for c in phoneme if not c.isdigit())
        if phoneme_no_tone in cls.PHONEME_TO_MOUTH:
            return cls.PHONEME_TO_MOUTH[phoneme_no_tone]
        # 尝试首字母匹配（fallback）
        if phoneme_no_tone:
            first = phoneme_no_tone[0]
            if first in cls.PHONEME_TO_MOUTH:
                return cls.PHONEME_TO_MOUTH[first]
        # 默认微开口型
        return {"open": 0.2, "form": 0.0}

    @classmethod
    async def synthesize(cls, text: str, emotion: str = "") -> TTSResult:
        """
        使用双向流式 WebSocket 合成语音，返回音频 + phoneme 时间轴
        """
        result = TTSResult()

        if not text or not text.strip():
            _log("[TTS-BiDi] ⚠️ 文本为空，跳过合成")
            return result

        if not cls._api_key or not cls._resource_id:
            _log("[TTS-BiDi] ❌ 火山引擎未配置（缺少 Token 或 Resource-ID），无法合成")
            return result

        _log(f"[TTS-BiDi] 🔊 开始双向流式合成: '{text[:50]}...'")

        connect_id = str(uuid.uuid4())
        # 使用新控制台鉴权方式：仅 X-Api-Key + X-Api-Resource-Id
        headers = {
            "Authorization": f"Bearer;{cls._api_key}",
            "X-Api-App-Id": cls._app_id,
            "X-Api-Access-Key": cls._api_key,
            "X-Api-Resource-Id": cls._resource_id,
            "X-Api-Connect-Id": connect_id,
        }

        audio_chunks: List[bytes] = []
        all_phonemes: List[PhonemeInfo] = []
        all_words: List[WordInfo] = []
        has_error = False

        try:
            _log(f"[TTS-BiDi] 🔐 请求 headers: { {k: v[:10]+'...' if len(v)>10 else v for k,v in headers.items()} }")
            async with websockets.connect(
                cls._ws_url,
                additional_headers=headers,
                ping_interval=30,
                ping_timeout=10,
                compression=None,
            ) as ws:
                _log("[TTS-BiDi] ✅ WebSocket 连接已打开")

                # ---- 1. 发送 StartConnection (event=1) ----
                # 连接类请求：payload 建议留空 {}
                start_conn_payload = b"{}"
                _log(f"[TTS-BiDi] 📤 StartConnection payload: {start_conn_payload.decode()}")
                frame = cls._build_frame(
                    start_conn_payload,
                    event_code=1,
                    connection_type=True
                )
                _log(f"[TTS-BiDi] 📤 发送 StartConnection 帧 hex (前64字节): {frame[:64].hex()}")
                await ws.send(frame)
                _log("[TTS-BiDi] 📤 已发送 StartConnection")

                # ---- 2. 等待 ConnectionStarted (event=50) ----
                _log("[TTS-BiDi] ⏳ 等待 Connection 启动...")
                connection_id = ""
                conn_started = False
                while not conn_started:
                    try:
                        msg = await asyncio.wait_for(ws.recv(decode=False), timeout=10.0)
                    except asyncio.TimeoutError:
                        _log("[TTS-BiDi] ❌ 等待 ConnectionStarted 超时")
                        has_error = True
                        break

                    if not isinstance(msg, bytes):
                        continue

                    msg_type, payload, evt_code, sid = cls._parse_frame(msg)
                    _log(f"[TTS-BiDi] 📥 收到帧: type={msg_type}, evt={evt_code}, sid={sid}, payload_len={len(payload)}")
                    if msg_type == 0xF:
                        err_msg = payload.decode('utf-8', errors='replace')
                        _log(f"[TTS-BiDi] ❌ 服务端错误帧: code={evt_code}, msg={err_msg}")
                        _log(f"[TTS-BiDi] ❌ 错误帧 payload hex: {payload.hex()}")
                        has_error = True
                        break

                    # 服务端响应: msg_type=0x9 (Full-server response)
                    # ConnectionStarted 的 event=50，payload 是空 JSON {}
                    # event 信息在二进制帧头里，不在 payload JSON 中
                    if msg_type == 0x9:
                        if evt_code == 50:
                            connection_id = sid
                            conn_started = True
                            _log(f"[TTS-BiDi] ✅ ConnectionStarted 收到, connection_id={connection_id}")
                            break
                        elif evt_code == 51:
                            _log(f"[TTS-BiDi] ❌ ConnectionFailed: {payload.decode('utf-8', errors='replace')}")
                            has_error = True
                            break

                if has_error or not conn_started:
                    _log("[TTS-BiDi] ❌ Connection 启动失败")
                    return result

                # ---- 3. 发送 StartSession (event=100) ----
                session_id = str(uuid.uuid4()).replace("-", "")[:12]   # 12字节
                start_session_body = {
                    "user": {"uid": "yvaine_user"},
                    "req_params": {
                        "speaker": cls._voice_type,
                        "audio_params": {
                            "format": "pcm",
                            "sample_rate": 24000
                        }
                    }
                }
                # 可选：添加 model（根据文档建议）
                if cls._resource_id.startswith("seed-icl"):
                    start_session_body["req_params"]["model"] = "seed-tts-2.0-expressive"
                    start_session_body["req_params"]["model_type"] = cls._model_type or 4
                elif cls._resource_id.startswith("seed-tts"):
                    start_session_body["req_params"]["model"] = "seed-tts-2.0-expressive"

                target_emotion = emotion or cls._emotion
                if target_emotion:
                    start_session_body["req_params"]["additions"] = json.dumps({"emotion": target_emotion})

                # 注意：event 和 namespace 不在 payload 中（已由帧头表达）
                payload_bytes = json.dumps(start_session_body).encode("utf-8")
                _log(f"[TTS-BiDi] 📤 StartSession payload: {payload_bytes.decode()}")
                frame = cls._build_frame(
                    payload_bytes,
                    event_code=100,
                    session_id=session_id,
                    connection_type=False
                )
                _log(f"[TTS-BiDi] 📤 StartSession frame hex (前64): {frame[:64].hex()}")
                await ws.send(frame)
                _log(f"[TTS-BiDi] 📤 已发送 StartSession, session_id={session_id}")

                # ---- 4. 等待 SessionStarted (event=150) ----
                _log("[TTS-BiDi] ⏳ 等待 Session 启动...")
                session_started = False
                while not session_started:
                    try:
                        msg = await asyncio.wait_for(ws.recv(decode=False), timeout=10.0)
                    except asyncio.TimeoutError:
                        _log("[TTS-BiDi] ❌ 等待 SessionStarted 超时")
                        has_error = True
                        break
                    except websockets.exceptions.ConnectionClosedOK as e:
                        _log(f"[TTS-BiDi] 🔌 连接正常关闭 (code={e.code}, reason={e.reason})")
                        has_error = True
                        break
                    except websockets.exceptions.ConnectionClosedError as e:
                        _log(f"[TTS-BiDi] ❌ 连接异常关闭: code={e.code}, reason={e.reason}")
                        has_error = True
                        break

                    if not isinstance(msg, bytes):
                        _log(f"[TTS-BiDi] ⚠️ 收到非二进制消息: {type(msg)}")
                        continue

                    msg_type, payload, evt_code, sid = cls._parse_frame(msg)
                    _log(f"[TTS-BiDi] 📥 收到帧: type={msg_type}, evt={evt_code}, sid={sid}, payload_len={len(payload)}")

                    if msg_type == 0xF:  # 错误帧
                        err_msg = payload.decode('utf-8', errors='replace')
                        _log(f"[TTS-BiDi] ❌ 服务端错误帧: code={evt_code}, msg={err_msg}")
                        has_error = True
                        break

                    if msg_type == 0x9:  # 服务端响应帧
                        if evt_code == 150:  # SessionStarted
                            session_started = True
                            _log(f"[TTS-BiDi] ✅ SessionStarted 收到, session_id={sid}")
                            break
                        elif evt_code == 151:  # SessionFailed
                            err_msg = payload.decode('utf-8', errors='replace')
                            _log(f"[TTS-BiDi] ❌ SessionFailed: {err_msg}")
                            has_error = True
                            break
                        else:
                            _log(f"[TTS-BiDi] 📨 收到其他事件 {evt_code}, payload={payload[:100]}")
                            # 继续等待

                if has_error or not session_started:
                    _log("[TTS-BiDi] ❌ Session 启动失败")
                    return result

                # ---- 5. 发送 TaskRequest (event=200) ----
                task_body = {
                    "user": {"uid": "yvaine_user"},
                    "event": 200,
                    "namespace": "BidirectionalTTS",
                    "req_params": {"text": text},
                }
                frame = cls._build_frame(
                    json.dumps(task_body).encode("utf-8"),
                    event_code=200,
                    session_id=session_id,
                    connection_type=False
                )
                await ws.send(frame)
                _log("[TTS-BiDi] 📤 已发送 TaskRequest")

                # ---- 6. 发送 FinishSession (event=102) ----
                finish_session_body = {
                    "user": {"uid": "yvaine_user"},
                    "event": 102,
                    "namespace": "BidirectionalTTS",
                }
                frame = cls._build_frame(
                    json.dumps(finish_session_body).encode("utf-8"),
                    event_code=102,
                    session_id=session_id,
                    connection_type=False
                )
                await ws.send(frame)
                _log("[TTS-BiDi] 📤 已发送 FinishSession")

                # ---- 7. 接收音频和元数据 ----
                _log("[TTS-BiDi] ⏳ 开始接收音频...")
                recv_count = 0
                session_finished = False

                while not session_finished and not has_error:
                    try:
                        msg = await asyncio.wait_for(ws.recv(decode=False), timeout=30.0)
                    except asyncio.TimeoutError:
                        _log("[TTS-BiDi] ⚠️ 接收音频超时")
                        break
                    except websockets.exceptions.ConnectionClosedOK:
                        _log("[TTS-BiDi] 🔌 连接正常关闭")
                        break
                    except websockets.exceptions.ConnectionClosedError as e:
                        _log(f"[TTS-BiDi] ❌ 连接异常关闭: {e}")
                        has_error = True
                        break

                    if not isinstance(msg, bytes):
                        _log(f"[TTS-BiDi] ⚠️ 收到非二进制消息: {type(msg)}")
                        continue

                    recv_count += 1
                    msg_type, payload, evt_code, sid = cls._parse_frame(msg)

                    if msg_type == 0xF:
                        err_msg = payload.decode('utf-8', errors='replace')
                        _log(f"[TTS-BiDi] ❌ 服务端错误帧: code={evt_code}, msg={err_msg}")
                        has_error = True
                        break

                    if msg_type == 0xB:   # 音频数据
                        if len(payload) > 0:
                            audio_chunks.append(payload)
                        continue

                    if msg_type == 0x9:
                        # SessionFinished 的 event=152，payload 是空 JSON {}
                        # 但 TaskResponse 等数据帧的 payload 包含实际 JSON 数据
                        if evt_code == 152:
                            _log("[TTS-BiDi] ⏹️ 收到 SessionFinished")
                            session_finished = True
                            break
                        elif evt_code == 153:
                            _log("[TTS-BiDi] ⏹️ 收到 SessionCancelled")
                            session_finished = True
                            break

                        # 数据帧：解析 payload JSON（时间戳、进度等）
                        if len(payload) > 0:
                            try:
                                json_payload = cls._extract_json_from_payload(payload)
                                resp = json.loads(json_payload.decode("utf-8"))
                                _log(f"[TTS-BiDi] 📨 JSON 帧: {resp}")

                                # 解析时间戳
                                cls._parse_subtitle_data(resp, all_phonemes, all_words)

                                # 有些实现用结束标志
                                if resp.get("is_end") or resp.get("finish"):
                                    _log("[TTS-BiDi] ⏹️ 收到结束标志")
                                    session_finished = True
                                    break

                                # 检查错误码
                                if resp.get("code", 0) not in (0, 20000000, 3000):
                                    _log(f"[TTS-BiDi] ❌ 合成过程错误: {resp}")
                                    has_error = True
                                    break

                            except Exception as e:
                                _log(f"[TTS-BiDi] ⚠️ 解析 JSON 帧失败: {e}, payload={payload[:100]}")

                    # 防止无限循环
                    if recv_count > 10000:
                        _log("[TTS-BiDi] ⚠️ 接收帧数超过上限，强制结束")
                        break

                # ---- 8. 发送 FinishConnection (event=2) ----
                try:
                    finish_conn_payload = b"{}"
                    frame = cls._build_frame(
                        finish_conn_payload,
                        event_code=2,
                        connection_type=True
                    )
                    await ws.send(frame)
                    _log("[TTS-BiDi] 📤 已发送 FinishConnection")
                except Exception as e:
                    _log(f"[TTS-BiDi] ⚠️ 发送 FinishConnection 失败: {e}")

        except Exception as e:
            _log(f"[TTS-BiDi] ❌ WebSocket 异常: {e}")
            import traceback
            _log(traceback.format_exc())
            has_error = True

        if has_error or not audio_chunks:
            _log("[TTS-BiDi] ⚠️ 合成失败或音频为空")
            return result

        # 合并音频并添加 WAV 头
        audio_bytes = b"".join(audio_chunks)
        wav_header = cls._create_wav_header(24000, 1, 16, len(audio_bytes))
        audio_with_header = wav_header + audio_bytes
        result.audio_base64 = base64.b64encode(audio_with_header).decode("utf-8")

        # 设置 phonemes 和 words
        result.phonemes = all_phonemes
        result.words = all_words

        # 计算总时长
        if all_phonemes:
            result.duration_ms = all_phonemes[-1].end_time * 1000
        elif all_words:
            result.duration_ms = all_words[-1].end_time * 1000
        else:
            result.duration_ms = (len(audio_bytes) / (24000 * 2)) * 1000

        _log(f"[TTS-BiDi] 🎵 合成完成: {len(text)} 字符, "
            f"音频={len(audio_with_header)} 字节, "
            f"phonemes={len(all_phonemes)}, words={len(all_words)}, "
            f"时长={result.duration_ms:.0f}ms")

        return result

    @classmethod
    def _parse_subtitle_data(cls, resp: Dict[str, Any],
                             phonemes: List[PhonemeInfo],
                             words: List[WordInfo]):
        """解析字幕/时间戳数据"""
        # 处理不同的事件类型
        event_type = resp.get("event", "")

        # 有些接口用 data 字段包裹
        data = resp.get("data", resp)

        # 解析 phonemes
        phoneme_list = data.get("phonemes", [])
        if phoneme_list:
            for p in phoneme_list:
                phonemes.append(PhonemeInfo(
                    phoneme=p.get("phoneme", ""),
                    start_time=p.get("startTime", 0.0),
                    end_time=p.get("endTime", 0.0),
                    confidence=p.get("confidence", 1.0),
                ))

        # 解析 words
        word_list = data.get("words", [])
        if word_list:
            for w in word_list:
                words.append(WordInfo(
                    word=w.get("word", ""),
                    start_time=w.get("startTime", 0.0),
                    end_time=w.get("endTime", 0.0),
                    confidence=w.get("confidence", 1.0),
                ))

        # 火山引擎可能用 result 字段
        result = data.get("result", {})
        if result:
            cls._parse_subtitle_data({"data": result}, phonemes, words)

    @classmethod
    def _build_frame(cls, payload: bytes, event_code: int = 0, session_id: str = "", connection_type: bool = False) -> bytes:
        """
        构造 V3 请求帧
        :param payload: JSON 字节
        :param event_code: 事件编号（如 1, 2, 100, 101）
        :param session_id: 会话ID（首次可为空）
        :param connection_type: True=连接类(StartConnection/FinishConnection), False=会话类/数据类
        """
        # 头部：v1(0x1), header_size=1(4字节) -> 0x11
        # Byte1: msg_type=1 (Full-client request) -> (1 << 4) = 0x10
        #        flags=0x04 (with event number) = 0x04
        #        Byte1 = 0x10 | 0x04 = 0x14
        header = bytearray([0x11, 0x14, 0x10, 0x00])
        header += struct.pack(">I", event_code)

        if connection_type:
            # 连接类：event 后面直接是 payload_len（没有 session_id）
            header += struct.pack(">I", len(payload))
        else:
            # 会话类/数据类：event 后面是 session_id_len + session_id + payload_len
            sid_bytes = session_id.encode("utf-8")
            header += struct.pack(">I", len(sid_bytes))
            header += sid_bytes
            header += struct.pack(">I", len(payload))

        header += payload
        return bytes(header)

    @classmethod
    def _parse_frame(cls, data: bytes):
        """解析 V3 协议二进制帧"""
        if len(data) < 4:
            return 0, data, 0, ""

        b0, b1, b2, b3 = data[0], data[1], data[2], data[3]
        version = (b0 >> 4) & 0x0F
        header_size = (b0 & 0x0F) * 4
        msg_type = (b1 >> 4) & 0x0F
        msg_flags = b1 & 0x0F
        ser_method = (b2 >> 4) & 0x0F
        compression = b2 & 0x0F
        p = header_size

        # 错误帧 (msg_type == 0xF)
        if msg_type == 0xF:
            if p + 4 > len(data):
                return 0xF, data[p:], 0, ""
            err_code = struct.unpack(">I", data[p:p+4])[0]
            p += 4
            if p + 4 > len(data):
                return 0xF, data[p:], err_code, ""
            sid_len = struct.unpack(">I", data[p:p+4])[0]
            p += 4
            sid = data[p:p+sid_len].decode("utf-8", errors="replace")
            p += sid_len
            if p + 4 > len(data):
                return 0xF, data[p:], err_code, sid
            pay_len = struct.unpack(">I", data[p:p+4])[0]
            p += 4
            payload = data[p:p+pay_len]
            if compression == 1:
                import gzip
                payload = gzip.decompress(payload)
            return 0xF, payload, err_code, sid

        has_event = bool(msg_flags & 0x04)
        event_code = 0
        session_id = ""

        if has_event:
            if p + 4 > len(data):
                return msg_type, data[p:], event_code, session_id
            event_code = struct.unpack(">I", data[p:p+4])[0]
            p += 4
            if p + 4 > len(data):
                return msg_type, data[p:], event_code, session_id
            sid_len = struct.unpack(">I", data[p:p+4])[0]
            p += 4
            session_id = data[p:p+sid_len].decode("utf-8", errors="replace")
            p += sid_len

        # 音频帧 - 纯音频数据
        if msg_type == 0xB:
            return msg_type, data[p:], event_code, session_id

        # JSON 帧: payload_len + payload
        if p + 4 > len(data):
            return msg_type, data[p:], event_code, session_id
        pay_len = struct.unpack(">I", data[p:p+4])[0]
        p += 4
        if p + pay_len > len(data):
            payload = data[p:]
        else:
            payload = data[p:p+pay_len]
        p += pay_len

        if compression == 1:
            import gzip
            payload = gzip.decompress(payload)

        return msg_type, payload, event_code, session_id

    @classmethod
    def _extract_json_from_payload(cls, payload: bytes) -> bytes:
        """从 payload 中提取纯 JSON 数据，跳过前面的二进制头"""
        if len(payload) == 0:
            return payload
        # 如果直接是 JSON，直接返回
        if payload[0] == ord('{'):
            return payload
        # 否则查找 { 的位置
        json_start = payload.find(b'{')
        if json_start >= 0:
            return payload[json_start:]
        return payload

    @classmethod
    def _create_wav_header(cls, sample_rate: int, channels: int, bits_per_sample: int, data_size: int) -> bytes:
        """生成 WAV 文件头"""
        byte_rate = sample_rate * channels * bits_per_sample // 8
        block_align = channels * bits_per_sample // 8
        header = b'RIFF' + (36 + data_size).to_bytes(4, 'little') + b'WAVE'
        header += b'fmt ' + (16).to_bytes(4, 'little')
        header += (1).to_bytes(2, 'little')
        header += channels.to_bytes(2, 'little')
        header += sample_rate.to_bytes(4, 'little')
        header += byte_rate.to_bytes(4, 'little')
        header += block_align.to_bytes(2, 'little')
        header += bits_per_sample.to_bytes(2, 'little')
        header += b'data' + data_size.to_bytes(4, 'little')
        return header

    @classmethod
    async def close(cls):
        pass