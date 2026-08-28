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
    <div class="hint">点击模型触发动作，鼠标移动控制视线</div>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onBeforeUnmount } from 'vue';
import { useLive2D } from '../composables/useLive2D';
import ExpressionPanel from './ExpressionPanel.vue';
import MotionPanel from './MotionPanel.vue';

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
  destroy,
} = useLive2D();

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