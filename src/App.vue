<template>
  <Live2DCanvas />
</template>

<script setup lang="ts">
import Live2DCanvas from './components/Live2DCanvas.vue';
</script>

<style>
* { margin: 0; padding: 0; }
html, body, #app {
  width: 100%;
  height: 100%;
  overflow: hidden;
}
</style>