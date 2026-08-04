<template>
  <div class="app-layout">
    <SplashScreen />
    <ClickEffect />
    <BackgroundEffects />
    <GlobalToolbox />

    <!-- Mobile overlay -->
    <div v-if="mobileSidebarOpen" class="mobile-overlay" @click="mobileSidebarOpen = false"></div>

    <!-- Hamburger button (mobile) -->
    <button class="hamburger" @click="mobileSidebarOpen = !mobileSidebarOpen" :class="{ open: mobileSidebarOpen }">
      <span></span>
      <span></span>
      <span></span>
    </button>

    <aside class="sidebar glass" :class="{ 'sidebar-open': mobileSidebarOpen }">
      <div class="sidebar-header">
        <div class="logo">
          <div class="logo-icon">I</div>
          <div class="logo-text">
            <span class="logo-title">IReckon</span>
            <span class="logo-sub">AI Factory</span>
          </div>
        </div>
      </div>

      <nav class="nav-list">
        <router-link to="/" class="nav-item" :class="{ active: $route.path === '/' }" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          </span>
          <span class="nav-label">聊天</span>
        </router-link>

        <router-link to="/tasks" class="nav-item" :class="{ active: $route.path === '/tasks' }" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
          </span>
          <span class="nav-label">任务</span>
        </router-link>

        <router-link to="/dashboard" class="nav-item" :class="{ active: $route.path === '/dashboard' }" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="14" y="14" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/></svg>
          </span>
          <span class="nav-label">仪表盘</span>
        </router-link>

        <router-link to="/ai-instances" class="nav-item" :class="{ active: $route.path === '/ai-instances' }" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 2a10 10 0 0 1 10 10c0 2.5-1 4.8-2.6 6.5"/><path d="M12 2a10 10 0 0 0-7.4 16.5"/><circle cx="12" cy="12" r="3"/></svg>
          </span>
          <span class="nav-label">AI 实例</span>
        </router-link>

        <router-link to="/self-improve" class="nav-item" :class="{ active: $route.path === '/self-improve' }" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/></svg>
          </span>
          <span class="nav-label">自我进化</span>
        </router-link>

        <router-link to="/settings" class="nav-item" :class="{ active: $route.path === '/settings' }" @click="mobileSidebarOpen = false">
          <span class="nav-icon">
            <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          </span>
          <span class="nav-label">设置</span>
        </router-link>
      </nav>

      <div class="sidebar-footer">
        <button class="sidebar-theme-btn" @click="toggleTheme" :title="isDark ? '切换浅色' : '切换深色'">
          <svg v-if="isDark" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <circle cx="12" cy="12" r="5"/><path d="M12 1v2M12 21v2M4.22 4.22l1.42 1.42M18.36 18.36l1.42 1.42M1 12h2M21 12h2M4.22 19.78l1.42-1.42M18.36 5.64l1.42-1.42"/>
          </svg>
          <svg v-else width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
            <path d="M21 12.79A9 9 0 1 1 11.21 3 7 7 0 0 0 21 12.79z"/>
          </svg>
          <span>{{ isDark ? '浅色' : '深色' }}</span>
        </button>
        <div class="update-badge" v-if="updateAvailable" @click="router.push('/settings'); mobileSidebarOpen = false">
          <span class="update-dot"></span>
          <span>新版本可用</span>
        </div>
        <div class="version-info">{{ version }}</div>
      </div>
    </aside>

    <main class="main-content">
      <PageTransition />
    </main>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { healthAPI } from './api/index.js'

import SplashScreen from './components/SplashScreen.vue'
import ClickEffect from './components/ClickEffect.vue'
import BackgroundEffects from './components/BackgroundEffects.vue'
import GlobalToolbox from './components/GlobalToolbox.vue'
import PageTransition from './components/PageTransition.vue'

const router = useRouter()
const version = ref('v1.0.0')
const updateAvailable = ref(false)
const isDark = ref(false)
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
    version.value = res.data?.version || 'v1.0.0'
    updateAvailable.value = res.data?.update_available || false
  } catch {
  }
})
</script>

<style scoped>
.app-layout {
  display: flex;
  height: 100vh;
  background: transparent;
}

/* Hamburger */
.hamburger {
  display: none;
  position: fixed;
  top: 12px;
  left: 12px;
  z-index: 1001;
  width: 36px;
  height: 36px;
  border-radius: 10px;
  background: var(--bg-glass);
  backdrop-filter: blur(12px);
  -webkit-backdrop-filter: blur(12px);
  border: 1px solid var(--glass-border);
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 4px;
  cursor: pointer;
  transition: all 0.2s ease;
}

