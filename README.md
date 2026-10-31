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
| 记忆系统 | SQLite 十一表 + ChromaDB 四 collection（bge-small-zh-v1.5 本地加载） |

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
│   │   ├── short_term.py           # ConversationStore（history + summaries 内存）
│   │   ├── summarizer.py           # 上下文压缩（写内存，不落库）
│   │   ├── database.py             # SQLite 十一表（含 workspace + relationship）
│   │   ├── vector_store.py         # ChromaDB 四 collection（+ workspace_items）
│   │   ├── extractor.py            # 事实提取 + memory_layer 分流 + 关系抽取
│   │   ├── reflection.py           # 用户规律反思（含衰减/强化）
│   │   ├── retriever.py            # 七段检索：核心事实/相关/理解/经验/工作话题/关系/短期
│   │   ├── lifecycle.py            # TTL + 衰减 + 话题归档 + 反思调度
│   │   ├── workspace.py            # 工作记忆：话题匹配 + 素材写入 + 归档
│   │   ├── relationship.py         # 关系网：AI↔用户三维 + 用户↔用户融合 + 隐私梯度
│   │   └── user_manager.py         # 用户管理 + 声纹接口预留
│   ├── feedback/
│   │   └── manager.py              # 写入 SQLite feedback 表
│   ├── personality/
│   │   └── system_prompt.txt
│   ├── data/
│   │   ├── feedback.jsonl
│   │   ├── memory.db               # SQLite（不提交）
│   │   ├── chroma/                 # 向量库（不提交）
│   │   ├── conversations/
│   │   ├── memories/
│   │   └── .gitkeep
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

**startup 钩子**：
- `_startup_lifecycle`：启动 `lifecycle_loop`，每 6h 跑一次 TTL 清理 / 衰减写回 / 话题归档 / 反思调度
- `_startup_warmup`：异步预热 ChromaDB（4 个 collection，串行 + 加锁，`asyncio.create_task` 不阻塞端口）

---

### 2. Core（编排层）

#### `core/chat_service.py`
- `ChatService.configure(provider, system_prompt)` — 注入 LLM 和人格
- `ChatService.chat_stream(user_message, session_id)` — 流式对话：记忆检索 → 注入 Prompt → LLM 流式 → 动作/对白分离 → 情绪解析 → 记忆提取 + 被动反思
- `ChatService._maybe_self_review(session_id, user_id, user_name)` — 断开时若会话 ≥6 轮，触发主动回看
- `ChatService.clear_session(session_id)` — 按 `session_id:` 前缀清所有用户的对话历史
- `ChatService.conversations` — key = `f"{session_id}:{user_id}"`，每人独立 10 轮历史

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

#### 文件职责

| 文件 | 职责 |
| :--- | :--- |
| `short_term.py` | `ConversationStore`：本次连接内的 `history` + `summaries`（内存，断开即清） |
| `summarizer.py` | 溢出窗口对话 → LLM 摘要 → 追加进 `conv.summaries`（不落库） |
| `database.py` | SQLite 十一表 CRUD + 迁移 |
| `vector_store.py` | ChromaDB 四 collection 读写（含 workspace_items） |
| `extractor.py` | 事实提取 → `user_memories`；`memory_layer` 分流到 workspace；`mentioned_relations` 观察；被动反思 → `ai_behaviors` |
| `reflection.py` | 用户规律反思 → `ai_reflections`，含衰减/强化（C 方案） |
| `retriever.py` | 七段检索：核心事实 / 相关记忆 / 对用户的理解 / 学到的经验 / 工作话题 / 关系 / 短期记忆 |
| `lifecycle.py` | TTL + 衰减（仅 user_memories）+ 话题归档 + 反思调度 |
| `workspace.py` | 工作记忆：话题匹配（LLM）+ 素材去重 + TTL 归档 + pending 迁移 |
| `relationship.py` | 关系网：三维更新 + 融合逻辑 + 隐私梯度 + AI 观察信号 |
| `user_manager.py` | 用户管理 + 声纹接口预留 |

#### 存储层结构（九层 + 3 辅助）

