import { ref, watch, onMounted } from 'vue';
import { listen } from '@tauri-apps/api/event';
import { invoke } from '@tauri-apps/api/core';
import { useWebSocket, type ChatMessage, type PhonemeInfo } from './useWebSocket';

export interface ChatHistoryItem {
  role: 'user' | 'yvaine';
  text: string;
  emotion?: string;
}

export function useChat(
  onYvaineSpeak?: (text: string, emotion?: string) => void,
  onAudioPlay?: (duration: number) => void,
  onPhonemes?: (phonemes: PhonemeInfo[], emotion?: string, audioStartTime?: number) => void
) {
  const { connect, disconnect, sendMessage, isConnected, isConnecting, lastMessage, messageQueue, error } = useWebSocket();

  const history = ref<ChatHistoryItem[]>([]);
  const isTyping = ref(false);
  const isPlaying = ref(false);

  // 音频播放器
  let currentAudio: HTMLAudioElement | null = null;

  // 缓存 phoneme 数据，等音频开始播放时同步触发
  let pendingPhonemes: PhonemeInfo[] | null = null;
  let pendingEmotion: string | undefined = undefined;
  // 记录当前正在播放的音频开始时间，用于处理延迟到达的 phoneme 数据
  let currentAudioStartTime: number | null = null;

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

  // 播放音频
  function playAudio(base64Data: string) {
    try {
      // 停止之前的音频
      if (currentAudio) {
        currentAudio.pause();
        currentAudio = null;
      }

      // 验证 base64 数据
      if (!base64Data || base64Data.length < 100) {
        console.warn('⚠️ 音频数据无效或太短');
        return;
      }

      console.log('🔊 创建音频对象...');

      // 将 base64 转换为 Blob URL（兼容性更好）
      const byteCharacters = atob(base64Data);
      const byteNumbers = new Array(byteCharacters.length);
      for (let i = 0; i < byteCharacters.length; i++) {
        byteNumbers[i] = byteCharacters.charCodeAt(i);
      }
      const byteArray = new Uint8Array(byteNumbers);

      // 检测音频格式（根据文件头）
      let mimeType = 'audio/mpeg';
      if (byteArray.length > 3 && byteArray[0] === 0x52 && byteArray[1] === 0x49 && byteArray[2] === 0x46) {
        mimeType = 'audio/wav';
      } else if (byteArray.length > 3 && byteArray[0] === 0x4F && byteArray[1] === 0x67 && byteArray[2] === 0x67) {
        mimeType = 'audio/ogg';
      }
      console.log('🔊 音频格式:', mimeType, '大小:', byteArray.length);

      const blob = new Blob([byteArray], { type: mimeType });
      const audioUrl = URL.createObjectURL(blob);

      const audio = new Audio(audioUrl);
      currentAudio = audio;
      isPlaying.value = true;

      // 音频实际开始播放时，同步触发 phoneme 口型动画
      audio.addEventListener('playing', () => {
        console.log('▶️ 音频开始播放，同步触发 phoneme 口型');
        const audioStartTime = Date.now();
        currentAudioStartTime = audioStartTime;
        if (pendingPhonemes && pendingPhonemes.length > 0 && onPhonemes) {
          onPhonemes(pendingPhonemes, pendingEmotion, audioStartTime);
          // 清空 pending
          pendingPhonemes = null;
          pendingEmotion = undefined;
        } else if (onAudioPlay && audio.duration) {
          // 没有 phoneme 数据时回退到旧模式
          onAudioPlay(audio.duration * 1000);
        }
      });

      audio.addEventListener('canplaythrough', () => {
        console.log('✅ 音频可以播放');
      });

      audio.addEventListener('loadedmetadata', () => {
        console.log('✅ 音频加载成功，时长:', audio.duration, '秒');
      });

      audio.addEventListener('ended', () => {
        console.log('🎵 音频播放结束');
        isPlaying.value = false;
        currentAudio = null;
        currentAudioStartTime = null;
        URL.revokeObjectURL(audioUrl); // 释放内存
      });

      audio.addEventListener('error', (e) => {
        console.error('❌ 音频播放失败:', e);
        isPlaying.value = false;
        currentAudio = null;
        currentAudioStartTime = null;
        URL.revokeObjectURL(audioUrl);
      });

      // 尝试播放
      const playPromise = audio.play();
      if (playPromise !== undefined) {
        playPromise
          .then(() => {
            console.log('▶️ 音频播放开始');
          })
          .catch((err) => {
            console.error('❌ 播放被拒绝:', err);
            isPlaying.value = false;
            currentAudio = null;
            currentAudioStartTime = null;
            URL.revokeObjectURL(audioUrl);
          });
      }
    } catch (e) {
      console.error('音频播放错误:', e);
      isPlaying.value = false;
    }
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
          });

          // 触发 Yvaine 说话（口型 + 表情）
          if (onYvaineSpeak) {
            onYvaineSpeak(msg.text, msg.emotion);
          }
        } else if (msg.type === 'audio' && msg.audioBase64) {
          // 播放音频
          console.log('🎵 收到音频数据，长度:', msg.audioBase64.length);
          playAudio(msg.audioBase64);
        } else if (msg.type === 'phonemes' && msg.phonemes) {
          // 缓存 phoneme 数据，等音频 playing 事件时同步触发
          console.log('📊 收到 phoneme 数据:', msg.phonemes.length, '个音素');
          pendingPhonemes = msg.phonemes;
          pendingEmotion = msg.emotion;

          // 如果音频已经在播放中（phoneme 消息延迟到达），立即触发口型同步
          if (currentAudioStartTime && onPhonemes && isPlaying.value) {
            console.log('🔄 音频播放中收到 phoneme，立即同步口型');
            onPhonemes(pendingPhonemes, pendingEmotion, currentAudioStartTime);
            pendingPhonemes = null;
            pendingEmotion = undefined;
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
    if (currentAudio) {
      currentAudio.pause();
      currentAudio = null;
      isPlaying.value = false;
      currentAudioStartTime = null;
    }
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
  };
}