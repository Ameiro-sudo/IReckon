import { defineStore } from 'pinia'
import { ref, computed } from 'vue'
import { taskAPI, statsAPI } from '../api/index.js'

function normalizeWsMessage(raw) {
  const role = raw.sender_role || raw.role || 'system'
  const content = raw.content || ''
  let msgType = raw.msg_type || 'text'
  if (raw.type === 'progress') msgType = 'progress'
  if (raw.type === 'log') msgType = 'log'
  return {
    msg_id: raw.msg_id || `${Date.now()}-${Math.random().toString(36).slice(2, 8)}`,
    role,
    content,
    msg_type: msgType,
    layer: raw.layer || 'L1',
    timestamp: raw.timestamp || new Date().toISOString(),
    progress: raw.progress,
    status: raw.status,
    level: raw.level,
    metadata: raw.metadata || {}
  }
}

export const useTaskStore = defineStore('tasks', () => {
  const tasks = ref([])
  const currentTask = ref(null)
  const messages = ref([])
  const board = ref(null)
  const stats = ref(null)
  const loading = ref(false)
  const error = ref(null)
  let pollTimer = null

  const activeCount = computed(() =>
    tasks.value.filter(t => ['pending', 'planning', 'executing', 'reviewing', 'revising', 'delivering'].includes(t.status)).length
  )

  async function fetchTasks() {
    loading.value = true
    try {
      const res = await taskAPI.list()
      tasks.value = res.data
      return res.data
    } catch (e) {
      error.value = e.message
      return []
    } finally {
      loading.value = false
    }
  }

  async function createTask(userRequest, schedulerCapId, uploadId) {
    loading.value = true
    try {
      const res = await taskAPI.create(userRequest, schedulerCapId, uploadId)
      tasks.value.unshift(res.data)
      setCurrentTask(res.data)
      messages.value = []
      board.value = null
      return res.data
    } catch (e) {
      error.value = e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function fetchTaskDetail(taskId) {
    try {
      const res = await taskAPI.get(taskId)
      const idx = tasks.value.findIndex(t => t.task_id === taskId)
      if (idx >= 0) tasks.value[idx] = { ...tasks.value[idx], ...res.data }
      if (currentTask.value?.task_id === taskId) {
        currentTask.value = { ...currentTask.value, ...res.data }
        if (res.data.board) board.value = res.data.board
      }
      return res.data
    } catch (e) {
      error.value = e.message
      return null
    }
  }

  async function fetchBoard(taskId) {
    if (!taskId) return null
    try {
      const res = await taskAPI.getBoard(taskId)
      board.value = res.data
      return res.data
    } catch {
      return null
    }
  }

  async function fetchMessages(taskId, layer = 'L1') {
    try {
      const res = await taskAPI.getMessages(taskId, layer)
      if (currentTask.value?.task_id === taskId) {
        mergeMessages(res.data)
      }
      return res.data
    } catch (e) {
      error.value = e.message
      return []
    }
  }

  function mergeMessages(list) {
    const seen = new Set(messages.value.map(m => m.msg_id))
    const fresh = list.map(normalizeWsMessage).filter(m => !seen.has(m.msg_id))
    if (fresh.length) messages.value = [...messages.value, ...fresh]
    if (messages.value.length > 800) {
      messages.value = messages.value.slice(-800)
    }
  }

  async function sendMessage(taskId, content, layer = 'L1') {
    try {
      const res = await taskAPI.sendMessage(taskId, content, layer)
      messages.value.push({
        msg_id: res.data.msg_id,
        role: 'user',
        content,
        msg_type: 'text',
        layer,
        timestamp: res.data.timestamp
      })
      return res.data
    } catch (e) {
      error.value = e.message
      throw e
    }
  }

  async function cancelTask(taskId) {
    try {
      await taskAPI.cancel(taskId)
      const task = tasks.value.find(t => t.task_id === taskId)
      if (task) task.status = 'paused'
    } catch (e) {
      error.value = e.message
      throw e
    }
  }

  async function resumeTask(taskId) {
    try {
      await taskAPI.resume(taskId)
      const task = tasks.value.find(t => t.task_id === taskId)
      if (task) task.status = 'executing'
    } catch (e) {
      error.value = e.message
      throw e
    }
  }

  async function deleteTask(taskId) {
    try {
      await taskAPI.delete(taskId)
      tasks.value = tasks.value.filter(t => t.task_id !== taskId)
      if (currentTask.value?.task_id === taskId) {
        currentTask.value = null
        messages.value = []
        board.value = null
      }
    } catch (e) {
      error.value = e.message
      throw e
    }
  }

  async function fetchStats() {
    try {
      const res = await statsAPI.get()
      stats.value = res.data
      return res.data
    } catch {
      return null
    }
  }

  function addWsMessage(raw) {
    const msg = normalizeWsMessage(raw)
    if (msg.msg_type === 'log') return
    if (msg.msg_type === 'progress') {
      if (msg.status) {
        const task = tasks.value.find(t => t.task_id === raw.task_id)
        if (task) task.status = msg.status
      }
      return
    }
    const exists = messages.value.some(m => m.msg_id === msg.msg_id)
    if (!exists) messages.value.push(msg)
  }

  function setCurrentTask(task) {
    currentTask.value = task
    board.value = null
  }

  function startPolling() {
    stopPolling()
    pollTimer = setInterval(async () => {
      await fetchTasks()
      if (currentTask.value?.task_id) {
        await fetchTaskDetail(currentTask.value.task_id)
        await fetchBoard(currentTask.value.task_id)
      }
    }, 8000)
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer)
      pollTimer = null
    }
  }

  return {
    tasks,
    currentTask,
    messages,
    board,
    stats,
    loading,
    error,
    activeCount,
    fetchTasks,
    createTask,
    fetchTaskDetail,
    fetchBoard,
    fetchMessages,
    sendMessage,
    cancelTask,
    resumeTask,
    deleteTask,
    fetchStats,
    addWsMessage,
    setCurrentTask,
    startPolling,
    stopPolling
  }
})
