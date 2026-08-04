<template>
  <div class="toolbox-container">
    <Teleport to="body">
      <Transition name="toolbox">
        <div v-if="expanded" class="toolbox-panel glass" @click.self="expanded = false">
          <div class="toolbox-item" @click="toggleTheme" title="切换主题">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
              <circle v-if="isDark" cx="12" cy="12" r="5"/><path v-if="isDark" d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
              <path v-else d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
            </svg>
          </div>
          <div class="toolbox-item" @click="scrollToTop" title="回到顶部">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="18 15 12 9 6 15"/></svg>
          </div>
          <div class="toolbox-item" @click="refresh" title="刷新">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
          </div>
        </div>
      </Transition>
    </Teleport>

    <button class="toolbox-trigger glass" @click="expanded = !expanded" :title="expanded ? '关闭' : '工具箱'">
      <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
        <circle cx="12" cy="12" r="3"/>
        <path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/>
      </svg>
    </button>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'

const expanded = ref(false)
const isDark = ref(false)

onMounted(() => {
  isDark.value = document.documentElement.getAttribute('data-theme') === 'dark'
})

function toggleTheme() {
  isDark.value = !isDark.value
  document.documentElement.setAttribute('data-theme', isDark.value ? 'dark' : 'light')
  localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
}

function scrollToTop() {
  const main = document.querySelector('.main-content')
  if (main) main.scrollTop = 0
}

function refresh() {
  window.location.reload()
}
</script>

<style scoped>
.toolbox-container {
  position: fixed;
  bottom: 24px;
  right: 24px;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
}

.toolbox-trigger {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  border: 1px solid var(--glass-border);
  color: var(--text-secondary);
  transition: all 0.2s ease;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.15);
}

.toolbox-trigger:hover {
  color: var(--primary);
  transform: scale(1.05);
  box-shadow: 0 6px 24px rgba(60, 150, 202, 0.25);
}

@media (max-width: 768px) {
  .toolbox-container { bottom: 16px !important; right: 16px !important; }
  .toolbox-trigger { width: 38px !important; height: 38px !important; }
  .toolbox-panel { padding: 4px 6px !important; }
  .toolbox-item { width: 30px !important; height: 30px !important; }
}

.toolbox-panel {
  display: flex;
  gap: 4px;
  padding: 6px 8px;
  border-radius: 24px;
  border: 1px solid var(--glass-border);
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.12);
}

.toolbox-item {
  width: 34px;
  height: 34px;
  border-radius: 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  color: var(--text-secondary);
  transition: all 0.2s ease;
}

.toolbox-item:hover {
  background: var(--bg-hover);
  color: var(--primary);
}

.toolbox-enter-active,
.toolbox-leave-active {
  transition: all 0.2s ease;
}

.toolbox-enter-from,
.toolbox-leave-to {
  opacity: 0;
  transform: translateY(8px) scale(0.9);
}
</style>
