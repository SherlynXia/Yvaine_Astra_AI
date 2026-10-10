import { ref, onBeforeUnmount } from 'vue';

export interface PhonemeInfo {
  phoneme: string;
  startTime: number;  // 秒
  endTime: number;
  confidence: number;
}

export interface WordInfo {
  word: string;
  startTime: number;
  endTime: number;
  confidence: number;
}

export interface ChatMessage {
  type: 'message' | 'audio' | 'phonemes' | 'error' | 'feedback_ack';
  text?: string;
  emotion?: string;
  audioBase64?: string;
  phonemes?: PhonemeInfo[];
  words?: WordInfo[];
  durationMs?: number;
  sessionId?: string;  // 会话ID
  messageId?: string;
  status?: string;
}

export function useWebSocket() {
  const ws = ref<WebSocket | null>(null);
  const isConnected = ref(false);
  const isConnecting = ref(false);
  const lastMessage = ref<ChatMessage | null>(null);
  const error = ref<string | null>(null);
  const wsUrl = ref<string>('');
  // 消息队列，用于处理短时间内连续到达的消息
  const messageQueue = ref<ChatMessage[]>([]);

  const sendFeedback = (messageId: string, rating: 'good' | 'bad'): boolean => {
    if (!ws.value || ws.value.readyState !== WebSocket.OPEN) {
      console.warn('[Feedback] WebSocket 未连接');
      return false;
    }
    ws.value.send(JSON.stringify({
      type: 'feedback',
      messageId,
      rating,
    }));
    return true;
  };

  async function getWebSocketUrl(): Promise<string> {
    // 尝试通过 Tauri Rust 后端获取 Python 服务的 WebSocket 地址
    try {
      const { invoke } = await import('@tauri-apps/api/core');
      const url = await invoke<string>('get_python_url');
      if (url) return url;
    } catch {
      // Tauri 不可用或命令失败，使用默认地址
    }

    // 回退：直接尝试默认端口（开发模式）
    return 'ws://127.0.0.1:8000/ws/chat';
  }

  async function connect(): Promise<void> {
    if (ws.value?.readyState === WebSocket.OPEN) {
      return;
    }

    isConnecting.value = true;
    error.value = null;

    try {
      const url = await getWebSocketUrl();
      if (!url) {
        // 如果获取不到 URL，等待 2 秒后重试
        console.log('⏳ Python 后端尚未就绪，2秒后重试...');
        setTimeout(() => {
          isConnecting.value = false;
          connect();
        }, 2000);
        return;
      }

      wsUrl.value = url;
      console.log('🔌 连接 WebSocket:', url);

      const socket = new WebSocket(url);

      socket.onopen = () => {
        console.log('✨ 与 Yvaine 的灵魂连接已建立');
        isConnected.value = true;
        isConnecting.value = false;
        ws.value = socket;
      };

      socket.onmessage = (event) => {
        try {
          const data = JSON.parse(event.data) as ChatMessage;
          console.log('📨 收到消息:', data);
          // 加入消息队列并更新 lastMessage（确保 watch 能触发）
          messageQueue.value.push(data);
          lastMessage.value = { ...data, _timestamp: Date.now() } as any;
        } catch (e) {
          console.error('消息解析失败:', e);
        }
      };

      socket.onclose = () => {
        console.log('💫 灵魂连接已断开');
        isConnected.value = false;
        isConnecting.value = false;
        ws.value = null;
      };

      socket.onerror = (e) => {
        console.error('❌ WebSocket 错误:', e);
        error.value = '连接失败，请检查 Python 后端是否已启动';
        isConnecting.value = false;
      };
    } catch (e) {
      isConnecting.value = false;
      error.value = String(e);
      console.error('连接异常:', e);
    }
  }

  function disconnect() {
    if (ws.value) {
      ws.value.close();
      ws.value = null;
    }
    isConnected.value = false;
  }

  function sendMessage(text: string): boolean {
    if (!ws.value || ws.value.readyState !== WebSocket.OPEN) {
      error.value = '连接未建立';
      return false;
    }

    ws.value.send(JSON.stringify({ text }));
    return true;
  }

  onBeforeUnmount(() => {
    disconnect();
  });

  return {
    ws,
    isConnected,
    isConnecting,
    lastMessage,
    messageQueue,
    error,
    wsUrl,
    connect,
    disconnect,
    sendMessage,
    sendFeedback,
  };
}