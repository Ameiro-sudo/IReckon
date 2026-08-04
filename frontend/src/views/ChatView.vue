<template>
  <div class="chat-view">
    <div class="chat-sidebar">
      <div class="sidebar-top">
        <div class="section-title">任务列表</div>
        <button class="btn btn-primary btn-sm" @click="createTask">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          新任务
        </button>
      </div>

      <div class="task-list">
        <div
          v-for="task in tasks"
          :key="task.task_id"
          class="task-item"
          :class="{ active: currentTask?.task_id === task.task_id }"
          @click="selectTask(task)"
        >
          <div class="task-item-top">
            <span class="task-name">{{ task.user_request?.slice(0, 24) || '新任务' }}</span>
            <span class="task-badge" :class="statusBadge(task.status)">{{ task.status }}</span>
          </div>
          <span class="task-time">{{ formatTime(task.created_at) }}</span>
        </div>
        <div v-if="!tasks.length" class="empty-tasks">
          <p>暂无任务</p>
        </div>
      </div>
    </div>

    <div class="chat-main">
      <div class="chat-header">
        <div class="chat-header-left">
          <h2 class="chat-title" v-if="currentTask">
            {{ currentTask.user_request?.slice(0, 40) || '聊天' }}
          </h2>
          <h2 class="chat-title" v-else>聊天</h2>
          <span v-if="wsConnected" class="connection-dot connected"></span>
          <span v-else class="connection-dot disconnected"></span>
        </div>
        <div class="chat-header-right">
          <select v-model="selectedLayer" class="input layer-select">
            <option value="L1">公共广场</option>
            <option value="L3">私人消息</option>
          </select>
        </div>
      </div>

      <div class="messages-area" ref="messagesRef">
        <div v-if="!currentTask" class="empty-state">
          <div class="empty-icon">
            <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
          </div>
          <p>选择一个任务开始聊天</p>
          <button class="btn btn-primary" @click="createTask">创建新任务</button>
        </div>

        <div v-else class="messages-list">
          <div
            v-for="(msg, i) in messages"
            :key="msg.id || i"
            class="message"
            :class="{ 'message-own': msg.role === 'user', 'message-system': msg.role === 'system' }"
          >
            <div class="msg-avatar">
              {{ msg.role === 'user' ? 'U' : roleAvatar(msg.role) }}
            </div>
            <div class="msg-body">
              <div class="msg-meta">
                <span class="msg-role">{{ displayRole(msg.role) }}</span>
                <span class="msg-time">{{ formatTime(msg.timestamp) }}</span>
              </div>
              <div class="msg-content" v-html="renderContent(msg.content)"></div>
            </div>
          </div>
          <div v-if="isLoading" class="loading-indicator">
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
            <span class="typing-dot"></span>
          </div>
        </div>
      </div>

      <div class="input-area">
        <textarea
          v-model="inputText"
          class="input msg-input"
          placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
          @keydown="handleKeydown"
          :disabled="!currentTask"
          rows="1"
        ></textarea>
        <button
          class="btn btn-primary send-btn"
          @click="sendMsg"
          :disabled="!inputText.trim() || !currentTask"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
          发送
        </button>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useTaskStore } from '../stores/taskStore.js'
import { taskAPI, createWebSocket } from '../api/index.js'

const taskStore = useTaskStore()
const tasks = computed(() => taskStore.tasks)
const currentTask = computed(() => taskStore.currentTask)
const messages = computed(() => taskStore.messages)

const inputText = ref('')
const selectedLayer = ref('L1')
const messagesRef = ref(null)
const wsConnected = ref(false)
const isLoading = ref(false)

let ws = null

const roleMap = {
  user: '👤 用户',
  executor: '⚡ 执行者',
  scheduler: '📋 调度器',
  reviewer: '🔍 审查者',
  deliverer: '📦 交付者',
  system: '🤖 系统',
  security_scanner: '🛡️ 安全扫描'
}

onMounted(async () => {
  await taskStore.fetchTasks()
  if (tasks.value.length && !currentTask.value) {
    selectTask(tasks.value[0])
  }
})

onUnmounted(() => {
  disconnectWs()
})

watch(selectedLayer, () => {
  if (currentTask.value) {
    taskStore.fetchMessages(currentTask.value.task_id, selectedLayer.value)
  }
})

function selectTask(task) {
  taskStore.setCurrentTask(task)
  taskStore.fetchMessages(task.task_id, selectedLayer.value)
  connectWs(task.task_id)
}

