<template>
  <div class="view-root">
    <PageHeader title="任务" subtitle="查看和管理所有 AI 执行任务">
    <template #actions>
      <select v-model="statusFilter" class="input filter-select">
        <option value="">全部状态</option>
        <option v-for="s in statusOptions" :key="s.value" :value="s.value">{{ s.label }}</option>
      </select>
      <button class="btn btn-secondary" @click="refresh">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        刷新
      </button>
      <button class="btn btn-primary" @click="openCreate">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        新任务
      </button>
    </template>
  </PageHeader>

  <div class="panel tasks-table-wrap">
    <table class="table" aria-label="任务列表">
      <thead>
        <tr>
          <th style="width: 92px;" scope="col">ID</th>
          <th scope="col">标题</th>
          <th style="width: 88px;" scope="col">状态</th>
          <th style="width: 180px;" scope="col">进度</th>
          <th style="width: 90px;" scope="col">Tokens</th>
          <th style="width: 70px;" scope="col">创建时间</th>
          <th style="width: 150px; text-align: right;" scope="col">操作</th>
        </tr>
      </thead>
      <tbody>
        <tr v-for="task in filteredTasks" :key="task.task_id" @click="viewTask(task)" style="cursor: pointer;">
          <td class="mono text-muted">{{ task.task_id.slice(5, 13) }}</td>
          <td>
            <span class="overflow-ellipsis" style="display: block; max-width: 380px;" :title="task.user_request">{{ taskTitle(task) }}</span>
          </td>
          <td><StatusPill :status="task.status" /></td>
          <td>
            <div class="progress-track">
              <div class="progress-fill" :style="{ width: boardProgress(task) + '%' }"></div>
            </div>
            <span class="text-xs text-muted">{{ stageText(task) }}</span>
          </td>
          <td class="mono text-muted">{{ task.tokens ? task.tokens.toLocaleString() : '—' }}</td>
          <td class="text-sm text-secondary">{{ shortTime(task.created_at) }}</td>
          <td>
            <div class="flex-center" style="justify-content: flex-end; gap: 6px;" @click.stop role="group" aria-label="任务操作">
              <button v-if="isActive(task)" class="btn btn-danger btn-sm" @click="cancel(task)">取消</button>
              <button v-else-if="['failed', 'paused'].includes(task.status)" class="btn btn-secondary btn-sm" @click="resume(task)">恢复</button>
              <button class="btn btn-ghost btn-icon" title="删除任务" aria-label="删除任务" @click="remove(task)">
                <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"/></svg>
              </button>
            </div>
          </td>
        </tr>
      </tbody>
    </table>

    <div v-if="!filteredTasks.length" class="empty-state">
      <div class="empty-icon">
        <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
      </div>
      <p>{{ tasks.length ? '无匹配任务' : '暂无任务' }}</p>
      <button v-if="!tasks.length" class="btn btn-primary btn-sm" @click="openCreate">创建第一个任务</button>
    </div>
  </div>

  <NewTaskModal ref="modalRef" @created="onTaskCreated" />
  </div>
</template>

<script setup>
import {computed, onMounted, onUnmounted, ref} from 'vue'
import {useRouter} from 'vue-router'
import {useTaskStore} from '../stores/taskStore.js'
import {useToast} from '../composables/useToast.js'
import {phaseBonus, taskTitle} from '../utils/task.js'
import PageHeader from '../components/PageHeader.vue'
import StatusPill from '../components/StatusPill.vue'
import NewTaskModal from '../components/NewTaskModal.vue'

const router = useRouter()
const taskStore = useTaskStore()
const toast = useToast()
const statusFilter = ref('')
const modalRef = ref(null)

const statusOptions = [
  { value: 'pending', label: '排队中' }, { value: 'planning', label: '规划中' },
  { value: 'executing', label: '执行中' }, { value: 'reviewing', label: '审查中' },
  { value: 'revising', label: '修订中' }, { value: 'delivering', label: '交付中' },
  { value: 'completed', label: '已完成' }, { value: 'failed', label: '失败' },
  { value: 'paused', label: '已暂停' }
]

const tasks = computed(() => taskStore.tasks)
const filteredTasks = computed(() => {
  if (!statusFilter.value) return tasks.value
  return tasks.value.filter(t => t.status === statusFilter.value)
})

onMounted(() => {
  taskStore.fetchTasks()
  taskStore.startPolling()
})

onUnmounted(() => taskStore.stopPolling())

function openCreate() {
  modalRef.value?.open()
}

async function onTaskCreated(request, capId, uploadId) {
  try {
    const task = await taskStore.createTask(request, capId, uploadId)
    toast.success(uploadId ? '任务已创建（含参考文件）' : '任务已创建')
    viewTask(task)
  } catch (e) {
    toast.error('创建失败: ' + (e.response?.data?.detail || e.message))
  }
}

function refresh() { taskStore.fetchTasks() }

function viewTask(task) {
  taskStore.setCurrentTask(task)
  router.push('/')
}

function isActive(task) {
  return ['pending', 'planning', 'executing', 'reviewing', 'revising', 'delivering'].includes(task.status)
}

async function cancel(task) {
  try {
    await taskStore.cancelTask(task.task_id)
    toast.info('任务已取消')
  } catch (e) {
    toast.error('取消失败: ' + e.message)
  }
}

async function resume(task) {
  try {
    await taskStore.resumeTask(task.task_id)
    toast.success('任务已恢复')
  } catch (e) {
    toast.error('恢复失败: ' + e.message)
  }
}

async function remove(task) {
  if (!confirm(`确定删除任务 "${task.user_request?.slice(0, 30)}"？此操作不可恢复。`)) return
  try {
    await taskStore.deleteTask(task.task_id)
    toast.success('任务已删除')
  } catch (e) {
    toast.error('删除失败: ' + e.message)
  }
}

function boardProgress(task) {
  const board = task.board
  if (board) {
    const total = Math.max(1, board.total_stages || 1)
    const stage = Math.min(board.current_stage || 0, total - 1)
    return Math.min(100, Math.round((stage / total) * 100 + (phaseBonus[board.phase] || 0) * 100 / total))
  }
  const fallback = { pending: 2, planning: 8, executing: 35, reviewing: 55, revising: 55, delivering: 80, completed: 100, failed: 100 }
  return fallback[task.status] || 0
}

function stageText(task) {
  const board = task.board
  if (board) {
    return `阶段 ${(board.current_stage || 0) + 1}/${board.total_stages || 1} · ${board.stage_name || ''}`
  }
  const map = {
    pending: '排队中', planning: '规划中', executing: '执行中', reviewing: '审查中',
    revising: '修订中', delivering: '交付中', completed: '已完成', failed: '已失败'
  }
  return map[task.status] || '—'
}

function shortTime(ts) {
  if (!ts) return '—'
  return new Date(ts).toLocaleString('zh-CN', { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
}
</script>

<style scoped>
.view-root {
  display: flex;
  flex-direction: column;
  flex: 1;
  min-height: 0;
}

.filter-select {
  width: 132px;
  padding: 6px 26px 6px 10px;
  font-size: 13px;
}

.tasks-table-wrap {
  padding: 6px 12px 12px;
  overflow-x: auto;
}

@media (max-width: 768px) {
  .filter-select { width: 100%; }

  .tasks-table-wrap {
    padding: 4px;
  }

  .table th, .table td {
    padding: 8px;
  }

  .table {
    min-width: 720px;
  }
}
</style>
