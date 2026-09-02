<template>
  <div class="chat-panel" :class="{ expanded: isExpanded }">
    <!-- 展开/收起按钮 -->
    <button class="toggle-btn" @click="toggleExpand">
      <span v-if="isExpanded">✕</span>
      <span v-else>💬</span>
    </button>

    <!-- 聊天内容区 -->
    <div v-show="isExpanded" class="chat-content">
      <!-- 连接状态 -->
      <div class="status-bar">
        <span class="status-dot" :class="{ connected: isConnected }"></span>
        <span class="status-text">{{ statusText }}</span>
      </div>

      <!-- 消息列表 -->
      <div class="message-list">
        <div v-if="history.length === 0" class="empty-hint">
          和 Yvaine 说点什么吧~
        </div>
        <template v-for="(msg, index) in history" :key="index">
          <div class="message" :class="msg.role">
            <div class="avatar">{{ msg.role === 'user' ? '👤' : '✨' }}</div>
            <div class="bubble">
              <div class="text">{{ msg.text }}</div>
              <div v-if="msg.emotion" class="emotion-tag">{{ msg.emotion }}</div>
            </div>
          </div>
        </template>
        <div v-if="isTyping" class="message yvaine typing">
          <div class="avatar">✨</div>
          <div class="bubble">
            <div class="dots">
              <span></span>
              <span></span>
              <span></span>
            </div>
          </div>
        </div>
      </div>

      <!-- 输入区 -->
      <div class="input-area">
        <input
          v-model="inputText"
          type="text"
          placeholder="输入消息..."
          @keydown.enter="handleSend"
          :disabled="isTyping || isConnecting"
        />
        <button
          @click="handleSend"
          :disabled="!canSend"
        >
          发送
        </button>
      </div>

      <!-- TTS 测试按钮 -->
      <div class="test-area">
        <button class="test-btn" @click="testTTS" :disabled="!isConnected">
          🔊 测试语音
        </button>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue';

const props = defineProps<{
  history: { role: 'user' | 'yvaine'; text: string; emotion?: string }[];
  isConnected: boolean;
  isConnecting: boolean;
  isTyping: boolean;
}>();

const emit = defineEmits<{
  send: [text: string];
  testTTS: [];
}>();

const isExpanded = ref(true);
const inputText = ref('');

const statusText = computed(() => {
  if (props.isConnecting) return '连接中...';
  if (props.isConnected) return 'Yvaine 在线';
  return '离线';
});

const canSend = computed(() => {
  return inputText.value.trim().length > 0 && !props.isTyping && !props.isConnecting;
});

function toggleExpand() {
  isExpanded.value = !isExpanded.value;
}

function handleSend() {
  const text = inputText.value.trim();
  if (!text || props.isTyping) return;
  emit('send', text);
  inputText.value = '';
}

function testTTS() {
  emit('testTTS');
}
</script>

<style scoped>
.chat-panel {
  position: fixed;
  right: 20px;
  bottom: 20px;
  z-index: 100;
  transition: all 0.3s ease;
}

.chat-panel.expanded {
  width: 360px;
  height: 500px;
}

.toggle-btn {
  position: absolute;
  right: 0;
  bottom: 0;
  width: 50px;
  height: 50px;
  border-radius: 50%;
  border: none;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  font-size: 20px;
  cursor: pointer;
  box-shadow: 0 4px 15px rgba(102, 126, 234, 0.4);
  transition: all 0.3s ease;
  z-index: 10;
}

.toggle-btn:hover {
  transform: scale(1.1);
  box-shadow: 0 6px 20px rgba(102, 126, 234, 0.6);
}

.chat-panel.expanded .toggle-btn {
  right: 10px;
  bottom: 10px;
  width: 36px;
  height: 36px;
  font-size: 14px;
}

.chat-content {
  width: 100%;
  height: 100%;
  background: rgba(20, 20, 40, 0.95);
  border-radius: 16px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  display: flex;
  flex-direction: column;
  overflow: hidden;
  backdrop-filter: blur(10px);
}

.status-bar {
  padding: 10px 16px;
  display: flex;
  align-items: center;
  gap: 8px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.05);
}

.status-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: #ff5f5f;
  transition: background 0.3s;
}

.status-dot.connected {
  background: #5fff5f;
  box-shadow: 0 0 8px #5fff5f;
}

.status-text {
  font-size: 12px;
  color: rgba(255, 255, 255, 0.6);
}

.message-list {
  flex: 1;
  overflow-y: auto;
  padding: 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.empty-hint {
  text-align: center;
  color: rgba(255, 255, 255, 0.3);
  font-size: 14px;
  margin-top: 40px;
}

.message {
  display: flex;
  gap: 10px;
  align-items: flex-start;
}

.message.user {
  flex-direction: row-reverse;
}

.avatar {
  width: 32px;
  height: 32px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  background: rgba(255, 255, 255, 0.1);
  font-size: 16px;
  flex-shrink: 0;
}

.bubble {
  max-width: 240px;
  padding: 10px 14px;
  border-radius: 14px;
  font-size: 14px;
  line-height: 1.5;
  word-break: break-word;
}

.message.yvaine .bubble {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  border-bottom-left-radius: 4px;
}

.message.user .bubble {
  background: rgba(255, 255, 255, 0.1);
  color: rgba(255, 255, 255, 0.9);
  border-bottom-right-radius: 4px;
}

.emotion-tag {
  font-size: 11px;
  opacity: 0.7;
  margin-top: 4px;
}

/* 输入中动画 */
.dots {
  display: flex;
  gap: 4px;
  padding: 4px 0;
}

.dots span {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: rgba(255, 255, 255, 0.6);
  animation: bounce 1.4s infinite ease-in-out;
}

.dots span:nth-child(1) { animation-delay: 0s; }
.dots span:nth-child(2) { animation-delay: 0.2s; }
.dots span:nth-child(3) { animation-delay: 0.4s; }

@keyframes bounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.5; }
  40% { transform: scale(1); opacity: 1; }
}

.input-area {
  padding: 12px 16px;
  display: flex;
  gap: 10px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.input-area input {
  flex: 1;
  padding: 10px 14px;
  border-radius: 20px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.05);
  color: white;
  font-size: 14px;
  outline: none;
  transition: border-color 0.3s;
}

.input-area input:focus {
  border-color: #667eea;
}

.input-area input::placeholder {
  color: rgba(255, 255, 255, 0.3);
}

.input-area button {
  padding: 10px 20px;
  border-radius: 20px;
  border: none;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
  font-size: 14px;
  cursor: pointer;
  transition: all 0.3s;
}

.input-area button:hover:not(:disabled) {
  transform: scale(1.05);
  box-shadow: 0 4px 12px rgba(102, 126, 234, 0.4);
}

.input-area button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.test-area {
  padding: 8px 16px;
  border-top: 1px solid rgba(255, 255, 255, 0.05);
}

.test-btn {
  width: 100%;
  padding: 8px;
  border-radius: 12px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.6);
  font-size: 12px;
  cursor: pointer;
  transition: all 0.3s;
}

.test-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.1);
  color: white;
}

.test-btn:disabled {
  opacity: 0.3;
  cursor: not-allowed;
}

/* 滚动条美化 */
.message-list::-webkit-scrollbar {
  width: 4px;
}

.message-list::-webkit-scrollbar-track {
  background: transparent;
}

.message-list::-webkit-scrollbar-thumb {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 2px;
}
</style>