| 层 | 载体 | 存什么 | 生命周期 |
| :--- | :--- | :--- | :--- |
| 长期记忆·用户 | `user_memories` | `fact`/`event`/`emotion`，按 `subject_id`+`scope` 区分 | 7 天 × 0.85 衰减 + TTL + `expires_at` |
| 长期记忆·反思 | `ai_reflections` | AI 对某个用户的规律认知 | 不删，`importance < 0.4` 休眠不注入 |
| 长期记忆·行为 | `ai_behaviors` | AI 对自己的行为经验 | 不衰减、不删 |
| 工作记忆·话题 | `workspace_topics` | 项目/话题容器（title / summary / ttl_days / status） | TTL 到期归档（软归档，可恢复） |
| 工作记忆·素材 | `workspace_items` | 话题内的设定/角色/情节/想法/草稿 | 跟随话题，话题归档时一起沉眠 |
| 关系网·AI↔用户 | `ai_user_relationships` | 三维（familiarity / trust / intimacy / stage） | 每轮更新，不衰减 |
| 关系网·用户↔用户 | `user_user_relationships` | 融合后的关系（relation_type / closeness / is_mutual） | 每轮观察更新，不删 |
| 关系网·单方声明 | `relation_claims` | "谁说过和谁是什么关系" | 解除关系时删，不衰减 |
| 短期记忆 | `conversation_history` | 场景内逐字对话（跨用户） | 3 天清理 |
| 当前上下文 | `ConversationStore.history` | 本次连接最近 10 轮 | 连接断开即清 |
| 上下文压缩 | `ConversationStore.summaries` | 溢出窗口摘要 | 连接断开即清 |
| 反馈数据 | `feedback` | 👍/👎 原始数据 | 永久，训练用 |

#### SQLite 十一表

| 表 | 关键字段 | 说明 |
| :--- | :--- | :--- |
| `users` | `user_id`, `name`, `voiceprint` | 用户 + `ai_self` |
| `user_memories` | `subject_id`, `scope`, `source_id`, `decay_applied_at`, `expires_at` | 用户的事实/事件/情绪 |
| `ai_reflections` | `user_id`, `evidence_ids`, `importance` | AI 对用户的规律，importance < 0.4 休眠 |
| `ai_behaviors` | `user_id`, `source` | `source` 区分 `user_feedback`/`self_review` |
| `workspace_topics` | `user_id`, `title`, `summary`, `ttl_days`, `status`, `last_touched_at` | 工作话题容器 |
| `workspace_items` | `topic_id`, `item_type`, `content` | 话题素材（setting/character/plot/idea/draft） |
| `ai_user_relationships` | `user_id`, `familiarity`, `trust`, `intimacy`, `stage` | AI ↔ 每个用户的三维 |
| `user_user_relationships` | `user_a`, `user_b`, `relation_type`, `closeness`, `confidence`, `is_mutual`, `observed_sentiment`, `observed_mentions` | 用户间关系（融合后） |
| `relation_claims` | `claimant_id`, `target_id`, `relation_type`, `stated_closeness` | 单方声明（多对多，融合前） |
| `conversation_history` | `session_id`, `user_id`, `role` | 短期记忆逐字 |
| `feedback` | `rating`, `user_message`, `ai_reply` | 训练数据源 |

#### ChromaDB 四 collection

| collection | 对应表 | 检索方式 |
| :--- | :--- | :--- |
| `user_memories` | `user_memories` | `subject_id + scope + type` 过滤 |
| `ai_reflections` | `ai_reflections` | 按 `user_id` 过滤，`importance < 0.4` 不注入 |
| `ai_behaviors` | `ai_behaviors` | 全局，不区分用户 |
| `workspace_items` | `workspace_items` | 按 `topic_id` 过滤（话题内去重） |

#### 写入规则

- `extract_and_store`：
  - `memory_layer=user` → `user_memories`（fact/event/emotion）
  - `memory_layer=workspace` → `workspace.record_item()`（话题匹配 + 素材去重）
  - `relation_info` 有值时 → `relation_claims` + `user_user_relationships`（融合后）
  - `mentioned_relations` 有值时 → `user_user_relationships.observed_sentiment`（滑动平均）
