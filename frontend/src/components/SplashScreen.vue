<template>
  <div v-if="visible" class="splash-overlay" :class="{ 'splash-hide': hiding }">
    <div class="splash-content">
      <div class="splash-logo-ring">
        <div class="splash-logo">I</div>
      </div>
      <h1 class="splash-title">IReckon</h1>
      <p class="splash-subtitle">俺寻思 AI 工厂</p>
      <div class="splash-bar">
        <div class="splash-bar-fill"></div>
      </div>
      <p class="splash-status">INITIALIZING SYSTEM</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'

const visible = ref(false)
const hiding = ref(false)

onMounted(() => {
  const seen = sessionStorage.getItem('ireckon-splash')
  if (seen) return
  visible.value = true
  setTimeout(() => {
    hiding.value = true
    setTimeout(() => {
      visible.value = false
      sessionStorage.setItem('ireckon-splash', '1')
    }, 600)
  }, 2200)
})
</script>

<style scoped>
.splash-overlay {
  position: fixed;
  inset: 0;
  z-index: 100000;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #0f172a 0%, #1e293b 50%, #2b3f67 100%);
  transition: opacity 0.6s ease, backdrop-filter 0.6s ease;
}

.splash-hide {
  opacity: 0;
  backdrop-filter: blur(20px);
}

.splash-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 12px;
}

.splash-logo-ring {
  width: 80px;
  height: 80px;
  border-radius: 50%;
  background: linear-gradient(135deg, #a855f7, #c084fc, #3c96ca, #60a5fa);
  background-size: 300% 300%;
  animation: splashRotate 2s linear infinite;
  display: flex;
  align-items: center;
  justify-content: center;
  margin-bottom: 8px;
}

.splash-logo {
  width: 68px;
  height: 68px;
  border-radius: 50%;
  background: #0f172a;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 32px;
  font-weight: 800;
  color: white;
  font-family: 'Inter', sans-serif;
}

.splash-title {
  font-size: 28px;
  font-weight: 700;
  color: white;
  font-family: 'Inter', sans-serif;
  letter-spacing: 2px;
}

.splash-subtitle {
  font-size: 13px;
  color: rgba(255, 255, 255, 0.5);
  font-family: 'Inter', sans-serif;
}

.splash-bar {
  width: 200px;
  height: 3px;
  background: rgba(255, 255, 255, 0.1);
  border-radius: 2px;
  overflow: hidden;
  margin-top: 8px;
}

.splash-bar-fill {
  height: 100%;
  width: 30%;
  background: linear-gradient(90deg, #a855f7, #3c96ca, #60a5fa);
  border-radius: 2px;
  animation: splashProgress 1.8s ease-in-out infinite;
}

.splash-status {
  font-size: 11px;
  color: rgba(255, 255, 255, 0.3);
  font-family: monospace;
  letter-spacing: 2px;
}

@keyframes splashRotate {
  0% { background-position: 0% 50%; }
  100% { background-position: 300% 50%; }
}

@keyframes splashProgress {
  0% { transform: translateX(-100%); width: 30%; }
  50% { width: 60%; }
  100% { transform: translateX(400%); width: 30%; }
}
</style>
