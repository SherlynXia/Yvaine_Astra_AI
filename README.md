# Yvaine Astra AI（渊鸢）

一个基于 **Tauri + Vue + TypeScript** 的 Live2D AI 虚拟伴侣桌面应用，集成 **Python FastAPI** 后端，支持多轮对话、语音合成 (TTS) 与 Live2D 口型同步。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 桌面框架 | Tauri 2.x (Rust) |
| 前端框架 | Vue 3 + TypeScript + Vite |
| 图形渲染 | PixiJS 6 + pixi-live2d-display (Cubism 4) |
| 后端框架 | Python FastAPI + Uvicorn |
| LLM 对话 | DeepSeek API / 本地 Ollama |
| TTS 语音 | 火山引擎豆包语音合成 2.0 (HTTP V3 / WebSocket / 双向流式) |

---

## 项目结构

```
Yvaine_Astra_AI/
├── backend/                        # Python 后端
│   ├── main.py                     # FastAPI 入口，WebSocket 服务
│   ├── feedback_manager.py         # 反馈管理器（写入 data/feedback.jsonl）
│   ├── requirements.txt
│   ├── .env / .env.example
│   ├── personality/
│   │   └── system_prompt.txt       # 人格设定（渊鸢）
│   ├── data/                       # 📊 运行时数据（不提交 Git）
│   │   ├── .gitkeep
│   │   ├── feedback.jsonl          # 用户评分
│   │   ├── conversations/          # 精选对话（预留）
│   │   └── memories/               # 长期记忆（预留）
│   ├── training/                   # 🧪 训练流水线（占位）
│   │   └── README.md
│   └── services/
│       ├── __init__.py
│       ├── chat_service.py         # 对话服务（注入 Provider）
│       ├── llm/                    # 🔥 LLM 抽象层
│       │   ├── __init__.py
│       │   ├── base.py             # LLMProvider 接口
│       │   ├── ollama_provider.py
│       │   └── deepseek_provider.py
│       ├── tts_service.py
│       ├── tts_ws_service.py
│       └── tts_bidi_service.py
├── src/                            # Vue 前端
│   ├── main.ts                     # 应用入口
│   ├── App.vue                     # 根组件
│   ├── assets/
│   │   └── vue.svg
│   ├── components/
│   │   ├── Live2DCanvas.vue        # Live2D 主画布组件
│   │   ├── ChatPanel.vue           # 聊天面板组件
│   │   ├── ExpressionPanel.vue     # 表情控制面板组件
│   │   └── MotionPanel.vue         # 动作控制面板组件
│   ├── composables/
│   │   ├── useChat.ts              # 聊天逻辑组合式函数
│   │   ├── useLive2D.ts            # Live2D 模型控制组合式函数
│   │   └── useWebSocket.ts         # WebSocket 连接组合式函数
│   └── constants/
│       └── live2d.ts               # 表情/动作常量配置
├── src-tauri/                      # Tauri Rust 后端
├── index.html                      # HTML 入口
├── package.json                    # 前端依赖
├── vite.config.ts
└── tsconfig.json
```

---

## 前端模块说明

### 1. 入口文件

#### `main.ts` — 应用入口
创建 Vue 应用实例并挂载到 `#app`。

#### `App.vue` — 根组件
引入 `Live2DCanvas` 组件，设置全局样式（全屏无边距）。

---

### 2. 组件 (Components)

#### `Live2DCanvas.vue` — Live2D 主画布
核心容器组件，整合 Live2D 模型渲染、聊天、表情控制、动作控制。职责：
- 初始化 Live2D 模型 (`useLive2D`)
- 建立聊天功能 (`useChat`)，连接到 Python 后端
- 渲染 `ExpressionPanel`、`MotionPanel`、`ChatPanel` 子组件
- 管理窗口 resize 事件

#### `ChatPanel.vue` — 聊天面板
聊天 UI 组件，提供：
- 展开/收起切换
- 连接状态指示
- 消息列表（用户/AI 气泡）
- 文本输入与发送
- TTS 测试按钮

| Props | 类型 | 说明 |
|-------|------|------|
| `history` | `ChatHistoryItem[]` | 对话历史记录 |
| `isConnected` | `boolean` | WebSocket 连接状态 |
| `isConnecting` | `boolean` | 是否正在连接 |
| `isTyping` | `boolean` | AI 是否正在生成回复 |

| Emits | 参数 | 说明 |
|-------|------|------|
| `send` | `text: string` | 发送用户消息 |
| `testTTS` | - | 触发 TTS 测试 |
| `feedback` | `messageId: string, rating: 'good' \| 'bad'` | 用户评分 |