- `reflect_on_self`（被动反思，用户评价触发）→ 写 `ai_behaviors`，`source=user_feedback`
- `self_review`（主动回看，会话 ≥6 轮断开触发）→ 写 `ai_behaviors`，`source=self_review`
- `generate_reflections`（lifecycle 每轮都尝试，`should_reflect` 按自上次反思后新增量 ≥ 5）→ 写 `ai_reflections`，相近的衰减旧的
- `relationship.update_after_turn`（每轮对话同步）→ 更新 `ai_user_relationships`（familiarity+1，情绪词 intimacy+2，口头表扬/批评 trust±1）
- `save_feedback` → 写 `feedback` 表（**不接关系网 trust**，独立数据）

#### 衰减规则（仅 `user_memories`）

- 7 天未访问，每 7 天 × 0.85，按 `decay_applied_at` 幂等
- 下限：`fact` 0.5 / `event` 0.2 / `emotion` 0.1
- TTL：`event` 90 天、`emotion` 30 天、`fact` 永久
- `expires_at` 到期（精确时间点，无 importance 保护）→ 硬删
- `ai_reflections` / `ai_behaviors` **不衰减、不删**

#### 反思衰减（C 方案）

- `dist < 0.1`（几乎重复）→ `importance +0.05`（强化）
- `0.1 ≤ dist < 0.25`（相近冲突）→ 旧反思 `importance -0.15`
- `importance < 0.4` 的反思休眠：**留在库中不删，检索时不注入**
- 休眠的反思被再次强化（`dist < 0.1`）可复活

#### 上下文压缩

- 触发：`ConversationStore.history` 超过 `max_turns*2 + 4` 条
- 处理：溢出最早 4 条 → LLM 压缩成 2-3 句 → 存进 `summaries` 内存列表
- 注入：`get_messages()` 把 `summaries` 拼成一条 system 消息，插在历史之前
- **不落库，断开即清**

#### 短期记忆

- 触发：`build_memory_block` 每次对话都查
- 查询：`conversation_history` 按 `session_id` + 最近 3 天，**不区分用户**，从新到旧累加（`max 800 字符`）
- 注入：`【近期对话】` 段，显示"谁在什么时候说了什么"

#### 长期记忆：工作记忆（workspace）

工作记忆与长期记忆**物理隔离**，存"当前正在创作/讨论的项目素材"，不污染 `user_memories`。

**分流判据**（`_COMMON_OUTPUT_SPEC` 里的 `memory_layer`）：

- `user`：关于人本身的稳定属性、喜好、长期目标、情绪
- `workspace`：当前创作/讨论的素材、设定、情节、角色
- **拿不准 → workspace**（工作记忆可恢复，长期记忆清理代价高）
- strong 模式（用户说"记住…"）→ 强制 `user`

**话题匹配**：

- `_match_or_create_topic()`：LLM 从 active 话题里找匹配的，或新建
- 无 active 话题时跳过 LLM 直接新建（省一次 API）
- 话题内去重：`dist < 0.1` 视为重复，touch 不新增

**工作记忆生命周期**：

- 默认 `ttl_days = 7`，可被对话改写（30 天 / 90 天）
- 每次素材写入 → `last_touched_at = now`（自动续期）
- `lifecycle` 每 6h 扫 `last_touched_at + ttl_days < now` → `status='archived'`
- **归档是软归档**，用户重提话题时 `reactivate_workspace_topic` 恢复
- 注入时最多展示 2 个 active 话题 + 每个话题最近 3 条素材

**注入格式**（`retriever.build_memory_block` 第 5 段）：


**历史素材迁移**：`migrate_cleanup.py` 导出 `pending_workspace.json` → `workspace.import_pending()` 或手动 `migrate_pending_workspace.py` 定向插入。

#### 长期记忆：关系网（relationships）

分两层：**AI ↔ 每个用户**（一对一）+ **用户 ↔ 用户**（社交图）。

**AI ↔ 用户（`ai_user_relationships`）**

