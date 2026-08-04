import { defineStore } from 'pinia'
import { ref } from 'vue'
import { taskAPI } from '../api/index.js'

export const useTaskStore = defineStore('tasks', () => {
  const tasks = ref([])
  const currentTask = ref(null)
  const messages = ref([])
  const loading = ref(false)
  const error = ref(null)

  async function fetchTasks() {
    loading.value = true
    try {
      const res = await taskAPI.list()
      tasks.value = res.data
    } catch (e) {
      error.value = e.message
    } finally {
      loading.value = false
    }
  }

  async function createTask(userRequest, schedulerCapId) {
    loading.value = true
    try {
      const res = await taskAPI.create(userRequest, schedulerCapId)
      tasks.value.unshift(res.data)
      return res.data
    } catch (e) {
      error.value = e.message
      throw e
    } finally {
      loading.value = false
    }
  }

  async function fetchMessages(taskId, layer = 'L1') {
    try {
      const res = await taskAPI.getMessages(taskId, layer)
      messages.value = res.data
      return res.data
    } catch (e) {
      error.value = e.message
      return []
    }
  }

  async function sendMessage(taskId, content, layer = 'L1') {
    try {
      const res = await taskAPI.sendMessage(taskId, content, layer)
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
      if (task) task.status = 'failed'
    } catch (e) {
      error.value = e.message
      throw e
    }
  }

  function setCurrentTask(task) {
    currentTask.value = task
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

  function addMessage(msg) {
    messages.value.push(msg)
  }

  return {
    tasks,
    currentTask,
    messages,
    loading,
    error,
    fetchTasks,
    createTask,
    fetchMessages,
    sendMessage,
    cancelTask,
    resumeTask,
    setCurrentTask,
    addMessage
  }
})