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

    <!-- 🔥 鼠标跟随开关 -->
    <button
      class="follow-toggle"
      :class="{ active: mouseFollowEnabled }"
      @click="toggleMouseFollow"
      :title="mouseFollowEnabled ? '关闭视线跟随' : '开启视线跟随'"
    >
      {{ mouseFollowEnabled ? '👁️' : '🚫' }}
    </button>

    <ChatPanel
      :history="chatHistory"
      :is-connected="isConnected"
      :is-connecting="isConnecting"
      :is-typing="isTyping"
      :users="users"
      :current-user="currentUser"
      @send="handleChatSend"
      @test-tts="handleTestTTS"
      @feedback="sendFeedback"
      @switch-user="switchUser"
      @create-user="createUser"
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
  mouseFollowEnabled,   // 🔥 新增
  setMouseFollow,       // 🔥 新增
} = useLive2D();

// 动作 tag → Live2D 行为
// 只处理肢体动作，表情类交给 emotion 处理，避免和 EMOTION_MAP 冲突
function handleActions(actions: string[]) {
  // 同一批动作只取第一个肢体动作，避免 playMotion 互相打断
  for (const tag of actions) {
    switch (tag) {
      case 'wave':
        playMotion('Tap', 0);
        return;
      case 'tilt_head':
        // 模型没有歪头动作时，用媚眼动作占位；有 ParamAngleZ 可改为直接设参数
        playMotion('Tap', 1);
        return;
      case 'nod':
        playMotion('Tap', 0);
        return;
      case 'shake_head':
        playMotion('Tap', 1);
        return;
      // smile / blush / pause / sigh / blink 不在这里处理，
      // 表情由 onYvaineSpeak 的 emotion 决定，避免双重触发
      default:
        break;
    }
  }
}

const {
  history: chatHistory,
  isConnected,
  isConnecting,
  isTyping,
  isPlaying,
  send: sendChat,
  sendFeedback,
  users, 
  currentUser, 
  switchUser, 
  createUser, 
} = useChat(
  (text: string, emotion?: string) => {
    if (emotion) applyEmotion(emotion);
  },
  (duration: number) => {
    speak('', undefined, duration);
  },
  (phonemes, emotion, audioStartTime) => {
    speakWithPhonemes(phonemes, emotion, audioStartTime);
  },
  handleActions,   // 🔥 第 4 个参数
);

function toggleMouseFollow() {
  setMouseFollow(!mouseFollowEnabled.value);
}

function handleChatSend(text: string) {
  sendChat(text);
}

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

/* 🔥 鼠标跟随开关 */
.follow-toggle {
  position: absolute;
  top: 16px;
  right: 16px;
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: rgba(20, 20, 40, 0.7);
  color: #fff;
  font-size: 16px;
  cursor: pointer;
  opacity: 0.5;
  transition: all 0.2s;
  z-index: 50;
}

.follow-toggle:hover {
  opacity: 1;
}

.follow-toggle.active {
  opacity: 0.9;
  border-color: rgba(100, 200, 255, 0.6);
  box-shadow: 0 0 8px rgba(100, 200, 255, 0.3);
}
</style>