function connectWs(taskId) {
  disconnectWs()
  try {
    ws = createWebSocket(taskId)
    ws.onopen = () => { wsConnected.value = true }
    ws.onclose = () => { wsConnected.value = false }
    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        taskStore.addMessage(data)
        scrollDown()
      } catch { /* ignore */ }
    }
    ws.onerror = () => { wsConnected.value = false }
  } catch {
    wsConnected.value = false
  }
}

function disconnectWs() {
  if (ws) {
    ws.close()
    ws = null
    wsConnected.value = false
  }
}

async function createTask() {
  const request = prompt('请输入任务描述:')
  if (request) {
    isLoading.value = true
    try {
      const task = await taskStore.createTask(request)
      selectTask(task)
    } finally {
      isLoading.value = false
    }
  }
}

async function sendMsg() {
  if (!inputText.value.trim() || !currentTask.value) return
  const text = inputText.value
  inputText.value = ''
  isLoading.value = true
  try {
    await taskStore.sendMessage(
      currentTask.value.task_id,
      text,
      selectedLayer.value
    )
    await taskStore.fetchMessages(currentTask.value.task_id, selectedLayer.value)
    await nextTick()
    scrollDown()
  } finally {
    isLoading.value = false
  }
}

function handleKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMsg()
  }
}

function scrollDown() {
  if (messagesRef.value) {
    messagesRef.value.scrollTop = messagesRef.value.scrollHeight
  }
}

function statusBadge(status) {
  const map = {
    completed: 'badge-success',
    failed: 'badge-error',
    executing: 'badge-warning',
    pending: 'badge-info'
  }
  return map[status] || 'badge-info'
}

function roleAvatar(role) {
  const avatars = {
    executor: 'E',
    scheduler: 'S',
    reviewer: 'R',
    deliverer: 'D',
    user: 'U',
    system: 'AI',
    security_scanner: 'SC'
  }
  return avatars[role] || '?'
}

function displayRole(role) {
  return roleMap[role] || role
}

