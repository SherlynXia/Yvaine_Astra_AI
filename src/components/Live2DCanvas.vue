<template>
  <div ref="canvasContainer" class="canvas-container">
    <ExpressionPanel
      :current-facial="currentFacial"
      :current-eyes="currentEyes"
      :current-mouth="currentMouth"
      :current-hair="currentHair"
      :current-accessories="currentAccessories"
      @set="setExpression"
      @clear="clearExpression"
    />
    <MotionPanel @play="playMotion" />
    <ChatPanel
      :history="chatHistory"
      :is-connected="isConnected"
      :is-connecting="isConnecting"
      :is-typing="isTyping"
      @send="handleChatSend"
      @test-t-t-s="handleTestTTS"
    />
    <div class="hint">点击模型触发动作，鼠标移动控制视线</div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue';
import { useLive2D } from '../composables/useLive2D';
import { useChat } from '../composables/useChat';
import ExpressionPanel from './ExpressionPanel.vue';
import MotionPanel from './MotionPanel.vue';
import ChatPanel from './ChatPanel.vue';

const canvasContainer = ref<HTMLDivElement | null>(null);

const {
  init,
  resize,
  playMotion,
  setExpression,
  clearExpression,
  currentFacial,
  currentEyes,
  currentMouth,
  currentHair,
  currentAccessories,
  speak,
  speakWithPhonemes,
  applyEmotion,
  destroy,
} = useLive2D();

// 聊天功能 - Yvaine 说话时触发口型和表情
const { history: chatHistory, isConnected, isConnecting, isTyping, isPlaying, send: sendChat } = useChat(
  // onYvaineSpeak - 收到文本时触发（只应用情绪表情，不启动口型）
  (text: string, emotion?: string) => {
    // 文本到达时只应用情绪表情
    // 口型动画将在音频播放时由 phoneme 数据精确驱动
    if (emotion) {
      applyEmotion(emotion);
    }
    // 注意：不调用 speak()，避免提前启动口型动画
  },
  // onAudioPlay - 音频播放时触发（无 phoneme 时的回退）
  (duration: number) => {
    // 根据音频时长播放口型动画（仅在无 phoneme 数据时生效）
    speak('', undefined, duration);
  },
  // onPhonemes - 收到 phoneme 时间轴数据时触发精确口型同步
  (phonemes, emotion, audioStartTime) => {
    speakWithPhonemes(phonemes, emotion, audioStartTime);
  }
);

function handleChatSend(text: string) {
  sendChat(text);
}

// 测试 TTS - 直接发送测试消息触发语音
function handleTestTTS() {
  sendChat('测试语音功能');
}

onMounted(async () => {
  if (!canvasContainer.value) return;
  try {
    await init(canvasContainer.value);

    const onResize = () => {
      if (canvasContainer.value) resize(canvasContainer.value);
    };
    window.addEventListener('resize', onResize);
    setTimeout(onResize, 100);

    (canvasContainer.value as any).__cleanup = () => {
      window.removeEventListener('resize', onResize);
    };
  } catch (e) {
    console.error('Live2D 初始化失败:', e);
  }
});

onBeforeUnmount(() => {
  if (canvasContainer.value && (canvasContainer.value as any).__cleanup) {
    (canvasContainer.value as any).__cleanup();
  }
  destroy();
});
</script>

<style scoped>
.canvas-container {
  width: 100vw;
  height: 100vh;
  background: #1a1a2e;
  position: relative;
  overflow: hidden;
}

.hint {
  position: absolute;
  bottom: 50px;
  left: 50%;
  transform: translateX(-50%);
  color: rgba(255, 255, 255, 0.5);
  font-size: 12px;
  pointer-events: none;
}
</style>