| 维度 | 含义 | 更新时机 |
| :--- | :--- | :--- |
| `familiarity` | 聊过多少次 | 每轮 +1 |
| `trust` | 用户对 AI 的态度 | 对话中口头表扬 +1 / 批评 -1 |
| `intimacy` | 用户愿不愿意交心 | 情绪词 +2，写入 private 记忆 +1 |

分级：`stranger`（0-15）/ `acquaintance`（15-35）/ `friend`（35-60）/ `close`（60-80）/ `intimate`（80+）

**feedback 👍/👎 不接 trust**——feedback 是训练数据，和关系网独立。

**用户 ↔ 用户（社交图）**

分两层表：

- **`relation_claims`**（单方声明）：`claimant_id` → `target_id`，谁说过什么关系，独立记录
- **`user_user_relationships`**（融合后）：无向关系 + `closeness` + `is_mutual`

**融合公式**：
双方声明 + 类型一致 → closeness = 双方均值 × 0.9，mutual=1
单方声明 → closeness = stated × (0.4 + 0.5×min(1, mentions/10)) + observed×0.05
只有观察（无声明） → mentions < 5 时为 0；否则 max(0, observed) × 0.3
类型冲突 → relation=acquaintance, mutual=0


**关键设计**：

- **单方声明不能全信**：刚说完"是我朋友"，closeness 只有 0.20，看不到对方任何 shared 记忆
- **需要观察积累**：10 次正向互动后接近 0.49，才能看 fact；要双方确认才一跃到 0.81
- **只有观察不算数**：即使提及 10 次，无声明时 closeness 上限 0.30（防 AI 自己猜错）
- **观察用滑动平均**：`0.8×旧 + 0.2×新`，单次"夏凛好烦"不会让 closeness 暴跌

**双向确认**：

`_build_relation_hint` 两个触发场景：

1. **优先**：有人声称过和当前用户有关系，但当前用户还没确认 → 问当前用户
2. 用户提到 X 但关系未知 → 问用户

AI 问「你和夏凛是什么关系呀？」→ 缓存到 `_relation_pending[session_id]` → 用户答「朋友」（只说词，没主语）→ `_try_resolve_pending` 补上主语 → 写 claim + 融合。

**每个 session 每个名字只问一次**（`_relation_asked`）。

**隐私梯度**：

AI 能不能把「B 的某条记忆」告诉「正在对话的 A」= **三重判定**：

| 条件 | 说明 |
| :--- | :--- |
| `confidence ≥ 0.5` | AI 确定有关系 |
| `closeness ≥ 类型门槛` | A-B 关系够铁 |
| `intimacy ≥ 类型门槛` | A-AI 关系够熟 |

**类型门槛**：

| 记忆 type | 别人的 shared 门槛（closeness） |
| :--- | :--- |
| `fact` | 0.25 |
| `event` | 0.50 |
| `emotion` | 0.70 |

**自己的记忆门槛**（intimacy）：fact+private 15 / event+private 20 / emotion+private 30。`shared` 基本无门槛。

**别人的 private：永不注入**（除非 B 明确授权给 A，当前不实现）。

**注入标注**：可见时前缀 `[你]` 或 `[夏凛·公开]`，让 LLM 知道来源。

#### 迁移脚本

```bash
# 记忆系统重构
python backend/migrate_restructure.py   # memories → user_memories / ai_reflections / ai_behaviors / feedback
python backend/migrate_chroma.py        # ChromaDB 重建三个 collection

# 记忆库整理（跑前先 dry-run 看计划）
python backend/migrate_cleanup.py              # 删过期/重复/一次性，导出 workspace 素材
python backend/migrate_cleanup.py --apply      # 实际执行（自动备份 memory.db）

# 工作记忆历史素材迁移
python backend/migrate_pending_workspace.py             # dry-run
python backend/migrate_pending_workspace.py --apply
```

#### 记忆管理 CLI
python backend/memory_cli.py list      # 列出 user_memories（可能仍指向旧表，待修复）
python backend/memory_cli.py stats     # 统计

### 6. Feedback 层

