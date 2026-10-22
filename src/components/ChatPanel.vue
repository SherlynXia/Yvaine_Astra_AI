<template>
  <div class="chat-panel" :class="{ expanded: isExpanded }">
    <!-- 展开/收起按钮 -->
    <button class="toggle-btn" @click="toggleExpand">
      <span v-if="isExpanded">✕</span>
      <span v-else>💬</span>
    </button>

    <!-- 聊天内容区 -->
    <div v-show="isExpanded" class="chat-content">
      <!-- 连接状态 + 用户选择 -->
      <div class="status-bar">
        <span class="status-dot" :class="{ connected: isConnected }"></span>
        <span class="status-text">{{ statusText }}</span>

        <!-- 🔥 用户选择 -->
        <div class="user-switcher" v-if="isConnected">
          <select
            :value="currentUser?.user_id || 'default'"
            @change="onUserChange"
            class="user-select"
          >
            <option
              v-for="u in users"
              :key="u.user_id"
              :value="u.user_id"
            >
              {{ u.name || u.user_id.slice(0, 6) }}
            </option>
          </select>
          <button class="user-add-btn" @click="promptCreateUser" title="新建用户">＋</button>
        </div>
      </div>

      <!-- 消息列表 -->
      <div class="message-list">
        <div v-if="history.length === 0" class="empty-hint">
          和 Yvaine 说点什么吧~
        </div>
        <template v-for="(msg, index) in history" :key="index">
          <div class="message" :class="msg.role">
            <div class="avatar">{{ msg.role === 'user' ? '👤' : '✨' }}</div>
            <div class="bubble-wrapper">
              <div class="bubble">
                <div class="text">{{ msg.text }}</div>
                <div v-if="msg.emotion" class="emotion-tag">{{ msg.emotion }}</div>
              </div>
              <!-- 🔥 评分按钮（只对 AI 消息显示） -->
              <div
                v-if="msg.role === 'yvaine' && msg.messageId"
                class="feedback-buttons"
              >
                <button
                  class="fb-btn"
                  :class="{ active: msg.feedback === 'good' }"
                  :disabled="msg.feedback === 'good' || msg.feedback === 'bad'"
                  @click="emit('feedback', msg.messageId!, 'good')"
                  title="回答不错"
                >👍</button>
                <button
                  class="fb-btn"
                  :class="{ active: msg.feedback === 'bad' }"
                  :disabled="msg.feedback === 'good' || msg.feedback === 'bad'"
                  @click="emit('feedback', msg.messageId!, 'bad')"
                  title="回答不好"
                >👎</button>
              </div>
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
  history: {
    role: 'user' | 'yvaine';
    text: string;
    emotion?: string;
    messageId?: string;
    feedback?: 'good' | 'bad' | null;
  }[];
  users: { user_id: string; name: string }[];
  currentUser: { user_id: string; name: string } | null;
  isConnected: boolean;
  isConnecting: boolean;
  isTyping: boolean;
}>();

const emit = defineEmits<{
  switchUser: [userId: string];
  createUser: [name: string];
  send: [text: string];
  testTTS: [];
  feedback: [messageId: string, rating: 'good' | 'bad'];
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

function onUserChange(e: Event) {
  const target = e.target as HTMLSelectElement;
  emit('switchUser', target.value);
}

function promptCreateUser() {
  const name = window.prompt('新用户的名字：');
  if (name && name.trim()) {
    emit('createUser', name.trim());
  }
}

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

.user-switcher {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 4px;
}

.user-select {
  background: rgba(255, 255, 255, 0.05);
  color: rgba(255, 255, 255, 0.8);
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 6px;
  padding: 2px 6px;
  font-size: 11px;
  outline: none;
  cursor: pointer;
  max-width: 90px;
}

.user-select:focus {
  border-color: #667eea;
}

.user-add-btn {
  width: 20px;
  height: 20px;
  border-radius: 50%;
  border: 1px solid rgba(255, 255, 255, 0.15);
  background: transparent;
  color: rgba(255, 255, 255, 0.6);
  font-size: 13px;
  line-height: 1;
  cursor: pointer;
  transition: all 0.2s;
}

.user-add-btn:hover {
  border-color: rgba(100, 200, 255, 0.6);
  color: rgba(100, 200, 255, 0.9);
}

.bubble-wrapper {
  display: flex;
  flex-direction: column;
  max-width: 240px;
}

.message.user .bubble-wrapper {
  align-items: flex-end;
}

.bubble {
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

/* 🔥 评分按钮 */
.feedback-buttons {
  display: flex;
  gap: 4px;
  margin-top: 3px;
  padding-left: 4px;
}

.message.user .feedback-buttons {
  justify-content: flex-end;
  padding-right: 4px;
}

.fb-btn {
  background: transparent;
  border: 1px solid rgba(255, 255, 255, 0.15);
  border-radius: 6px;
  padding: 1px 7px;
  cursor: pointer;
  font-size: 12px;
  line-height: 1.4;
  opacity: 0.4;
  transition: all 0.2s ease;
}

.fb-btn:hover:not(:disabled) {
  opacity: 1;
  border-color: rgba(255, 255, 255, 0.5);
  transform: scale(1.05);
}

.fb-btn.active {
  opacity: 1;
  background: rgba(100, 200, 255, 0.2);
  border-color: rgba(100, 200, 255, 0.6);
  box-shadow: 0 0 6px rgba(100, 200, 255, 0.3);
}

.fb-btn:disabled {
  cursor: default;
  opacity: 0.25;
}

.fb-btn.active:disabled {
  opacity: 1;
}
</style>