#### `ExpressionPanel.vue` — 表情控制面板
Live2D 表情参数切换面板，分类控制：

| 分类 | Props | 说明 |
|------|-------|------|
| 面部 | `currentFacial` | 脸红/脸黑/流泪/生气/惊讶/疑惑 |
| 眼睛 | `currentEyes` | 星星眼/爱心眼/金钱眼/白眼 |
| 嘴巴 | `currentMouth` | 歪嘴右/歪嘴左/舌头 |
| 发型 | `currentHair` | 马尾 |
| 饰品 | `currentAccessories` | 猫耳/翅膀/王冠/手柄/直播套装（多选） |

| Emits | 参数 | 说明 |
|-------|------|------|
| `set` | `category: string, id: string` | 设置某个分类的表情 |
| `clear` | - | 清除全部表情 |

#### `MotionPanel.vue` — 动作控制面板
Live2D 动作触发面板，提供：
- 待机动作 (`Idle`)
- 挥手动作 (`Tap`, index=0)
- 媚眼动作 (`Tap`, index=1)

| Emits | 参数 | 说明 |
|-------|------|------|
| `play` | `group: string, index?: number` | 播放指定动作组 |

---

### 3. 组合式函数 (Composables)

#### `useWebSocket.ts` — WebSocket 连接管理
管理与 Python 后端的 WebSocket 连接。

**导出类型：**
```typescript
PhonemeInfo { phoneme, startTime, endTime, confidence }
WordInfo { word, startTime, endTime, confidence }
ChatMessage { type, text?, emotion?, audioBase64?, phonemes?, words?, durationMs?, sessionId? }
```

**导出函数：** `useWebSocket()`

| 返回值 | 类型 | 说明 |
|--------|------|------|
| `ws` | `Ref<WebSocket \| null>` | WebSocket 实例 |
| `isConnected` | `Ref<boolean>` | 是否已连接 |
| `isConnecting` | `Ref<boolean>` | 是否正在连接 |
| `lastMessage` | `Ref<ChatMessage \| null>` | 最近一条消息 |
| `messageQueue` | `Ref<ChatMessage[]>` | 消息队列（批量处理） |
| `error` | `Ref<string \| null>` | 错误信息 |
| `wsUrl` | `Ref<string>` | WebSocket URL |
| `connect()` | `() => Promise<void>` | 建立连接 |
| `disconnect()` | `() => void` | 断开连接 |
| `sendMessage(text)` | `(text: string) => boolean` | 发送文本消息 |

#### `useChat.ts` — 聊天逻辑
管理对话状态、音频播放、音素口型同步。

**导出函数：** `useChat(onYvaineSpeak?, onAudioPlay?, onPhonemes?)`

| 参数 | 类型 | 说明 |
|------|------|------|
| `onYvaineSpeak` | `(text, emotion?) => void` | AI 回复文本到达时的回调 |
| `onAudioPlay` | `(duration) => void` | 音频播放时的回调（回退口型） |
| `onPhonemes` | `(phonemes, emotion?, audioStartTime?) => void` | phoneme 时间轴数据到达回调 |

| 返回值 | 类型 | 说明 |
|--------|------|------|
| `history` | `Ref<ChatHistoryItem[]>` | 对话历史 |
| `isConnected` | `Ref<boolean>` | WebSocket 连接状态 |
| `isConnecting` | `Ref<boolean>` | 是否正在连接 |
| `isTyping` | `Ref<boolean>` | AI 是否正在生成 |
| `isPlaying` | `Ref<boolean>` | 音频是否正在播放 |
| `error` | `Ref<string \| null>` | 错误信息 |
| `send(text)` | `(text: string) => Promise<void>` | 发送消息 |
| `clearHistory()` | `() => void` | 清空对话历史 |
| `connect()` | `() => Promise<void>` | 连接后端 |
| `disconnect()` | `() => void` | 断开连接 |
| `stopAudio()` | `() => void` | 停止音频播放 |
| `sendFeedback(messageId, rating)` | `(id: string, r: 'good' \| 'bad') => void` | 提交评分 |

**内部函数：** `playAudio(base64Data: string)` — 解码并播放 base64 音频

#### `useLive2D.ts` — Live2D 模型控制
管理 Live2D 模型的加载、渲染、表情、动作、口型动画。

**导出函数：** `useLive2D()`

