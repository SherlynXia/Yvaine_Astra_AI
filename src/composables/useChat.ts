import { ref, watch, onMounted } from 'vue';
import { listen } from '@tauri-apps/api/event';
import { invoke } from '@tauri-apps/api/core';
import { useWebSocket, type ChatMessage, type PhonemeInfo } from './useWebSocket';

export interface ChatHistoryItem {
  role: 'user' | 'yvaine';
  text: string;
  emotion?: string;
  messageId?: string;
  feedback?: 'good' | 'bad' | null;
}


export function useChat(
  onYvaineSpeak?: (text: string, emotion?: string) => void,
  onAudioPlay?: (duration: number) => void,
  onPhonemes?: (phonemes: PhonemeInfo[], emotion?: string, audioStartTime?: number) => void,
  onActions?: (actions: string[]) => void,
) {
  const {
    connect, disconnect, sendMessage, sendFeedback: wsSendFeedback,
    listUsers: wsListUsers, switchUser: wsSwitchUser, createUser: wsCreateUser,
    isConnected, isConnecting, lastMessage, messageQueue, error,
  } = useWebSocket();
  const users = ref<UserInfo[]>([]);
  const currentUser = ref<UserInfo | null>(null);
  const history = ref<ChatHistoryItem[]>([]);
  const isTyping = ref(false);
  const isPlaying = ref(false);


  // 组件挂载时监听 Python 启动事件
  onMounted(async () => {
    console.log('🔄 等待 Python 后端启动...');
    
    // 监听 Rust 发送的 python-started 事件
    const unlisten = await listen<number>('python-started', (event) => {
      console.log('✅ Python 后端已启动，端口:', event.payload);
      connect();
    });
    
    // 也监听 python-error 事件
    await listen<string>('python-error', (event) => {
      console.error('❌ Python 后端启动失败:', event.payload);
    });
    
    // 检查 Python 是否已经在运行（可能事件在挂载前已发送）
    try {
      const status = await invoke<{running: boolean, port: number}>('get_python_status');
      console.log('📊 Python 状态:', status);
      if (status.running && status.port > 0) {
        console.log('✅ Python 已在运行，直接连接...');
        connect();
      }
    } catch (e) {
      console.log('⚠️ 无法获取 Python 状态:', e);
    }
    
    // 清理函数
    return () => {
      unlisten();
    };
  });

  let hasLoggedIn = false;

  watch(isConnected, (connected) => {
    if (connected && !hasLoggedIn) {
      hasLoggedIn = true;
      console.log('[Auth] WebSocket 已连接，请求用户列表并登录');
      wsListUsers();
      wsSwitchUser('default');
    }
    if (!connected) {
      hasLoggedIn = false;   // 断线后允许重连再登录
    }
  });

  interface UserInfo {
    user_id: string;
    name: string;
    intimacy?: number;
  }

  // ========== 音频队列 ==========
  interface AudioChunk {
    audio: HTMLAudioElement;
    audioUrl: string;
    phonemes?: PhonemeInfo[];
    words?: any[];
  }

  const audioQueue: AudioChunk[] = [];
  let isPlayingQueue = false;

  function decodeBase64Audio(base64Data: string): { audio: HTMLAudioElement; audioUrl: string } | null {
    try {
      if (!base64Data || base64Data.length < 100) return null;
      const byteCharacters = atob(base64Data);
      const byteNumbers = new Uint8Array(byteCharacters.length);
      for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i);
      }
      let mimeType = 'audio/mpeg';
      if (byteNumbers[0] === 0x52 && byteNumbers[1] === 0x49 && byteNumbers[2] === 0x46) {
        mimeType = 'audio/wav';
      } else if (byteNumbers[0] === 0x4F && byteNumbers[1] === 0x67 && byteNumbers[2] === 0x67) {
        mimeType = 'audio/ogg';
      }
      const blob = new Blob([byteNumbers], { type: mimeType });
      const url = URL.createObjectURL(blob);
      const audio = new Audio(url);
      return { audio, audioUrl: url };
    } catch (e) {
      console.error('解码音频失败:', e);
      return null;
    }
  }

  function enqueueAudio(base64: string, phonemes?: PhonemeInfo[], words?: any[]) {
    const decoded = decodeBase64Audio(base64);
    if (!decoded) return;
    audioQueue.push({ audio: decoded.audio, audioUrl: decoded.audioUrl, phonemes, words });
    if (!isPlayingQueue) {
      playQueue();
    }
  }

  async function playQueue() {
    isPlayingQueue = true;
      isPlaying.value = true;

    while (audioQueue.length > 0) {
      const chunk = audioQueue.shift()!;
      await new Promise<void>((resolve) => {
        chunk.audio.addEventListener('playing', () => {
          if (chunk.phonemes && chunk.phonemes.length > 0 && onPhonemes) {
            const startTime = Date.now();
            onPhonemes(chunk.phonemes, undefined, startTime);
          } else if (onAudioPlay && chunk.audio.duration) {
            onAudioPlay(chunk.audio.duration * 1000);
        }
      });
        chunk.audio.addEventListener('ended', () => {
          URL.revokeObjectURL(chunk.audioUrl);
          resolve();
        });
        chunk.audio.addEventListener('error', () => {
          URL.revokeObjectURL(chunk.audioUrl);
          resolve();
      });
        chunk.audio.play().catch((e) => {
          console.error('播放失败:', e);
          resolve();
        });
      });
    }

    isPlayingQueue = false;
      isPlaying.value = false;
    }

  // 监听后端消息 - 使用消息队列确保不遗漏
  watch(
    messageQueue,
    (queue) => {
      // 处理队列中所有未处理的消息
      while (queue.length > 0) {
        const msg = queue.shift();
        if (!msg) continue;

        console.log('🔄 处理消息:', msg.type, msg.type === 'audio' ? `长度=${msg.audioBase64?.length}` : '');

        if (msg.type === 'message' && msg.text) {
          isTyping.value = false;
          history.value.push({
            role: 'yvaine',
            text: msg.text,
            emotion: msg.emotion,
            messageId: msg.messageId,   // s保存 messageId
            feedback: null,             // 初始未评分
          });
          // 1. 先应用情绪（基调）
          if (onYvaineSpeak) {
            onYvaineSpeak(msg.text, msg.emotion);
          }

          // 2. 再应用动作（优先级更高，可覆盖表情）
          if (msg.actions && msg.actions.length > 0) {
            onActions?.(msg.actions);
          }
        } else if (msg.type === 'user_list') {
          users.value = msg.users || [];
          console.log('[Auth] 用户列表:', users.value);
        } else if (msg.type === 'login_ack') {
          currentUser.value = {
            user_id: msg.userId || 'default',
            name: msg.name || '主人',
          };
          console.log('[Auth] 已登录:', currentUser.value);
        } else if (msg.type === 'user_created') {
          console.log('[Auth] 新建用户:', msg.userId, msg.name);
          wsListUsers();  // 刷新列表
        } else if (msg.type === 'audio' && msg.audioBase64) {
          console.log('🎵 收到音频片段', msg.sequenceIndex, '长度:', msg.audioBase64.length);
          // phonemes 现在跟 audio 一起到达
          enqueueAudio(msg.audioBase64, msg.phonemes, msg.words);
        }else if (msg.type === 'feedback_ack') {
          console.log(`[Feedback] ${msg.status}: ${msg.messageId}`);
          if (msg.status !== 'ok') {
            // 保存失败，回滚本地状态
            const item = history.value.find(h => h.messageId === msg.messageId);
            if (item) item.feedback = null;
          }
        } else if (msg.type === 'error') {
          // 后端报错（如 TTS 失败）
          isTyping.value = false;
          console.warn('⚠️ 后端错误:', msg.text);
        }
      }
    },
    { deep: true }
  );

  async function send(text: string) {
    if (!text.trim()) return;

    // 确保连接
    if (!isConnected.value) {
      try {
        await connect();
      } catch (e) {
        console.error('连接失败:', e);
        return;
      }
    }

    // 添加用户消息到历史
    history.value.push({ role: 'user', text: text.trim() });
    isTyping.value = true;

    // 发送给后端
    sendMessage(text.trim());
  }

  function clearHistory() {
    history.value = [];
  }

  function stopAudio() {
    audioQueue.length = 0;
    isPlayingQueue = false;
      isPlaying.value = false;
  }

  function sendFeedback(messageId: string, rating: 'good' | 'bad') {
    // 本地先乐观更新
    const item = history.value.find(h => h.messageId === messageId);
    if (!item || item.feedback !== null) return;  // 已经评过就跳过

    const ok = wsSendFeedback(messageId, rating);
    if (ok) {
      item.feedback = rating;
    }
  }

  function switchUser(userId: string) {
  if (wsSwitchUser(userId)) {
    history.value = [];  // 切换用户清空当前会话历史
    isTyping.value = false;
  }
}

function createUser(name: string) {
  const trimmed = name.trim();
  if (trimmed) wsCreateUser(trimmed);
}

  return {
    history,
    isConnected,
    isConnecting,
    isTyping,
    isPlaying,
    error,
    send,
    clearHistory,
    connect,
    disconnect,
    stopAudio,
    sendFeedback,
    users, 
    currentUser, 
    switchUser, 
    createUser,
  };
}