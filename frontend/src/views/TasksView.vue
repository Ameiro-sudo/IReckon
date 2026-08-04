<template>
  <div class="page-view">
    <div class="page-header">
      <div>
        <h1 class="page-title">任务管理</h1>
        <p class="page-subtitle">查看和管理所有 AI 执行任务</p>
      </div>
      <button class="btn btn-primary" @click="refresh">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        刷新
      </button>
    </div>

    <div class="tasks-grid">
      <div v-for="task in tasks" :key="task.task_id" class="task-card card">
        <div class="task-card-header">
          <span class="task-id">#{{ task.task_id?.slice(0, 10) }}</span>
          <span class="badge" :class="statusClass(task.status)">{{ task.status }}</span>
        </div>
        <p class="task-request">{{ task.user_request }}</p>
        <div class="task-meta">
          <span>
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
            {{ formatTime(task.created_at) }}
          </span>
          <span v-if="task.updated_at">
            <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/><line x1="16" y1="13" x2="8" y2="13"/><line x1="16" y1="17" x2="8" y2="17"/></svg>
            {{ formatTime(task.updated_at) }}
          </span>
        </div>
        <div class="task-actions">
          <button class="btn btn-secondary btn-sm" @click="viewTask(task)">查看</button>
          <button v-if="task.status === 'executing'" class="btn btn-danger btn-sm" @click="cancel(task.task_id)">取消</button>
          <button v-if="task.status === 'failed'" class="btn btn-secondary btn-sm" @click="resume(task.task_id)">恢复</button>
        </div>
      </div>

      <div v-if="!tasks.length" class="empty-state">
        <div class="empty-icon">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><rect x="3" y="3" width="18" height="18" rx="2" ry="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
        </div>
        <p>暂无任务</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { useTaskStore } from '../stores/taskStore.js'

const router = useRouter()
const taskStore = useTaskStore()
const tasks = computed(() => taskStore.tasks)

onMounted(() => { taskStore.fetchTasks() })

function refresh() { taskStore.fetchTasks() }

function viewTask(task) {
  taskStore.setCurrentTask(task)
  router.push('/')
}

async function cancel(id) { await taskStore.cancelTask(id) }
async function resume(id) { await taskStore.resumeTask(id) }

function statusClass(status) {
  const map = { completed: 'badge-success', failed: 'badge-error', executing: 'badge-warning', pending: 'badge-info' }
  return map[status] || 'badge-info'
}

function formatTime(ts) {
  if (!ts) return '-'
  return new Date(ts).toLocaleString('zh-CN')
}
</script>

<style scoped>
.tasks-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(300px, 1fr));
  gap: 16px;
}

.task-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.task-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
  border-color: var(--glass-border);
}

.task-card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.task-id {
  font-size: 12px;
  color: var(--text-muted);
  font-family: 'JetBrains Mono', monospace;
}

.task-request {
  font-size: 14px;
  color: var(--text-primary);
  line-height: 1.5;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}

.task-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: var(--text-muted);
}

.task-meta span {
  display: flex;
  align-items: center;
  gap: 4px;
}

.task-actions {
  display: flex;
  gap: 8px;
  margin-top: 4px;
}

.btn-sm {
  padding: 5px 12px;
  font-size: 12px;
}

@media (max-width: 480px) {
  .tasks-grid { grid-template-columns: 1fr !important; }
  .task-card { gap: 8px; }
  .task-actions { flex-wrap: wrap; }
}
</style>
