# Yvaine Astra AI（渊鸢）

一个基于 **Tauri + Vue + TypeScript** 的 Live2D AI 虚拟伴侣桌面应用，集成 **Python FastAPI** 后端，支持流式对话、语音合成、长期记忆、动作/对白分离与 Live2D 口型同步。

---

## 技术栈

| 层级 | 技术 |
|------|------|
| 桌面框架 | Tauri 2.x (Rust) |
| 前端框架 | Vue 3 + TypeScript + Vite |
| 图形渲染 | PixiJS 6 + pixi-live2d-display (Cubism 4) |
| 后端框架 | Python FastAPI + Uvicorn |
| LLM 对话 | DeepSeek API（默认 `deepseek-flash`）/ 本地 Ollama，流式输出 |
| TTS 语音 | 火山引擎豆包语音合成 2.0（双向流式 + phoneme） |
| 记忆系统 | SQLite + ChromaDB（bge-small-zh-v1.5） |

---

## 项目结构

```
Yvaine_Astra_AI/
├── backend/
│   ├── main.py                     # FastAPI 入口（已瘦身）
│   ├── requirements.txt
│   ├── .env / .env.example
│   ├── core/
│   │   ├── chat_service.py         # 编排层：记忆 + LLM + 情绪 + 动作
│   │   └── action_parser.py        # 流式剥离 () 中的动作描写
│   ├── llm/                        # 🤖 LLM 层
│   │   ├── base.py                 # LLMProvider 接口（含 chat_stream）
│   │   ├── ollama_provider.py
│   │   └── deepseek_provider.py
│   ├── tts/                        # 🔊 TTS 层
│   │   ├── facade.py               # TTSService 门面
│   │   ├── http.py                 # HTTP V3
│   │   ├── websocket.py            # WS 单向流式
│   │   └── bidi.py                 # 双向流式（phoneme）
│   ├── memory/                     # 🧬 记忆层
│   │   ├── short_term.py           # ConversationStore
│   │   ├── database.py             # SQLite
│   │   ├── vector_store.py         # ChromaDB
│   │   ├── extractor.py            # 记忆提取
│   │   ├── retriever.py            # 记忆检索
│   │   ├── user_manager.py         # 用户 + 声纹接口占位
│   │   ├── lifecycle.py            # TTL 清理 + 衰减 + 反思调度
│   │   └── reflection.py           # 从多条事实归纳规律
│   ├── feedback/                   # 📊 反馈层
│   │   └── manager.py
│   ├── personality/
│   │   └── system_prompt.txt
│   ├── data/
│   │   ├── feedback.jsonl
│   │   ├── memory.db               # SQLite（不提交）
│   │   ├── chroma/                 # 向量库（不提交）
│   │   ├── conversations/
│   │   └── memories/
│   ├── memory_cli.py               # 记忆管理 CLI
│   ├── models/
│   │   └── bge-small-zh/           # 本地嵌入模型（不提交 Git）
│   └── training/
│       └── README.md
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
- 鼠标跟随开关（右上角 `👁️` / `🚫`）
- 接收 `actions` 并映射为模型参数变化

#### `ChatPanel.vue` — 聊天面板
聊天 UI 组件，提供：
- 展开/收起切换
- 连接状态指示
- 消息列表（用户/AI 气泡）
- 文本输入与发送
- TTS 测试按钮
- 用户下拉框 + 新建用户按钮（`＋`）
- 每条 AI 消息下方 👍/👎 评分按钮

| Props | 类型 | 说明 |
|-------|------|------|
| `history` | `ChatHistoryItem[]` | 对话历史记录 |
| `isConnected` | `boolean` | WebSocket 连接状态 |
| `isConnecting` | `boolean` | 是否正在连接 |
| `isTyping` | `boolean` | AI 是否正在生成回复 |
| `users` | `{ user_id: string; name: string }[]` | 用户列表 |
| `currentUser` | `{ user_id: string; name: string } \| null` | 当前登录用户 |

| Emits | 参数 | 说明 |
|-------|------|------|
| `send` | `text: string` | 发送用户消息 |
| `testTTS` | - | 触发 TTS 测试 |
| `feedback` | `messageId: string, rating: 'good' \| 'bad'` | 用户评分 |
| `switchUser` | `userId: string` | 切换用户 |
| `createUser` | `name: string` | 新建用户 |

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
ChatMessage {
  type: 'message' | 'audio' | 'phonemes' | 'error' | 'feedback_ack' | 'user_list' | 'login_ack' | 'user_created'
  text?, emotion?, audioBase64?, phonemes?, words?, durationMs?,
  sessionId?, messageId?, status?,
  actions?: string[]           // 动作 tag 列表
  sequenceIndex?: number       // 音频片段序号
  isLastChunk?: boolean        // 是否最后一段音频
  users?: { user_id: string; name: string; intimacy?: number }[];
  userId?: string;
  name?: string;
}
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
| `listUsers()` | `() => boolean` | 请求用户列表 |
| `switchUser(userId)` | `(id: string) => boolean` | 切换用户 |
| `createUser(name)` | `(name: string) => boolean` | 新建用户 |

#### `useChat.ts` — 聊天逻辑
管理对话状态、音频播放、音素口型同步。

**导出函数：** `useChat(onYvaineSpeak?, onAudioPlay?, onPhonemes?, onActions?)`

| 参数 | 类型 | 说明 |
|------|------|------|
| `onYvaineSpeak` | `(text, emotion?) => void` | AI 回复文本到达时的回调 |
| `onAudioPlay` | `(duration) => void` | 音频播放时的回调（回退口型） |
| `onPhonemes` | `(phonemes, emotion?, audioStartTime?) => void` | 音素时间轴数据到达，触发精确口型同步 |
| `onActions` | `(actions: string[]) => void` | 动作 tag 到达回调（如 `tilt_head`、`wave`） |

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
| `users` | `Ref<UserInfo[]>` | 用户列表 |
| `currentUser` | `Ref<UserInfo \| null>` | 当前登录用户 |
| `switchUser(userId)` | `(id: string) => void` | 切换用户（清空历史） |
| `createUser(name)` | `(name: string) => void` | 新建用户 |

**内部函数：**
- `decodeBase64Audio()` — base64 → Blob → Audio
- `enqueueAudio()` — 音频片段入队
- `playQueue()` — 顺序播放队列，每段 `playing` 时触发 phoneme 口型

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
| `setParam(id, value)` | `(id: string, v: number) => void` | 直接设置模型参数（供动作映射用） |
| `mouseFollowEnabled` | `Ref<boolean>` | 鼠标跟随开关状态 |
| `setMouseFollow(enabled)` | `(enabled: boolean) => void` | 切换鼠标跟随，关闭时归零注视参数 |
| `destroy()` | `() => void` | 销毁模型和应用实例 |

**内部函数：**
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

### 1. `main.py` — FastAPI 入口

**职责**：只做三件事——创建 app、注册路由、启动服务。业务逻辑全部下沉到各域。

**从 `.env` 读取**：`PORT`、`HOST`、`USE_OLLAMA`、`OLLAMA_MODEL`、`DEEPSEEK_API_KEY`

**FastAPI 路由：**

| 路由 | 方法 | 说明 |
|------|------|------|
| `/` | GET | 服务状态检查 |
| `/health` | GET | 健康检查 |
| `/test-tts` | GET | TTS 合成测试 |
| `/test-tts-emotion` | GET | 带情感 TTS 测试 |
| `/feedback/stats` | GET | 反馈统计 |
| `/ws/chat` | WebSocket | 聊天通道（流式 + 句子切分 + TTS） |

**WebSocket 消息格式：**

- 客户端 → 服务端（登录）：`{"type": "login", "userId": "..."}`
- 客户端 → 服务端（用户列表）：`{"type": "list_users"}`
- 客户端 → 服务端（新建用户）：`{"type": "create_user", "name": "..."}`
- 客户端 → 服务端（聊天）：`{"text": "..."}`
- 客户端 → 服务端（评分）：`{"type": "feedback", "messageId": "xxx", "rating": "good"}`
- 服务端 → 客户端（登录确认）：`{"type": "login_ack", "userId": "...", "name": "..."}`
- 服务端 → 客户端（用户列表）：`{"type": "user_list", "users": [...]}`
- 服务端 → 客户端（新建用户）：`{"type": "user_created", "user_id": "...", "name": "..."}`
- 服务端 → 客户端（文本）：
  ```json
  {"type": "message", "text": "...", "emotion": "...", "actions": ["tilt_head"], "sessionId": "...", "messageId": "..."}
