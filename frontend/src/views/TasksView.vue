<template>
  <div class="view-root">
    <PageHeader title="任务" subtitle="查看和管理所有 AI 执行任务">
      <template #actions>
        <select v-model="statusFilter" class="input w-[132px]!" aria-label="按状态筛选">
          <option value="">全部状态</option>
          <option v-for="s in statusOptions" :key="s.value" :value="s.value">{{ s.label }}</option>
        </select>
        <button class="btn btn-secondary" @click="refresh">
          <AppIcon name="refresh" :size="13" />
          刷新
        </button>
        <button class="btn btn-primary" @click="openCreate">
          <AppIcon name="plus" :size="13" :stroke-width="2" />
          新任务
        </button>
      </template>
    </PageHeader>

    <div class="panel overflow-x-auto px-3! py-1.5! pb-3">
      <table class="table min-w-[720px]" aria-label="任务列表">
        <thead>
          <tr>
            <th class="w-[92px]" scope="col">ID</th>
            <th scope="col">标题</th>
            <th class="w-[88px]" scope="col">状态</th>
            <th class="w-[180px]" scope="col">进度</th>
            <th class="w-[90px]" scope="col">Tokens</th>
            <th class="w-[70px]" scope="col">创建时间</th>
            <th class="w-[150px] text-right" scope="col">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="task in filteredTasks" :key="task.task_id" class="cursor-pointer" @click="viewTask(task)">
            <td class="font-mono text-ink-3">{{ task.task_id.slice(5, 13) }}</td>
            <td>
              <span class="block max-w-[380px] truncate" :title="task.user_request">{{ taskTitle(task) }}</span>
            </td>
            <td><StatusPill :status="task.status" /></td>
            <td>
              <div class="progress-track">
                <div class="progress-fill" :style="{ width: boardProgress(task) + '%' }"></div>
              </div>
              <span class="text-xs text-ink-3">{{ stageText(task) }}</span>
            </td>
            <td class="font-mono text-ink-3">{{ task.tokens ? task.tokens.toLocaleString() : '—' }}</td>
            <td class="text-[13px] text-ink-2">{{ shortTime(task.created_at) }}</td>
            <td>
              <div class="flex items-center justify-end gap-1.5" @click.stop role="group" aria-label="任务操作">
                <button v-if="isActive(task)" class="btn btn-danger btn-sm" @click="cancel(task)">取消</button>
                <button v-else-if="['failed', 'paused'].includes(task.status)" class="btn btn-secondary btn-sm" @click="resume(task)">恢复</button>
                <button class="btn btn-ghost btn-icon" title="删除任务" aria-label="删除任务" @click="remove(task)">
                  <AppIcon name="trash" :size="13" />
                </button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="!filteredTasks.length" class="empty-state">
        <div class="empty-icon"><AppIcon name="box" :size="19" /></div>
        <p>{{ tasks.length ? '无匹配任务' : '暂无任务' }}</p>
        <button v-if="!tasks.length" class="btn btn-primary btn-sm" @click="openCreate">创建第一个任务</button>
      </div>
    </div>

    <NewTaskModal ref="modalRef" @created="onTaskCreated" />
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useTaskStore } from '../stores/taskStore.js'
import { useToast } from '../composables/useToast.js'
import { useConfirm } from '../composables/useConfirm.js'
import { phaseBonus, taskTitle } from '../utils/task.js'
import { timeMDHM } from '../utils/format.js'
import PageHeader from '../components/PageHeader.vue'
import StatusPill from '../components/StatusPill.vue'
import NewTaskModal from '../components/NewTaskModal.vue'
import AppIcon from '../components/ui/AppIcon.vue'

const router = useRouter()
const taskStore = useTaskStore()
const toast = useToast()
const { confirm } = useConfirm()
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

function refresh() {
  taskStore.fetchTasks()
}

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
  const ok = await confirm({
    title: '删除任务',
    message: `确定删除任务 "${task.user_request?.slice(0, 30)}"？此操作不可恢复。`,
    confirmText: '删除',
    danger: true
  })
  if (!ok) return
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
  return timeMDHM(ts)
}
</script>