| 文件 | 说明 |
|------|------|
| `feedback/manager.py` | `save_feedback()` / `get_feedback_stats()`，写入 SQLite `feedback` 表 |

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
    ├── memory/retriever 七段检索：
    │   ├── user_memories：核心事实 + 话题相关（按隐私梯度过滤）
    │   ├── ai_reflections：你对这个人的理解（importance ≥ 0.4）
    │   ├── ai_behaviors：你从过往学到的经验
    │   ├── workspace：当前工作话题（active，按 user_id 严格隔离）
    │   ├── relationship：你和他的关系（三维 + 他认识的人）
    │   └── conversation_history：最近 3 天，从新到旧取（max 800 字符）
    ├── 记忆提取分流：
    │   ├── user_memories：关于人的稳定信息
    │   ├── workspace：当前项目素材
    │   ├── relation_claims + user_user_relationships：关系声明
    │   └── user_user_relationships.observed_sentiment：情感观察
    ├── ConversationStore.summaries：本次连接内的上下文压缩
    ├── LLM 流式生成
    └── SentenceBuffer 句子切分
→ tts/facade 逐句合成音频
→ WebSocket 推送 message + audio 片段
→ useChat 音频队列顺序播放
→ useLive2D.speakWithPhonemes 口型同步
→ 异步后处理：
    ├── relationship.update_after_turn → ai_user_relationships（三维）
    ├── relationship.try_auto_detect_relation → relation_claims（"X 是我朋友"）
    ├── extractor.extract_and_store → user_memories / workspace / relation_claims
    ├── extractor.reflect_on_self → ai_behaviors（用户评价触发）
    └── ConversationStore.add 溢出 → summarizer.compress_to_memory → summaries（内存）
```

### 上下文压缩

```
ConversationStore.history 超过 24 条
    ↓
取最早 4 条 → LLM 压缩成 2-3 句
    ↓
追加到 ConversationStore.summaries（内存）
    ↓
下次 get_messages() 时拼成一条 system 消息
    ↓
连接断开 → summaries 随 ConversationStore 一起清空
```

### 主动回看

```
WebSocket 断开
    ↓
本次会话 ≥ 6 轮？
    ├── 是 → extractor.self_review(最近 12 条对话)
    │        → AI 只看自己的回复 → 写入 ai_behaviors（source=self_review）
    └── 否 → 跳过
```

### 用户规律反思

```
每次 lifecycle 循环（6h）都会尝试
    ↓
should_reflect(user_id, min_new=5)：自上次反思新增 fact+event ≥5？
    ├── 是 → generate_reflections
    │        → LLM 从 user_memories 归纳规律
    │        → 写入 ai_reflections（dist<0.1 强化旧的，0.1-0.25 衰减旧的）
    └── 否 → 跳过
```

### 记忆衰减

```
每 6 小时（启动时补跑一次）
    ↓
solidify_decay()
    ├── 只处理 user_memories
    ├── 起点 = max(last_accessed, decay_applied_at)
    ├── 7 天未访问 → 每 7 天 × 0.85
    ├── 下限：fact 0.5 / event 0.2 / emotion 0.1
    └── decay_applied_at 幂等，连续跑不重复衰减

ai_reflections / ai_behaviors：不衰减、不删
```

### 反馈回路（数据飞轮起点）

用户点击 👍/👎
  → WebSocket 发送 `{type: "feedback"}`
  → feedback/manager.save_feedback()
  → 写入 SQLite `feedback` 表
  → 导出命令：`database.export_feedback_jsonl()`
  → 未来：训练专属模型的原始数据


---

## 已知问题 / 待办

**已修复（历史）：**
- ChromaDB 并行预热 race → 改为串行 + `_get_collection` 加锁
- 短期记忆从旧到新截断 → 改为从新到旧累加
- prompt 花括号未双写导致 `KeyError`
- `_parse_json_array` 截断整批丢 → 改为保留前面完整对象

**待办（backlog）：**
- `memory_cli.py` 适配新表
- 声纹识别（`user_manager` 接口已预留）
- 主动发言（`proactive/loop.py`，让"明天提醒"类事件真正兑现）
- workspace 跨用户协作（`subject_ids` 共享）
- 记忆库索引优化（`_daily_count` 改 range 查询，`solidify_decay` 加 WHERE 过滤）