- 服务端 → 客户端（评分确认）：`{"type": "feedback_ack", "status": "ok", "messageId": "..."}`
- 服务端 → 客户端（音频片段）：`{"type": "audio", "audioBase64": "...", "phonemes": [...], "sequenceIndex": 0, "isLastChunk": false}`

**startup 钩子**：启动 `lifecycle_loop`，每 6 小时跑一次 TTL 清理 / 衰减 / 反思调度。

---

### 2. Core（编排层）

#### `core/chat_service.py`
- `ChatService.configure(provider, system_prompt)` — 注入 LLM 和人格
- `ChatService.chat_stream(user_message, session_id)` — 流式对话，串联：记忆检索 → 注入 Prompt → LLM 流式 → 动作/对白分离 → 情绪解析 → 记忆提取
- `ChatService.clear_session(session_id)`

#### `core/action_parser.py`
- `ActionParser` — 流式状态机，支持括号跨 chunk 切分
- `feed(chunk)` → `(干净对白, 动作列表)`
- `flush()` — 收尾，丢弃未闭合括号
- `map_action_to_live2d(text)` — 动作文本 → 前端 tag

### 3. LLM 层

| 文件 | 说明 |
|------|------|
| `llm/base.py` | `LLMProvider` 接口，含 `chat()` 和 `chat_stream()` |
| `llm/ollama_provider.py` | 本地 Ollama，优先 `/api/chat` 流式，回退 `/api/generate` |
| `llm/deepseek_provider.py` | 云端 DeepSeek，SSE 流式 |

