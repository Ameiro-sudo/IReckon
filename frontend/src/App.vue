<template>
  <router-view v-if="isBare" />
  <div v-else class="app-shell">
    <div v-if="mobileSidebarOpen" class="fixed inset-0 z-30 bg-black/40 md:hidden" @click="mobileSidebarOpen = false"></div>

    <aside
      class="fixed inset-y-0 left-0 z-40 flex w-[260px] shrink-0 flex-col border-r border-line-strong bg-housing transition-transform duration-200 md:static md:z-auto md:w-[236px] md:translate-x-0"
      :class="mobileSidebarOpen ? 'translate-x-0 shadow-lg' : '-translate-x-full'"
      aria-label="主导航侧边栏"
    >
      <div class="flex items-center gap-2.5 border-b border-line px-4 pt-4 pb-3.5">
        <div class="brand-mark">I</div>
        <div>
          <div class="brand-name">IReckon</div>
          <div class="brand-sub">Multi-Agent AI Factory</div>
        </div>
      </div>

      <nav class="flex min-h-0 flex-1 flex-col overflow-y-auto px-2.5 pb-2">
        <template v-for="group in NAV" :key="group.label">
          <div class="nav-group-label">{{ group.label }}</div>
          <router-link
            v-for="item in group.items"
            :key="item.to"
            :to="item.to"
            class="nav-item"
            :title="item.label + '（Alt+' + item.hotkey + '）'"
            @click="mobileSidebarOpen = false"
          >
            <span class="flex w-[15px] shrink-0 justify-center opacity-85">
              <AppIcon :name="item.icon" :size="15" />
            </span>
            {{ item.label }}
            <span v-if="item.badge && taskStore.activeCount > 0" class="nav-count">{{ taskStore.activeCount }}</span>
          </router-link>
        </template>
      </nav>

      <div class="flex flex-col gap-1.5 border-t border-line p-2.5">
        <div class="flex items-center gap-2 rounded-md border border-line bg-subtle px-2.5 py-[7px] text-xs text-ink-2">
          <span class="lamp" :class="backendOnline ? 'lamp-ok' : 'lamp-bad'"></span>
          <span class="flex-1">{{ backendOnline ? '后端在线' : '后端离线' }}</span>
          <span class="ml-1 font-mono text-[11px] text-ink-3">v{{ version }}</span>
        </div>
        <button class="btn btn-secondary btn-block py-1.5! text-xs!" @click="toggleTheme" :aria-label="isDark ? '切换到浅色模式' : '切换到深色模式'">
          <AppIcon :name="isDark ? 'sun' : 'moon'" :size="13" />
          {{ isDark ? '浅色模式' : '深色模式' }}
        </button>
      </div>
    </aside>

    <main class="app-main">
      <div class="sticky top-0 z-20 flex items-center gap-2 border-b border-line bg-housing px-3 py-2 md:hidden">
        <button class="btn btn-ghost btn-icon" @click="mobileSidebarOpen = true" aria-label="打开导航菜单">
          <AppIcon name="menu" :size="18" />
        </button>
        <span class="font-display text-sm font-bold tracking-wide uppercase">IReckon</span>
      </div>

      <router-view />
    </main>

    <ToastContainer />
    <ConfirmDialog />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { useTaskStore } from './stores/taskStore.js'
import { healthAPI } from './api/index.js'
import ToastContainer from './components/ToastContainer.vue'
import ConfirmDialog from './components/ui/ConfirmDialog.vue'
import AppIcon from './components/ui/AppIcon.vue'

const NAV = [
  {
    label: '工作台',
    items: [
      { to: '/', icon: 'chat', label: '聊天', hotkey: 1 },
      { to: '/tasks', icon: 'list', label: '任务', badge: true, hotkey: 2 },
      { to: '/dashboard', icon: 'gauge', label: '仪表盘', hotkey: 3 }
    ]
  },
  {
    label: '监控',
    items: [
      { to: '/logs', icon: 'zap', label: '系统日志', hotkey: 4 },
      { to: '/artifacts', icon: 'file', label: '交付产物', hotkey: 5 }
    ]
  },
  {
    label: '管理',
    items: [
      { to: '/ai-instances', icon: 'cpu', label: 'AI 实例', hotkey: 6 },
      { to: '/self-improve', icon: 'eye', label: '自我进化', hotkey: 7 },
      { to: '/settings', icon: 'gear', label: '设置', hotkey: 8 }
    ]
  }
]
const flatNav = NAV.flatMap(g => g.items)

const route = useRoute()
const router = useRouter()
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
  window.addEventListener('keydown', onGlobalKeydown)
  if (isBare.value) return
  // 任务列表初始加载一次；后续轮询统一由 taskStore.startPolling 管理，
  // 避免双定时器导致请求翻倍且 stopPolling 失效
  await taskStore.fetchTasks()
})

onUnmounted(() => {
  if (healthTimer) clearInterval(healthTimer)
  window.removeEventListener('keydown', onGlobalKeydown)
})

/* Alt+数字 快捷跳转（输入框聚焦时失效，登录页除外） */
function onGlobalKeydown(e) {
  if (!e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return
  const idx = Number(e.key) - 1
  if (!(idx >= 0 && idx < flatNav.length)) return
  const el = e.target
  if (el && el.closest && el.closest('input, textarea, select, [contenteditable="true"]')) return
  if (isBare.value) return
  e.preventDefault()
  mobileSidebarOpen.value = false
  router.push(flatNav[idx].to)
}
</script>
