import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  {
    path: '/',
    name: 'Chat',
    component: () => import('./views/ChatView.vue')
  },
  {
    path: '/tasks',
    name: 'Tasks',
    component: () => import('./views/TasksView.vue')
  },
  {
    path: '/dashboard',
    name: 'Dashboard',
    component: () => import('./views/DashboardView.vue')
  },
  {
    path: '/logs',
    name: 'Logs',
    component: () => import('./views/LogsView.vue')
  },
  {
    path: '/artifacts',
    name: 'Artifacts',
    component: () => import('./views/ArtifactsView.vue')
  },
  {
    path: '/ai-instances',
    name: 'AIInstances',
    component: () => import('./views/AIInstancesView.vue')
  },
  {
    path: '/self-improve',
    name: 'SelfImprove',
    component: () => import('./views/SelfImproveView.vue')
  },
  {
    path: '/settings',
    name: 'Settings',
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

export default router