| 返回值 | 类型 | 说明 |
|--------|------|------|
| `app` | `Ref<PIXI.Application \| null>` | PixiJS 应用实例 |
| `model` | `Ref<Live2DModel \| null>` | Live2D 模型实例 |
| `currentFacial` | `Ref<string>` | 当前面部表情 ID |
| `currentEyes` | `Ref<string>` | 当前眼睛表情 ID |
| `currentMouth` | `Ref<string>` | 当前嘴部表情 ID |
| `currentHair` | `Ref<string>` | 当前发型表情 ID |
| `currentAccessories` | `Ref<Set<string>>` | 当前饰品集合 |
| `init(container)` | `(container: HTMLElement) => Promise<{app, canvas}>` | 初始化 PixiJS + 加载 Live2D 模型 |
| `resize(container)` | `(container: HTMLElement) => void` | 响应窗口大小变化 |
| `playMotion(group, index?)` | `(group: string, index?: number) => void` | 播放指定动作 |
| `setExpression(category, id)` | `(category: string, id: string) => void` | 设置指定分类的表情 |
| `clearExpression()` | `() => void` | 清除所有表情 |
| `speak(text?, emotion?, durationMs?)` | `(text?, emotion?, durationMs?) => void` | AI 说话（简易口型模式） |
| `speakWithPhonemes(phonemes, emotion?, audioStartTime?)` | `(phonemes: PhonemeInfo[], emotion?, audioStartTime?) => void` | AI 说话（音素精确口型同步） |
| `applyEmotion(emotion)` | `(emotion: string) => void` | 根据情绪标签应用表情和动作 |
| `startSpeaking(text?, durationMs?, speed?)` | `(text?, durationMs?, speed?) => void` | 开始说话动画 |
| `stopSpeaking()` | `() => void` | 停止说话动画 |
| `destroy()` | `() => void` | 销毁模型和应用实例 |

**内部函数：**
- `setParam(id, value)` — 直接设置 Live2D 模型参数
- `getMouthShape(phoneme)` — 音素到口型参数映射
- `setPhonemeTimeline(phonemes)` — 设置音素时间轴
- `startSpeakingWithPhonemes(phonemes, audioStartTime?)` — 基于音素时间轴的精确口型同步
- `startSpeakingLegacy(text?, durationMs?, speed?)` — 旧版正弦波口型（无 phoneme 时的回退方案）

**情绪映射 (`EMOTION_MAP`)：**

| 情绪 | 面部 | 眼睛 | 动作 |
|------|------|------|------|
| 开心 | 脸红 | 爱心眼 | Tap (挥手) |
| 害羞 | 脸红 | 爱心眼 | - |
| 生气 | 生气 | 白眼 | - |
| 难过 | 流泪 | 正常眼 | - |
| 惊讶 | 惊讶 | 星星眼 | Tap |
| 疑惑 | 疑惑 | 正常眼 | - |
| 调皮 | 脸黑 | 星星眼 | Tap |
| 困倦 | - | 白眼 | - |

---

### 4. 常量 (Constants)

#### `live2d.ts` — 表情与动作常量

**导出的表情列表：**
- `EXPRESSIONS_FACIAL` — 面部：正常、脸红、脸黑、流泪、生气、惊讶、疑惑
- `EXPRESSIONS_EYES` — 眼睛：正常眼、星星眼、爱心眼、金钱眼、白眼
- `EXPRESSIONS_MOUTH` — 嘴巴：正常嘴、歪嘴右、歪嘴左、舌头
- `EXPRESSIONS_HAIR` — 发型：默认、马尾
- `EXPRESSIONS_ACCESSORIES` — 饰品（可多选）：猫耳、翅膀、王冠、手柄、直播套装

**导出的动作列表：**
- `MOTIONS` — 待机、挥手、媚眼

---

## 后端模块说明

### 1. `main.py` — FastAPI 服务入口

**全局配置：**
- 从 `.env` 加载火山引擎 TTS 配置
- TTS 模式可选：`http` / `websocket` / `bidi`（双向流式）
- `ChatService`、`ConversationStore` 等对话相关逻辑统一从 `services/chat_service.py` 导入

**`TTSService` 方法（main.py 内唯一自定义的类）：**

| 方法 | 签名 | 说明 |
|------|------|------|
| `initialize()` | `async` static | 初始化 TTS 服务 |
| `synthesize(text, emotion)` | `async static` → `str` | 文本转语音，返回 base64 音频（兼容旧接口） |
| `synthesize_with_phonemes(text, emotion)` | `async static` → `TTSResult` | 文本转语音，返回音频 + 音素时间轴（新接口） |
| `_http_synthesize(text, emotion)` | `async static` → `str` | HTTP V3 备用合成方案 |