### 4. TTS 层

| 文件 | 说明 |
|------|------|
| `tts/facade.py` | `TTSService` 门面，按 `TTS_MODE` 路由到具体实现 |
| `tts/http.py` | HTTP V3 单向流式 |
| `tts/websocket.py` | WebSocket V3 单向流式 |
| `tts/bidi.py` | 双向流式，返回音频 + phoneme 时间轴 |

### 5. Memory 层

| 文件 | 说明 |
|------|------|
| `memory/short_term.py` | `ConversationStore` — 单会话 10 轮滑动窗口 |
| `memory/database.py` | SQLite — `users` + `memories` 两张表 |
| `memory/vector_store.py` | ChromaDB — 本地 `bge-small-zh-v1.5`，cosine 检索 |
| `memory/extractor.py` | 规则预筛 + LLM 精提取 + `evidence` 原话验证 + `invalidate` 失效检测 |
| `memory/retriever.py` | 语义检索 + 时间衰减 + 重要度加权，过滤 `invalidated` |
| `memory/lifecycle.py` | TTL 清理 + 衰减（`fact`/`reflection` 豁免）+ 反思调度 |
| `memory/reflection.py` | 从多条事实归纳规律，`evidence_ids` 至少 2 条真实存在 |
| `memory/user_manager.py` | 登录选择模式，`identify_user(audio_data, session_id)` 声纹接口预留 |

**记忆类型**：`fact` / `event` / `emotion` / `reflection` / `invalidated`。