function formatTime(ts) {
  if (!ts) return ''
  return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function renderContent(content) {
  if (!content) return ''
  return content
    .replace(/```(\w+)?\n([\s\S]*?)```/g, '<pre><code class="code-block">$2</code></pre>')
    .replace(/`([^`]+)`/g, '<code>$1</code>')
    .replace(/\n/g, '<br>')
}
</script>

<style scoped>
.chat-view {
  height: 100%;
  display: flex;
  gap: 0;
}

.chat-sidebar {
  width: 260px;
  flex-shrink: 0;
  background: var(--bg-glass);
  backdrop-filter: blur(16px) saturate(180%);
  -webkit-backdrop-filter: blur(16px) saturate(180%);
  border-right: 1px solid var(--glass-border);
  display: flex;
  flex-direction: column;
}

.sidebar-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px;
  border-bottom: 1px solid var(--border-light);
}

.section-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-muted);
  text-transform: uppercase;
  letter-spacing: 0.5px;
}

.btn-sm {
  padding: 5px 10px;
  font-size: 12px;
  gap: 4px;
}

.task-list {
  flex: 1;
  overflow-y: auto;
  padding: 8px;
}

.task-item {
  padding: 10px 12px;
  border-radius: var(--radius-md);
  cursor: pointer;
  transition: all 0.2s ease;
  margin-bottom: 4px;
  border: 1px solid transparent;
}

.task-item:hover {
  background: var(--bg-hover);
  border-color: var(--border-light);
}

.task-item.active {
  background: rgba(60, 150, 202, 0.08);
  border-color: rgba(60, 150, 202, 0.2);
}

.task-item-top {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 2px;
}

.task-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text-primary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.task-badge {
  font-size: 10px;
  padding: 1px 8px;
  border-radius: 10px;
  flex-shrink: 0;
}

.task-time {
  font-size: 11px;
  color: var(--text-muted);
}

.empty-tasks {
  text-align: center;
  padding: 20px;
  color: var(--text-muted);
  font-size: 13px;
}

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}

.chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 14px 24px;
  border-bottom: 1px solid var(--glass-border);
  background: var(--bg-glass);
  backdrop-filter: blur(12px) saturate(180%);
  -webkit-backdrop-filter: blur(12px) saturate(180%);
}

.chat-header-left {
  display: flex;
  align-items: center;
  gap: 10px;
}

.chat-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text-primary);
  font-family: 'Noto Serif SC', serif;
}

.connection-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.connection-dot.connected {
  background: var(--success);
  box-shadow: 0 0 6px var(--success);
}

.connection-dot.disconnected {
  background: var(--text-muted);
}

.layer-select {
  width: auto;
  padding: 6px 12px;
  font-size: 12px;
}

.messages-area {
  flex: 1;
  overflow-y: auto;
  padding: 20px 24px;
}

.messages-list {
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.message {
  display: flex;
  gap: 10px;
  max-width: 80%;
}

.message-own {
  flex-direction: row-reverse;
  align-self: flex-end;
}

.message-system {
  align-self: center;
  max-width: 90%;
}

.msg-avatar {
  width: 32px;
  height: 32px;
  border-radius: 10px;
  background: var(--bg-glass);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid var(--glass-border-subtle);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 12px;
  font-weight: 700;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.message-own .msg-avatar {
  background: var(--accent-gradient);
  color: white;
  border: none;
}

.msg-body {
  min-width: 0;
}

.msg-meta {
  display: flex;
  gap: 8px;
  align-items: center;
  margin-bottom: 4px;
}

.msg-role {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-primary);
}

.msg-time {
  font-size: 10px;
  color: var(--text-muted);
}

.msg-content {
  padding: 12px 16px;
  background: var(--bg-glass);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid var(--glass-border-subtle);
  border-radius: var(--radius-lg);
  font-size: 13px;
  line-height: 1.6;
  color: var(--text-primary);
  word-break: break-word;
  transition: all 0.2s ease;
}

.msg-content:hover {
  border-color: var(--glass-border);
  box-shadow: var(--shadow-sm);
}

.message-own .msg-content {
  background: var(--accent-gradient);
  color: white;
  border: none;
}

.message-own .msg-content:hover {
  box-shadow: 0 4px 16px rgba(60, 150, 202, 0.25);
}

.message-system .msg-content {
  background: var(--bg-glass);
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
  border-color: transparent;
}

.msg-content :deep(pre) {
  background: rgba(0, 0, 0, 0.2);
  padding: 10px;
  border-radius: 8px;
  overflow-x: auto;
  margin: 6px 0;
  font-size: 12px;
}

.msg-content :deep(code) {
  font-family: 'JetBrains Mono', 'Fira Code', monospace;
  font-size: 12px;
}

.msg-content :deep(.code-block) {
  display: block;
}

.loading-indicator {
  display: flex;
  gap: 4px;
  padding: 12px 16px;
  align-self: flex-start;
}

.typing-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--primary);
  animation: typingBounce 1.4s infinite ease-in-out both;
}

.typing-dot:nth-child(1) { animation-delay: -0.32s; }
.typing-dot:nth-child(2) { animation-delay: -0.16s; }
.typing-dot:nth-child(3) { animation-delay: 0s; }

@keyframes typingBounce {
  0%, 80%, 100% { transform: scale(0.6); opacity: 0.4; }
  40% { transform: scale(1); opacity: 1; }
}

.input-area {
  display: flex;
  gap: 10px;
  padding: 16px 24px;
  border-top: 1px solid var(--glass-border);
  background: var(--bg-glass);
  backdrop-filter: blur(12px) saturate(180%);
  -webkit-backdrop-filter: blur(12px) saturate(180%);
}

.msg-input {
  flex: 1;
  padding: 10px 14px;
  border-radius: var(--radius-lg);
  resize: none;
  min-height: 42px;
  max-height: 120px;
  font-size: 13px;
}

.send-btn {
  align-self: flex-end;
  padding: 10px 18px;
  border-radius: var(--radius-lg);
}

@media (max-width: 768px) {
  .chat-view { flex-direction: column !important; }
  .chat-sidebar {
    width: 100% !important;
    max-height: 160px;
    border-right: none !important;
    border-bottom: 1px solid var(--glass-border);
    flex-shrink: 0;
  }
  .message { max-width: 92% !important; }
  .chat-header { padding: 10px 14px !important; }
  .messages-area { padding: 14px !important; }
  .input-area { padding: 12px 14px !important; }
}

@media (max-width: 480px) {
  .chat-header-left { margin-left: 40px; }
  .chat-header { padding: 8px 12px !important; }
  .chat-title { font-size: 14px !important; }
  .messages-area { padding: 10px !important; }
  .input-area { padding: 8px 12px !important; flex-direction: column; gap: 8px; }
  .msg-input { min-height: 36px; font-size: 12px !important; }
  .send-btn { width: 100%; justify-content: center; }
  .msg-content { font-size: 12px !important; padding: 10px 12px !important; }
  .message { max-width: 98% !important; }
  .chat-sidebar { max-height: 120px; }
  .sidebar-top { padding: 10px 12px; }
  .task-list { padding: 4px; }
  .task-item { padding: 8px 10px; }
}
</style>