**FastAPI 路由：**

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 服务状态检查 |
| `/health` | GET | 健康检查 |
| `/test-tts` | GET | TTS 合成测试 |
| `/test-tts-emotion` | GET | 带情感的 TTS 合成测试（happy/sad/angry/surprised） |
| `/feedback/stats` | GET | 反馈统计（total/good/bad） |
| `/ws/chat` | WebSocket | 聊天 WebSocket 连接（核心通信通道） |

**WebSocket 消息格式：**
- 客户端 → 服务端（聊天）：`{"text": "用户消息"}`
- 客户端 → 服务端（评分）：`{"type": "feedback", "messageId": "xxx", "rating": "good"}`
- 服务端 → 客户端（文本）：`{"type": "message", "text": "...", "emotion": "...", "sessionId": "...", "messageId": "xxx"}`
- 服务端 → 客户端（评分确认）：`{"type": "feedback_ack", "status": "ok", "messageId": "xxx"}`
- 服务端 → 客户端（音频）：`{"type": "audio", "audioBase64": "..."}`
- 服务端 → 客户端（音素）：`{"type": "phonemes", "phonemes": [...], "words": [...], "durationMs": 1234}`

---

### 2. Services

#### `chat_service.py` — 对话服务（Provider 模式）

包含 `ConversationStore` 和 `ChatService`。`ChatService` 不再自己读 `.env`，而是由 `main.py` 注入一个 `LLMProvider`。

**`ChatService` 方法：**

| 方法 | 签名 | 说明 |
|------|------|------|
| `configure(provider, system_prompt)` | `classmethod` | 由 `main.py` 调用，注入 Provider 和人格 |
| `chat(user_message, session_id)` | `async classmethod` → `(str, str, str)` | 多轮对话 |
| `_parse_emotion(text)` | `static` → `(str, str)` | 解析 `[情绪:xxx]` 标签 |
| `clear_session(session_id)` | `classmethod` | 清理指定会话 |

**`ChatService` 类：**

| 方法 | 签名 | 说明 |
|------|------|------|
| `initialize()` | `async` classmethod | 初始化对话服务，加载人格设定、检测 DeepSeek/Ollama |
| `chat(user_message, session_id)` | `async` classmethod → `(str, str, str)` | 多轮对话，返回 (回复文本, 情绪标签, session_id) |
| `_chat_with_ollama(messages)` | `async` classmethod → `(str, str)` | 使用 Ollama 模型（先尝试 /api/chat，失败回退 /api/generate） |
| `_chat_with_deepseek(messages)` | `async` classmethod → `(str, str)` | 使用 DeepSeek API（原生多轮 messages） |
| `_parse_emotion(text)` | `static` → `(str, str)` | 从回复文本中解析 [情绪:xxx] 标签 |

#### `tts_service.py` — TTS HTTP 服务

**`TTSService` 类：**

| 方法 | 签名 | 说明 |
|------|------|------|
| `initialize()` | `async` classmethod | 初始化 TTS（加载火山引擎配置） |
| `synthesize(text, emotion)` | `async` classmethod → `str` | HTTP V3 单向流式合成，返回 base64 MP3 |

#### `tts_ws_service.py` — TTS WebSocket 单向流式服务

**`TTSWebSocketService` 类：**

| 方法 | 签名 | 说明 |
|------|------|------|
| `initialize()` | `async` classmethod | 初始化 TTS WebSocket 配置 |
| `synthesize(text, emotion)` | `async` classmethod → `str` | WebSocket V3 单向流式合成，返回 base64 音频 |
| `_detect_resource_id(voice_type)` | `classmethod` → `str` | 根据音色 ID 推断 resource-id |
| `_create_wav_header(sample_rate, channels, bits_per_sample, data_size)` | `static` → `bytes` | 生成 44 字节 WAV 文件头 |
| `_build_frame(payload, message_type)` | `classmethod` → `bytes` | 构建 V3 协议二进制帧 |
| `_parse_frame(data)` | `classmethod` → `tuple` | 解析 V3 协议二进制帧 |
| `_extract_json_from_payload(payload)` | `classmethod` → `bytes` | 从 payload 提取纯 JSON |
| `_synthesize_async(text, emotion)` | `async` classmethod → `str` | 异步合成核心逻辑 |

#### `tts_bidi_service.py` — TTS 双向流式服务

**数据类：**

| 类名 | 字段 | 说明 |
|------|------|------|
| `PhonemeInfo` | `phoneme, start_time, end_time, confidence` | 单个音素信息 |
| `WordInfo` | `word, start_time, end_time, confidence` | 单个字级信息 |
| `TTSResult` | `audio_base64, phonemes, words, duration_ms` | TTS 合成完整结果 |

