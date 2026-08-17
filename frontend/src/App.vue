<template>
  <div class="app-shell">
    <div v-if="mobileSidebarOpen" class="mobile-overlay" @click="mobileSidebarOpen = false"></div>

    <aside class="sidebar" :class="{ open: mobileSidebarOpen }">
      <div class="sidebar-brand">
        <div class="brand-mark">I</div>
        <div>
          <div class="brand-name">IReckon</div>
          <div class="brand-sub">Multi-Agent AI Factory</div>
        </div>
      </div>

      <nav class="sidebar-nav">
        <div class="nav-group-label">工作台</div>
        <router-link to="/" class="nav-item" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          </span>
          聊天
        </router-link>
        <router-link to="/tasks" class="nav-item" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M3 6h18M3 12h18M3 18h12"/></svg>
          </span>
          任务
          <span v-if="activeCount > 0" class="nav-count">{{ activeCount }}</span>
        </router-link>
        <router-link to="/dashboard" class="nav-item" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="9" rx="1"/><rect x="14" y="3" width="7" height="5" rx="1"/><rect x="14" y="12" width="7" height="9" rx="1"/><rect x="3" y="16" width="7" height="5" rx="1"/></svg>
          </span>
          仪表盘
        </router-link>

        <div class="nav-group-label">监控</div>
        <router-link to="/logs" class="nav-item" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 17l6-6-6-6"/><path d="M12 19h8"/></svg>
          </span>
          系统日志
        </router-link>
        <router-link to="/artifacts" class="nav-item" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          </span>
          交付产物
        </router-link>

        <div class="nav-group-label">管理</div>
        <router-link to="/ai-instances" class="nav-item" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a10 10 0 0 1 10 10c0 2.5-1 4.8-2.6 6.5"/><path d="M12 2a10 10 0 0 0-7.4 16.5"/><circle cx="12" cy="12" r="3"/></svg>
          </span>
          AI 实例
        </router-link>
        <router-link to="/self-improve" class="nav-item" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/></svg>
          </span>
          自我进化
        </router-link>
        <router-link to="/settings" class="nav-item" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          </span>
          设置
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <button class="btn btn-ghost btn-sm" @click="toggleTheme">
          <svg v-if="isDark" width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
          <svg v-else width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
          {{ isDark ? '浅色模式' : '深色模式' }}
        </button>
        <span class="footer-version">v{{ version }}</span>
      </div>
    </aside>

    <main class="app-main">
      <div class="mobile-topbar">
        <button class="btn btn-ghost btn-icon" @click="mobileSidebarOpen = true">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
        </button>
        <span class="mobile-title">IReckon</span>
      </div>

      <router-view />
    </main>

    <ToastContainer />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useTaskStore } from './stores/taskStore.js'
import { healthAPI } from './api/index.js'
import ToastContainer from './components/ToastContainer.vue'

const taskStore = useTaskStore()
const activeCount = ref(0)
const isDark = ref(false)
const version = ref('—')
const mobileSidebarOpen = ref(false)

const toggleTheme = () => {
  isDark.value = !isDark.value
  document.documentElement.setAttribute('data-theme', isDark.value ? 'dark' : 'light')
  localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
}

onMounted(async () => {
  const savedTheme = localStorage.getItem('theme')
  if (savedTheme === 'dark' || (!savedTheme && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
    isDark.value = true
    document.documentElement.setAttribute('data-theme', 'dark')
  }
  try {
    const res = await healthAPI.check()
    version.value = res.data?.version || '—'
  } catch {
    /* offline */
  }
  const refresh = async () => {
    await taskStore.fetchTasks()
    activeCount.value = taskStore.activeCount
  }
  await refresh()
  setInterval(refresh, 10000)
})
</script>

<style scoped>
.mobile-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: 29;
}

.mobile-topbar {
  display: none;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-surface);
  position: sticky;
  top: 0;
  z-index: 20;
}

.mobile-title {
  font-weight: 700;
  font-size: 14px;
}

.nav-count {
  margin-left: auto;
  min-width: 18px;
  height: 18px;
  padding: 0 5px;
  border-radius: 9px;
  background: var(--accent);
  color: #fff;
  font-size: 10px;
  font-weight: 700;
  display: flex;
  align-items: center;
  justify-content: center;
}

@media (max-width: 768px) {
  .mobile-overlay { display: block; }
  .mobile-topbar { display: flex; }
}
</style>
