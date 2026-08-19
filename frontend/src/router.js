import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Chat',
    meta: { title: '聊天' },
    component: () => import('./views/ChatView.vue')
  },
  {
    path: '/tasks',
    name: 'Tasks',
    meta: { title: '任务' },
    component: () => import('./views/TasksView.vue')
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    meta: { title: '仪表盘' },
    component: () => import('./views/DashboardView.vue')
  },
  {
    path: '/logs',
    name: 'Logs',
    meta: { title: '系统日志' },
    component: () => import('./views/LogsView.vue')
  },
  {
    path: '/artifacts',
    name: 'Artifacts',
    meta: { title: '交付产物' },
    component: () => import('./views/ArtifactsView.vue')
  },
  {
    path: '/ai-instances',
    name: 'AIInstances',
    meta: { title: 'AI 实例' },
    component: () => import('./views/AIInstancesView.vue')
  },
  {
    path: '/self-improve',
    name: 'SelfImprove',
    meta: { title: '自我进化' },
    component: () => import('./views/SelfImproveView.vue')
  },
  {
    path: '/settings',
    name: 'Settings',
    meta: { title: '设置' },
    component: () => import('./views/SettingsView.vue')
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes,
  scrollBehavior() {
    return { top: 0 }
  }
})

router.afterEach((to) => {
  document.title = to.meta?.title ? `${to.meta.title} — IReckon` : 'IReckon — AI Factory'
})

export default router