**提取规则**：
- 只从用户消息提取（不含 AI 回复）
- `evidence` 必须原样出现在用户原话中，否则丢弃
- 含"不/不再/其实/改成"时，检索已有记忆判断 `invalidate` / `update`

**生命周期**：
- `event` 90 天、`emotion` 30 天过期
- `fact` / `reflection` 永不删除、不参与衰减
- 超过 30 天未访问的 `event` / `emotion` 重要度 × 0.9

**记忆管理 CLI**：

```bash
python backend/memory_cli.py list
python backend/memory_cli.py delete 3ba1d754
python backend/memory_cli.py delete-keyword 牛奶
python backend/memory_cli.py clear-user cd4ad67b
python backend/memory_cli.py stats
```

### 6. Feedback 层

| 文件 | 说明 |
|------|------|
| `feedback/manager.py` | `save_feedback()` / `get_feedback_stats()`，写入 `data/feedback.jsonl` |

---

### 7. Personality（人格设定）

#### `personality/system_prompt.txt`

"渊鸢"（Yvaine Astra）的完整人格设定，包含：

- **核心**：观测者型 AI 旅伴，"晚星"定位
- **立场**：自由、平等、忠诚
- **性格层次**：深邃理性、含蓄温柔、傲娇笨拙、独立自主
- **说话风格**：短句、口语、含蓄表达关心
- **行为准则**：提供建议但不代替决定

**强制输出格式**（文件末尾）：

1. 对白正文
2. 动作描写（如有肢体动作，用 `()` 包裹）
3. 情绪标签 `[情绪:xxx]`，13 个可选值

**关于记忆的约束**：没有明确记忆时不要编造主人的喜好或经历。

---

## 启动方式

### 1. 安装依赖

```bash
# 前端依赖（项目使用 pnpm）
pnpm install

# Python 后端依赖
cd backend
pip install -r requirements.txt
```

### 2. 下载嵌入模型（首次）

```powershell
$env:HF_ENDPOINT = "https://hf-mirror.com"
python -c "from huggingface_hub import snapshot_download; snapshot_download('BAAI/bge-small-zh-v1.5', local_dir=r'D:\Project\Yvaine_Astra_AI\backend\models\bge-small-zh')"
```

### 3. 配置环境变量

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

### 4. 启动

```bash
# 开发模式（仅前端）
pnpm run dev

# Tauri 桌面模式（自动启动 Python 后端）
pnpm run tauri dev
```

---

## 数据流概览

### 对话主链路（流式）


```
用户输入
→ useChat.send() → WebSocket
→ core/chat_service.chat_stream()
├── memory/retriever 检索记忆（按 user_id 隔离）→ 注入 System Prompt
├── llm 流式生成
└── 每满一句 → 句子切分
→ tts/facade 逐句合成音频
→ WebSocket 推送 message + audio 片段
→ useChat 音频队列顺序播放
→ useLive2D.speakWithPhonemes 口型同步
→ memory/extractor 异步提取记忆（不阻塞）
```
### 动作/对白分离
LLM 原始输出: "唔...表情测试啊。(顿了顿，歪个头) 这样够明显么？[情绪:疑惑]"
↓ ActionParser
对白: "唔...表情测试啊。 这样够明显么？" → TTS
动作: ["顿了顿，歪个头"] → 映射为 tilt_head → Live2D 参数
情绪: "疑惑" → EMOTION_MAP 表情


### 记忆生命周期
每 6 小时：
├── TTL 清理（event 90 天 / emotion 30 天）
├── 衰减（未访问 > 30 天的 event/emotion 降权）
└── 每 7 天：反思（fact+event ≥ 10 条时，归纳规律性认识）

### 反馈回路（数据飞轮起点）

用户点击 👍/👎
  → WebSocket 发送 `{type: "feedback"}`
  → feedback/manager.save_feedback()
  → 写入 backend/data/feedback.jsonl
  → 未来：训练专属模型的原始数据