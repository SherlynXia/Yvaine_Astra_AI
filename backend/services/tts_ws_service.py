import asyncio
import base64
import json
import os
import uuid
from pathlib import Path

import websockets
from dotenv import load_dotenv

# 确保从 backend 目录加载 .env
env_path = Path(__file__).parent.parent / ".env"
load_dotenv(dotenv_path=env_path)


def _log(msg: str):
    print(msg, flush=True)


class TTSWebSocketService:
    """语音合成服务 - 使用火山引擎 WebSocket V3 单向流式接口 (JSON 协议)"""

    _initialized = False
    _app_id: str = ""
    _api_key: str = ""
    _voice_type: str = "zh_female_wanwanxiaohe_moon_bigtts"
    _ws_url: str = "wss://openspeech.bytedance.com/api/v3/tts/unidirectional/stream"
    _emotion: str = ""
    _resource_id: str = ""
    _model_type: int = 0  # 复刻音色需要: 1=ICL1.0, 2=DiT标准, 3=DiT还原, 4=ICL2.0, 5=ICL3.0

    @classmethod
    def _detect_resource_id(cls, voice_type: str) -> str:
        """根据音色 ID 自动推断 resource-id

        注意: S_ 前缀的音色属于声音复刻，resource-id 统一用 seed-icl-2.0
        （ICL 1.0/2.0/3.0 在 V3 接口下都走 seed-icl-2.0，通过 model_type 区分版本）
        """
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

    @classmethod
    async def initialize(cls):
        """初始化 TTS 服务"""
        cls._app_id = os.getenv("VOLCANO_APPID", "")
        cls._api_key = os.getenv("VOLCANO_TOKEN", "")
        cls._voice_type = os.getenv("VOLCANO_VOICE_TYPE", cls._voice_type)
        cls._emotion = os.getenv("VOLCANO_EMOTION", "")
        cls._resource_id = os.getenv("VOLCANO_RESOURCE_ID", "")
        model_type_str = os.getenv("VOLCANO_MODEL_TYPE", "")
        if model_type_str:
            try:
                cls._model_type = int(model_type_str)
            except ValueError:
                cls._model_type = 0

        # 如果没有手动配置 resource-id，自动推断
        if not cls._resource_id:
            cls._resource_id = cls._detect_resource_id(cls._voice_type)

        # 调试：打印配置信息（隐藏敏感信息）
        _log(f"[TTS-WS] 🔧 配置信息:")
        _log(f"[TTS-WS] 🔧   APPID: {cls._app_id}")
        _log(f"[TTS-WS] 🔧   TOKEN: {cls._api_key[:10]}..." if cls._api_key else "[TTS-WS] 🔧   TOKEN: 未设置")
        _log(f"[TTS-WS] 🔧   音色: {cls._voice_type}")
        _log(f"[TTS-WS] 🔧   Resource-ID: {cls._resource_id}")
        if cls._model_type:
            _log(f"[TTS-WS] 🔧   Model-Type: {cls._model_type}")

        if not cls._api_key:
            _log("[TTS-WS] ⚠️ 未配置火山引擎 Token，TTS 将不可用")
            _log("[TTS-WS] ⚠️ 请在 .env 中设置 VOLCANO_TOKEN")
        else:
            _log(f"[TTS-WS] 🔊 火山引擎 TTS WebSocket V3 已准备就绪")
            _log(f"[TTS-WS] 🔊 使用音色: {cls._voice_type}")
            if cls._emotion:
                _log(f"[TTS-WS] 🔊 使用情感: {cls._emotion}")

        cls._initialized = True

    @classmethod
    async def synthesize(cls, text: str, emotion: str = "") -> str:
        """
        将文本转为语音 (使用 WebSocket V3 单向流式接口)
        返回: base64 编码的音频数据，失败时返回空字符串
        """
        if not text or not text.strip():
            _log("[TTS-WS] ⚠️ 文本为空，跳过合成")
            return ""

        if not cls._api_key:
            _log("[TTS-WS] ❌ 火山引擎未配置，无法合成")
            return ""

        _log(f"[TTS-WS] 🔊 开始合成: '{text[:50]}...'")
        _log(f"[TTS-WS] 🔊 使用音色: {cls._voice_type}")

        return await cls._synthesize_async(text, emotion)

    @staticmethod
    def _create_wav_header(sample_rate: int, channels: int, bits_per_sample: int, data_size: int) -> bytes:
        """生成 WAV 文件头（44 字节）"""
        byte_rate = sample_rate * channels * bits_per_sample // 8
        block_align = channels * bits_per_sample // 8
        header = b'RIFF' + (36 + data_size).to_bytes(4, 'little') + b'WAVE'
        header += b'fmt ' + (16).to_bytes(4, 'little')
        header += (1).to_bytes(2, 'little')  # PCM format
        header += channels.to_bytes(2, 'little')
        header += sample_rate.to_bytes(4, 'little')
        header += byte_rate.to_bytes(4, 'little')
        header += block_align.to_bytes(2, 'little')
        header += bits_per_sample.to_bytes(2, 'little')
        header += b'data' + data_size.to_bytes(4, 'little')
        return header

    @classmethod
    def _build_frame(cls, payload: bytes, message_type: int = 1) -> bytes:
        """构建 V3 协议二进制帧

        正确的 SendText 帧格式 (4 字节 header + 4 字节 payload 长度 + payload):
        Byte 0: 0x11 (version=1, header_size=1 表示4字节)
        Byte 1: 0x10 (full-client request, no event)
        Byte 2: 0x10 (JSON serialization, no compression)
        Byte 3: 0x00 (reserved)
        Byte 4-7: payload 长度 (大端 uint32)
        Byte 8+: UTF-8 JSON payload
        """
        import struct
        header = bytes([
            0x11,   # 0001 0001  v1, 4-byte header
            0x10,   # 0001 0000  full-client request, no event
            0x10,   # 0001 0000  JSON, no compression
            0x00,   # reserved
        ])
        length = struct.pack(">I", len(payload))  # 大端 uint32
        return header + length + payload

    @classmethod
    def _parse_frame(cls, data: bytes) -> tuple[int, bytes, int, str]:
        """解析收到的 V3 协议二进制帧，返回 (msg_type, payload, event_code, session_id)

        服务端返回的帧格式 (根据官方文档):
        Byte 0: version(4) + header_size(4)  → 0x11 (v1, 4字节头)
        Byte 1: msg_type(4) + flags(4)        → 0x90=JSON元数据, 0xB0=音频帧
        Byte 2: serialization(4) + compression(4)
        Byte 3: reserved
        然后:
          - event_code (4字节, uint32)  如果 flags & 0x04
          - session_id_len (4字节, uint32)
          - session_id (字符串)
          - payload_len (4字节, uint32)
          - payload
        """
        import struct
        if len(data) < 4:
            return (0, data, 0, "")

        b0, b1, b2, b3 = data[0], data[1], data[2], data[3]
        version = (b0 >> 4) & 0x0F
        header_size = (b0 & 0x0F) * 4
        msg_type = (b1 >> 4) & 0x0F
        msg_flags = b1 & 0x0F
        ser_method = (b2 >> 4) & 0x0F
        compression = b2 & 0x0F

        p = header_size  # payload 起点

        # 错误帧
        if b1 == 0xF0:
            if p + 4 > len(data):
                return (0xF, data[p:], 0, "")
            err_code = struct.unpack(">I", data[p:p+4])[0]
            p += 4
            if p + 4 > len(data):
                return (0xF, data[p:], err_code, "")
            sid_len = struct.unpack(">I", data[p:p+4])[0]
            p += 4
            sid = data[p:p+sid_len].decode("utf-8", errors="replace")
            p += sid_len
            if p + 4 > len(data):
                return (0xF, data[p:], err_code, sid)
            pay_len = struct.unpack(">I", data[p:p+4])[0]
            p += 4
            payload = data[p:p+pay_len]
            if compression == 1:
                import gzip
                payload = gzip.decompress(payload)
            return (0xF, payload, err_code, sid)

        has_event = bool(msg_flags & 0x04)
        event_code = 0
        session_id = ""

        if has_event:
            if p + 4 > len(data):
                return (msg_type, data[p:], event_code, session_id)
            event_code = struct.unpack(">I", data[p:p+4])[0]
            p += 4
            if p + 4 > len(data):
                return (msg_type, data[p:], event_code, session_id)
            sid_len = struct.unpack(">I", data[p:p+4])[0]
            p += 4
            session_id = data[p:p+sid_len].decode("utf-8", errors="replace")
            p += sid_len

        # ✅ 音频帧 (type=0xB=11): payload 是纯音频数据，没有 payload_len 前缀
        if msg_type == 0xB:
            return (msg_type, data[p:], event_code, session_id)

        # JSON/错误帧: payload_len + payload
        if p + 4 > len(data):
            return (msg_type, data[p:], event_code, session_id)
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

        return (msg_type, payload, event_code, session_id)

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
    async def _synthesize_async(cls, text: str, emotion: str = "") -> str:
        """异步版本的合成（使用 websockets 库）"""
        connect_id = str(uuid.uuid4())

        # WebSocket 请求头 (V3 鉴权)
        headers = {
            "Authorization": f"Bearer;{cls._api_key}",
            "X-Api-App-Id": cls._app_id,
            "X-Api-Access-Key": cls._api_key,
            "X-Api-Resource-Id": cls._resource_id,
            "X-Api-Connect-Id": connect_id,
        }

        _log(f"[TTS-WS] 📤 请求头: {headers}")

        # 构建请求体
        request_body = {
            "user": {"uid": "yvaine_user"},
            "req_params": {
                "text": text,
                "speaker": cls._voice_type,
                "audio_params": {
                    "format": "pcm",
                    "sample_rate": 24000,
                },
            },
        }

        # 复刻音色 (S_ 或 ICL_ 前缀) 需要 model_type
        if cls._voice_type.startswith("S_") or cls._voice_type.startswith("ICL_"):
            # 优先使用用户配置的 model_type，否则默认用 4 (ICL 2.0)
            request_body["req_params"]["model_type"] = cls._model_type if cls._model_type else 4

        # 如果配置了情感参数
        target_emotion = emotion or cls._emotion
        if target_emotion:
            request_body["req_params"]["additions"] = json.dumps({
                "emotion": target_emotion,
            })

        audio_chunks = []
        has_error = False

        try:
            async with websockets.connect(
                cls._ws_url,
                additional_headers=headers,
                ping_interval=30,
                ping_timeout=10,
                compression=None,
            ) as ws:
                _log("[TTS-WS] ✅ WebSocket 连接已打开，发送请求...")
                request_json = json.dumps(request_body)
                _log(f"[TTS-WS] 📤 请求体: {request_json}")

                # 构建二进制帧并发送
                frame = cls._build_frame(request_json.encode('utf-8'), message_type=1)
                _log(f"[TTS-WS] 📤 发送帧: {len(frame)} 字节, hex={frame[:20].hex()}")
                await ws.send(frame)

                # 接收响应（使用 recv(decode=False) 禁用自动 UTF-8 解码）
                while True:
                    try:
                        message = await ws.recv(decode=False)
                    except websockets.exceptions.ConnectionClosedOK:
                        _log("[TTS-WS] 🔌 WebSocket 连接已正常关闭")
                        break
                    except websockets.exceptions.ConnectionClosedError as e:
                        _log(f"[TTS-WS] ❌ WebSocket 连接异常关闭: {e}")
                        has_error = True
                        break

                    if not isinstance(message, bytes):
                        _log(f"[TTS-WS] 📥 收到文本消息: {message}")
                        continue

                    # 解析二进制帧
                    msg_type, payload, event_code, session_id = cls._parse_frame(message)
                    _log(f"[TTS-WS] 📥 收到帧: type={msg_type}, event={event_code}, sid={session_id}, payload_len={len(payload)}")

                    # 错误帧
                    if msg_type == 0xF:
                        _log(f"[TTS-WS] ❌ 服务端错误帧: code={event_code}")
                        has_error = True
                        break

                    # 音频数据帧 (type=0xB=11) — 直接处理，不尝试 JSON 解析
                    if msg_type == 0xB and len(payload) > 0:
                        _log(f"[TTS-WS] 📥 收到音频数据: {len(payload)} 字节")
                        audio_chunks.append(payload)
                        continue

                    # JSON 元数据帧 (type=0x9)
                    if msg_type == 0x9 and len(payload) > 0:
                        try:
                            resp = json.loads(payload.decode('utf-8'))
                            _log(f"[TTS-WS] 📥 JSON 内容: {resp}")

                            # 检查错误
                            if "error" in resp:
                                _log(f"[TTS-WS] ❌ 服务端错误: {resp}")
                                has_error = True
                                break
                            if resp.get("code") not in (0, 20000000, 3000, None):
                                _log(f"[TTS-WS] ❌ TTS 错误: {resp}")
                                has_error = True
                                break

                            # 检查结束标志（多种可能的字段）
                            if resp.get("is_end") or resp.get("end") or resp.get("finish"):
                                _log("[TTS-WS] ⏹️ 收到结束标志")
                                break

                            # 复刻音色可能用空 JSON {} 作为结束信号（最后一个 type=9 帧）
                            if resp == {}:
                                _log("[TTS-WS] ⏹️ 收到空 JSON 结束帧")
                                break

                        except (json.JSONDecodeError, UnicodeDecodeError):
                            _log(f"[TTS-WS] 📥 JSON/UTF-8 解析失败, 跳过此帧, hex={payload[:50].hex()}")

        except Exception as e:
            _log(f"[TTS-WS] ❌ WebSocket 异常: {e}")
            has_error = True

        if has_error or not audio_chunks:
            _log("[TTS-WS] ⚠️ 合成返回空音频数据或出错")
            return ""

        _log(f"[TTS-WS] 📊 音频块数量: {len(audio_chunks)}, 总音频长度: {sum(len(c) for c in audio_chunks)} 字节")

        # 合并所有音频块
        audio_bytes = b"".join(audio_chunks)
        if len(audio_bytes) == 0:
            _log("[TTS-WS] ⚠️ 音频数据为空")
            return ""

        # 添加 WAV 头（PCM, 24000Hz, 单声道, 16bit）
        wav_header = cls._create_wav_header(24000, 1, 16, len(audio_bytes))
        audio_with_header = wav_header + audio_bytes

        audio_base64 = base64.b64encode(audio_with_header).decode("utf-8")

        _log(f"[TTS-WS] 🎵 合成完成: {len(text)} 字符, PCM={len(audio_bytes)} 字节, WAV={len(audio_with_header)} 字节")
        return audio_base64

    @classmethod
    async def close(cls):
        """关闭服务"""
        pass