.hamburger span {
  display: block;
  width: 18px;
  height: 2px;
  border-radius: 2px;
  background: var(--text-primary);
  transition: all 0.3s ease;
}

.hamburger.open span:nth-child(1) {
  transform: rotate(45deg) translate(4px, 4px);
}

.hamburger.open span:nth-child(2) {
  opacity: 0;
}

.hamburger.open span:nth-child(3) {
  transform: rotate(-45deg) translate(4px, -4px);
}

/* Mobile overlay */
.mobile-overlay {
  display: none;
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.4);
  z-index: 999;
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
}

.sidebar {
  width: 220px;
  flex-shrink: 0;
  backdrop-filter: blur(24px) saturate(200%);
  -webkit-backdrop-filter: blur(24px) saturate(200%);
  border-right: 1px solid var(--glass-border);
  display: flex;
  flex-direction: column;
  padding: 0;
  z-index: 10;
  transition: transform 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.sidebar-header {
  padding: 20px 20px 16px;
  border-bottom: 1px solid var(--border-light);
}

.logo {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo-icon {
  width: 38px;
  height: 38px;
  border-radius: 12px;
  background: linear-gradient(135deg, #a855f7 0%, #3c96ca 100%);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
  font-weight: 800;
  color: white;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(161, 140, 209, 0.3);
}

.logo-text {
  display: flex;
  flex-direction: column;
}

.logo-title {
  font-size: 16px;
  font-weight: 700;
  color: var(--text-primary);
  line-height: 1.2;
}

.logo-sub {
  font-size: 11px;
  color: var(--text-muted);
}

.nav-list {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 12px 10px;
  overflow-y: auto;
}

.nav-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px 14px;
  border-radius: var(--radius-md);
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 13px;
  font-weight: 500;
  transition: all 0.2s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.nav-item::before {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%) scaleY(0);
  width: 3px;
  height: 20px;
  border-radius: 0 3px 3px 0;
  background: var(--primary);
  transition: transform 0.2s cubic-bezier(0.4, 0, 0.2, 1);
}

.nav-item:hover {
  background: var(--bg-hover);
  color: var(--text-primary);
}

.nav-item:hover .nav-icon {
  color: var(--primary);
  transform: translateX(2px);
}

.nav-item.active {
  background: rgba(60, 150, 202, 0.08);
  color: var(--primary);
}

.nav-item.active::before {
  transform: translateY(-50%) scaleY(1);
}

.nav-item.active .nav-icon {
  color: var(--primary);
  transform: translateX(2px);
}

.nav-icon {
  display: flex;
  align-items: center;
  justify-content: center;
  width: 20px;
  height: 20px;
  flex-shrink: 0;
  transition: transform 0.2s ease;
}

.sidebar-footer {
  padding: 12px 16px;
  border-top: 1px solid var(--border-light);
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.sidebar-theme-btn {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  width: 100%;
  height: 34px;
  border-radius: var(--radius-md);
  background: var(--bg-glass);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid var(--glass-border-subtle);
  color: var(--text-secondary);
  cursor: pointer;
  transition: all 0.2s ease;
  font-size: 12px;
}

.sidebar-theme-btn:hover {
  background: var(--bg-hover);
  color: var(--primary);
  border-color: var(--primary);
}

.update-badge {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  padding: 6px 10px;
  border-radius: var(--radius-sm);
  font-size: 11px;
  color: var(--warning);
  cursor: pointer;
  transition: background 0.15s;
}

.update-badge:hover {
  background: var(--warning-bg);
}

.update-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--warning);
  animation: pulse 2s infinite;
}

@keyframes pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.4; }
}

.version-info {
  font-size: 11px;
  color: var(--text-muted);
  text-align: center;
}

.main-content {
  flex: 1;
  overflow: hidden;
  background: transparent;
  position: relative;
}

/* Mobile responsive */
@media (max-width: 768px) {
  .hamburger {
    display: flex;
  }

  .mobile-overlay {
    display: block;
  }

  .sidebar {
    position: fixed;
    top: 0;
    left: 0;
    bottom: 0;
    z-index: 1000;
    transform: translateX(-100%);
    border-right: none;
    box-shadow: 4px 0 24px rgba(0, 0, 0, 0.15);
  }

  .sidebar.sidebar-open {
    transform: translateX(0);
  }

  .main-content {
    margin-left: 0;
    padding-top: 0;
  }
}
</style>
