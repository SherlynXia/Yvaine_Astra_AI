<template>
  <div class="expression-panel">
    <!-- 面部 -->
    <div class="category">
      <span class="label">面部</span>
      <button
        v-for="exp in EXPRESSIONS_FACIAL"
        :key="exp.name"
        @click="emit('set', 'facial', exp.id)"
        :class="{ active: currentFacial === exp.id }"
      >
        {{ exp.name }}
      </button>
    </div>

    <!-- 眼睛 -->
    <div class="category">
      <span class="label">眼睛</span>
      <button
        v-for="exp in EXPRESSIONS_EYES"
        :key="exp.name"
        @click="emit('set', 'eyes', exp.id)"
        :class="{ active: currentEyes === exp.id }"
      >
        {{ exp.name }}
      </button>
    </div>

    <!-- 嘴巴 -->
    <div class="category">
      <span class="label">嘴巴</span>
      <button
        v-for="exp in EXPRESSIONS_MOUTH"
        :key="exp.name"
        @click="emit('set', 'mouth', exp.id)"
        :class="{ active: currentMouth === exp.id }"
      >
        {{ exp.name }}
      </button>
    </div>

    <!-- 发型 -->
    <div class="category">
      <span class="label">发型</span>
      <button
        v-for="exp in EXPRESSIONS_HAIR"
        :key="exp.name"
        @click="emit('set', 'hair', exp.id)"
        :class="{ active: currentHair === exp.id }"
      >
        {{ exp.name }}
      </button>
    </div>

    <!-- 饰品（多选） -->
    <div class="category">
      <span class="label">饰品</span>
      <button
        v-for="exp in EXPRESSIONS_ACCESSORIES"
        :key="exp.name"
        @click="emit('set', 'accessory', exp.id)"
        :class="{ active: currentAccessories.has(exp.id) }"
      >
        {{ exp.name }}
      </button>
    </div>

    <button @click="emit('clear')" class="clear-btn">清除全部</button>
  </div>
</template>

<script setup lang="ts">
import {
  EXPRESSIONS_FACIAL,
  EXPRESSIONS_EYES,
  EXPRESSIONS_MOUTH,
  EXPRESSIONS_HAIR,
  EXPRESSIONS_ACCESSORIES,
} from '../constants/live2d';

defineProps<{
  currentFacial: string;
  currentEyes: string;
  currentMouth: string;
  currentHair: string;
  currentAccessories: Set<string>;
}>();

const emit = defineEmits<{
  set: [category: string, id: string];
  clear: [];
}>();
</script>

<style scoped>
.expression-panel {
  position: absolute;
  top: 10px;
  left: 10px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  max-width: 320px;
  z-index: 10;
  background: rgba(0, 0, 0, 0.3);
  padding: 10px;
  border-radius: 8px;
}

.category {
  display: flex;
  flex-wrap: wrap;
  gap: 4px;
  align-items: center;
}

.label {
  color: rgba(255, 255, 255, 0.7);
  font-size: 11px;
  width: 40px;
  flex-shrink: 0;
}

.expression-panel button {
  padding: 4px 8px;
  border: none;
  border-radius: 4px;
  background: rgba(255, 255, 255, 0.15);
  color: #fff;
  font-size: 11px;
  cursor: pointer;
  transition: background 0.2s;
}

.expression-panel button:hover {
  background: rgba(255, 255, 255, 0.3);
}

.expression-panel button.active {
  background: rgba(100, 180, 255, 0.6);
}

.expression-panel .clear-btn {
  background: rgba(255, 100, 100, 0.4);
  margin-top: 4px;
}

.expression-panel .clear-btn:hover {
  background: rgba(255, 100, 100, 0.6);
}
</style>