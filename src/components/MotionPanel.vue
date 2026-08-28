<template>
  <div class="motion-panel">
    <button v-for="m in MOTIONS" :key="m.name" @click="emit('play', m.group, m.index)">
      {{ m.name }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { MOTIONS } from '../constants/live2d';

const emit = defineEmits<{
  play: [group: string, index?: number];
}>();
</script>

<style scoped>
.motion-panel {
  position: absolute;
  bottom: 10px;
  left: 50%;
  transform: translateX(-50%);
  display: flex;
  gap: 10px;
  z-index: 10;
}

.motion-panel button {
  padding: 8px 20px;
  border: none;
  border-radius: 6px;
  background: rgba(255, 255, 255, 0.2);
  color: #fff;
  font-size: 14px;
  cursor: pointer;
  transition: background 0.2s;
}

.motion-panel button:hover {
  background: rgba(255, 255, 255, 0.4);
}
</style>