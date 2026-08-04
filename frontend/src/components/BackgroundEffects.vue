<template>
  <div class="bg-effects" :class="{ dark: isDark }">
    <div v-for="i in particleCount" :key="i" class="particle" :style="particleStyle(i)"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'

const isDark = ref(false)
const particleCount = 30

function particleStyle(i) {
  const size = 2 + Math.random() * 4
  const left = Math.random() * 100
  const delay = Math.random() * 8
  const duration = 6 + Math.random() * 8
  const drift = -30 + Math.random() * 60
  return {
    width: `${size}px`,
    height: `${size}px`,
    left: `${left}%`,
    bottom: '-10px',
    animationDelay: `${delay}s`,
    animationDuration: `${duration}s`,
    '--drift': `${drift}px`,
  }
}

const observer = new MutationObserver(() => {
  isDark.value = document.documentElement.getAttribute('data-theme') === 'dark'
})

onMounted(() => {
  isDark.value = document.documentElement.getAttribute('data-theme') === 'dark'
  observer.observe(document.documentElement, { attributes: true, attributeFilter: ['data-theme'] })
})

onUnmounted(() => observer.disconnect())
</script>

<style scoped>
.bg-effects {
  position: fixed;
  inset: 0;
  z-index: -5;
  pointer-events: none;
  overflow: hidden;
}

.particle {
  position: absolute;
  border-radius: 50%;
  opacity: 0;
  animation: particleFloat linear infinite;
}

.bg-effects:not(.dark) .particle {
  background: rgba(161, 140, 209, 0.15);
  box-shadow: 0 0 6px rgba(161, 140, 209, 0.1);
}

.bg-effects.dark .particle {
  background: rgba(99, 102, 241, 0.2);
  box-shadow: 0 0 8px rgba(99, 102, 241, 0.15);
}

@keyframes particleFloat {
  0% {
    opacity: 0;
    transform: translateY(0) translateX(0) scale(0.5);
  }
  10% {
    opacity: 1;
  }
  90% {
    opacity: 0.6;
  }
  100% {
    opacity: 0;
    transform: translateY(-100vh) translateX(var(--drift)) scale(1.2);
  }
}
</style>