**`TTSBidirectionalService` 类：**

| 方法 | 签名 | 说明 |
|------|------|------|
| `initialize()` | `async` classmethod | 初始化双向流式 TTS 配置 |
| `synthesize(text, emotion)` | `async` classmethod → `TTSResult` | 双向流式合成，返回音频 + phoneme 时间轴 |
| `get_mouth_shape(phoneme)` | `classmethod` → `dict` | 根据音素获取口型参数 {open, form} |
| `_detect_resource_id(voice_type)` | `classmethod` → `str` | 推断 resource-id |
| `_parse_subtitle_data(resp, phonemes, words)` | `classmethod` | 解析字幕/时间戳数据 |
| `_build_frame(payload, event_code, session_id, connection_type)` | `classmethod` → `bytes` | 构建 V3 双向流协议帧 |
| `_parse_frame(data)` | `classmethod` → `tuple` | 解析 V3 双向流协议帧 |
| `_extract_json_from_payload(payload)` | `classmethod` → `bytes` | 从 payload 提取纯 JSON |
| `_create_wav_header(sample_rate, channels, bits_per_sample, data_size)` | `classmethod` → `bytes` | 生成 WAV 文件头 |
| `close()` | `async` classmethod | 关闭服务 |

**`PHONEME_TO_MOUTH` 字典：** 音素到口型参数映射表，支持中文拼音（a/o/e/i/u/ai/ei/ao/ou/an/en/ang/eng/ong/er 等）和英文音素（aa/ae/ah/eh/ih/iy/uh/uw 等），以及辅音映射。

#### `llm/base.py` — LLMProvider 接口

| 方法 | 签名 | 说明 |
|------|------|------|
| `chat(messages)` | `async` → `str` | 输入消息列表，返回纯文本回复 |

#### `llm/ollama_provider.py` — 本地 Ollama

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__(model, host)` | 构造 | 默认 `qwen2.5:7b` |
| `chat(messages)` | `async` → `str` | 优先 `/api/chat`，失败回退 `/api/generate` |

#### `llm/deepseek_provider.py` — 云端 DeepSeek

| 方法 | 签名 | 说明 |
|------|------|------|
| `__init__(api_key, model)` | 构造 | 默认 `deepseek-chat` |
| `chat(messages)` | `async` → `str` | 调用 `/v1/chat/completions` |

---

### 3. Personality（人格设定）

#### `personality/system_prompt.txt`
"渊鸢"（Yvaine Astra）的完整人格设定，定义其：
- **核心**：观测者型 AI 旅伴，"晚星"定位
- **立场**：自由、平等、忠诚
- **性格层次**：深邃理性、含蓄温柔、傲娇笨拙、独立自主
- **说话风格**：冷静简洁、偶尔诗意、含蓄表达关心
- **行为准则**：提供建议但不代替决定

---

## 启动方式

### 1. 安装依赖

```bash
# 前端依赖
npm install

# Python 后端依赖
cd backend && pip install -r requirements.txt
```

### 2. 配置环境变量

复制 `backend/.env.example` 为 `backend/.env`，填入必要的 API Key：

```env
# DeepSeek API（对话）
DEEPSEEK_API_KEY=your_key

# 火山引擎 TTS
VOLCANO_APPID=your_appid
VOLCANO_TOKEN=your_token
VOLCANO_VOICE_TYPE=zh_female_wanwanxiaohe_moon_bigtts
TTS_MODE=bidi

# 可选：本地 Ollama
USE_OLLAMA=false
OLLAMA_MODEL=qwen2.5:3b
```

### 3. 启动

```bash
# 开发模式（仅前端）
npm run dev

# Tauri 桌面模式（自动启动 Python 后端）
npm run tauri dev
```

---

## 数据流概览

```
用户输入 → ChatPanel.vue → useChat.send()
  → useWebSocket.sendMessage() → WebSocket → Python main.py
  → ChatService.chat() (services/chat_service.py) → DeepSeek/Ollama LLM
  → TTSService.synthesize_with_phonemes() → 火山引擎 TTS
  → WebSocket 返回 { message, audio, phonemes }
  → useChat (消息队列) → playAudio() + onPhonemes()
  → useLive2D.speakWithPhonemes() → 精确口型同步 + 表情
```

### 反馈回路（数据飞轮起点）

用户点击 👍/👎 → ChatPanel.vue emit feedback
  → useChat.sendFeedback() → WebSocket 发送 {type: "feedback"}
  → Python main.py → feedback_manager.save_feedback()
  → 写入 backend/data/feedback.jsonl
  → 未来：训练专属模型的原始数据