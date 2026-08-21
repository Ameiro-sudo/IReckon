<template>
  <router-view v-if="isBare" />
  <div v-else class="app-shell">
    <div v-if="mobileSidebarOpen" class="mobile-overlay" @click="mobileSidebarOpen = false"></div>

    <aside class="sidebar" :class="{ open: mobileSidebarOpen }" aria-label="主导航侧边栏">
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
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          </span>
          聊天
        </router-link>
        <router-link to="/tasks" class="nav-item" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M8 6h13M8 12h13M8 18h13"/><path d="M3 6h.01M3 12h.01M3 18h.01"/></svg>
          </span>
          任务
          <span v-if="taskStore.activeCount > 0" class="nav-count">{{ taskStore.activeCount }}</span>
        </router-link>
        <router-link to="/dashboard" class="nav-item" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="9" rx="1.5"/><rect x="14" y="3" width="7" height="5" rx="1.5"/><rect x="14" y="12" width="7" height="9" rx="1.5"/><rect x="3" y="16" width="7" height="5" rx="1.5"/></svg>
          </span>
          仪表盘
        </router-link>

        <div class="nav-group-label">监控</div>
        <router-link to="/logs" class="nav-item" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
          </span>
          系统日志
        </router-link>
        <router-link to="/artifacts" class="nav-item" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
          </span>
          交付产物
        </router-link>

        <div class="nav-group-label">管理</div>
        <router-link to="/ai-instances" class="nav-item" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg>
          </span>
          AI 实例
        </router-link>
        <router-link to="/self-improve" class="nav-item" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z"/><circle cx="12" cy="12" r="3"/></svg>
          </span>
          自我进化
        </router-link>
        <router-link to="/settings" class="nav-item" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          </span>
          设置
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <div class="sidebar-status">
          <span class="status-dot" :class="backendOnline ? 'on' : 'off'"></span>
          <span class="text-sm" style="flex: 1;">{{ backendOnline ? '后端在线' : '后端离线' }}</span>
          <span class="footer-version">v{{ version }}</span>
        </div>
        <button class="btn btn-secondary btn-block" @click="toggleTheme" :aria-label="isDark ? '切换到浅色模式' : '切换到深色模式'">
          <svg v-if="isDark" width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></svg>
          <svg v-else width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/></svg>
          {{ isDark ? '浅色模式' : '深色模式' }}
        </button>
      </div>
    </aside>

    <main class="app-main">
      <div class="mobile-topbar">
        <button class="btn btn-ghost btn-icon" @click="mobileSidebarOpen = true" aria-label="打开导航菜单">
          <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" aria-hidden="true"><line x1="3" y1="6" x2="21" y2="6"/><line x1="3" y1="12" x2="21" y2="12"/><line x1="3" y1="18" x2="21" y2="18"/></svg>
        </button>
        <span class="mobile-title">IReckon</span>
      </div>

      <router-view />
    </main>

    <ToastContainer />
  </div>
</template>

<script setup>
import {computed, onMounted, onUnmounted, ref} from 'vue'
import {useRoute} from 'vue-router'
import {useTaskStore} from './stores/taskStore.js'
import {healthAPI} from './api/index.js'
import ToastContainer from './components/ToastContainer.vue'

const route = useRoute()
const taskStore = useTaskStore()
const isDark = ref(false)
const version = ref('—')
const backendOnline = ref(true)
const mobileSidebarOpen = ref(false)
let healthTimer = null

const isBare = computed(() => Boolean(route.meta?.bare))

const toggleTheme = () => {
  isDark.value = !isDark.value
  document.documentElement.setAttribute('data-theme', isDark.value ? 'dark' : 'light')
  localStorage.setItem('theme', isDark.value ? 'dark' : 'light')
}

async function checkHealth() {
  try {
    const res = await healthAPI.check()
    version.value = res.data?.version || version.value
    backendOnline.value = true
  } catch {
    backendOnline.value = false
  }
}

onMounted(async () => {
  isDark.value = document.documentElement.getAttribute('data-theme') === 'dark'
  await checkHealth()
  healthTimer = setInterval(checkHealth, 15000)
  if (isBare.value) return
  // 任务列表初始加载一次；后续轮询统一由 taskStore.startPolling 管理，
  // 避免双定时器导致请求翻倍且 stopPolling 失效
  await taskStore.fetchTasks()
})

onUnmounted(() => {
  if (healthTimer) clearInterval(healthTimer)
})
</script>
