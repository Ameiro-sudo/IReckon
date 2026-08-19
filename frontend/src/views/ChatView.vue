<template>
  <div class="view-root chat-page">
    <div class="chat-headbar">
      <div>
        <h1 class="page-title">聊天</h1>
        <p class="page-subtitle">与 AI 智能体团队对话，实时跟踪任务执行</p>
      </div>
      <div class="header-actions">
        <button class="btn btn-primary" @click="openCreate">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
          新建任务
        </button>
      </div>
    </div>

    <div class="chat-shell">
      <aside class="chat-side">
        <div class="chat-side-head">
          <span class="text-sm" style="font-weight: 600;">任务</span>
          <span class="text-xs text-muted mono">{{ tasks.length }}</span>
        </div>

        <div class="chat-side-search">
          <input v-model="searchText" class="input" placeholder="搜索任务..." />
        </div>

        <div class="chat-side-list">
          <div
            v-for="task in filteredTasks"
            :key="task.task_id"
            class="chat-task"
            :class="{ active: currentTask?.task_id === task.task_id }"
            @click="selectTask(task)"
            :title="task.user_request"
          >
            <div class="chat-task-top">
              <span class="chat-task-name overflow-ellipsis">{{ taskTitle(task) }}</span>
              <StatusPill :status="task.status" />
            </div>
            <div class="chat-task-meta">
              <span>{{ formatTime(task.created_at) }}</span>
              <span v-if="task.tokens" class="mono">{{ task.tokens.toLocaleString() }}</span>
            </div>
          </div>
          <div v-if="!filteredTasks.length" class="empty-state" style="padding: 30px 10px;">
            <p class="text-sm">{{ tasks.length ? '无匹配任务' : '暂无任务，点击右上角新建' }}</p>
          </div>
        </div>
      </aside>

      <section class="chat-main">
        <div class="chat-head">
          <div class="flex-center" style="min-width: 0;">
            <span class="conn-dot" :class="wsConnected ? 'on' : 'off'" :title="wsConnected ? '实时连接' : '连接断开，重连中...'"></span>
            <h2 class="chat-title overflow-ellipsis" :title="currentTask?.user_request">{{ taskTitle(currentTask) }}</h2>
          </div>
          <div class="flex-center chat-head-actions">
            <select v-model="selectedLayer" class="input layer-select" @change="onLayerChange">
              <option value="L1">公共广场</option>
              <option value="L2">会议层</option>
            </select>
            <template v-if="currentTask">
              <button v-if="isActive" class="btn btn-danger btn-sm" @click="cancelCurrent">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
                取消
              </button>
              <button v-else-if="['failed', 'paused'].includes(currentTask.status)" class="btn btn-secondary btn-sm" @click="resumeCurrent">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2"><polygon points="5 3 19 12 5 21 5 3"/></svg>
                恢复
              </button>
              <a :href="downloadUrl" class="btn btn-secondary btn-sm" target="_blank" title="下载交付产物">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
                产物
              </a>
            </template>
          </div>
        </div>

        <div class="chat-body">
          <div class="chat-messages" ref="messagesRef">
            <div v-if="!currentTask" class="empty-state">
              <div class="empty-icon">
                <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15a2 2 0 0 1-2 2H7l-4 4V5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2z"/></svg>
              </div>
              <p>选择左侧任务，或创建一个新任务</p>
              <button class="btn btn-primary" @click="openCreate">创建新任务</button>
            </div>

            <div v-else class="msg-list">
              <div
                v-for="(msg, i) in messages"
                :key="msg.msg_id || i"
                class="msg"
                :class="{ own: msg.role === 'user', sys: msg.role === 'system' }"
              >
                <div class="msg-avatar" :style="{ background: roleColor(msg.role) }">{{ avatarText(msg.role) }}</div>
                <div class="msg-body">
                  <div class="msg-meta">
                    <span class="msg-role" :style="{ color: roleColor(msg.role) }">{{ roleLabel(msg.role) }}</span>
                    <span v-if="msg.msg_type === 'task_board_update'" class="msg-tag">看板</span>
                    <span v-else-if="msg.msg_type === 'security_warning'" class="msg-tag danger">安全</span>
                    <span v-else-if="msg.msg_type === 'code'" class="msg-tag">代码</span>
                    <span class="msg-time">{{ formatTime(msg.timestamp) }}</span>
                  </div>
                  <div class="msg-content" v-html="renderContent(msg)"></div>
                </div>
              </div>
              <div v-if="loading" class="msg-loading">
                <span class="dot"></span><span class="dot"></span><span class="dot"></span>
              </div>
            </div>
          </div>

          <aside class="chat-board" v-if="currentTask">
            <TaskBoardPanel :board="taskStore.board" />
          </aside>
        </div>

        <div class="chat-input-bar">
          <textarea
            v-model="inputText"
            class="input"
            placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
            rows="1"
            :disabled="!currentTask"
            @keydown="handleKeydown"
          ></textarea>
          <button class="btn btn-primary" :disabled="!inputText.trim() || !currentTask" @click="sendMsg">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><line x1="22" y1="2" x2="11" y2="13"/><polygon points="22 2 15 22 11 13 2 9 22 2"/></svg>
            发送
          </button>
        </div>
      </section>
    </div>

    <NewTaskModal ref="modalRef" @created="onTaskCreated" />
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, watch, nextTick } from 'vue'
import { useTaskStore } from '../stores/taskStore.js'
import { taskAPI, createWebSocket } from '../api/index.js'
import { renderMarkdown, highlightDom, roleLabel, roleColor } from '../utils/markdown.js'
import { taskTitle } from '../utils/task.js'
import { useToast } from '../composables/useToast.js'
import NewTaskModal from '../components/NewTaskModal.vue'
import TaskBoardPanel from '../components/TaskBoardPanel.vue'
import StatusPill from '../components/StatusPill.vue'

const taskStore = useTaskStore()
const toast = useToast()

const tasks = computed(() => taskStore.tasks)
const currentTask = computed(() => taskStore.currentTask)
const messages = computed(() => taskStore.messages)

const inputText = ref('')
const selectedLayer = ref('L1')
const messagesRef = ref(null)
const wsConnected = ref(false)
const loading = ref(false)
const searchText = ref('')
const modalRef = ref(null)

let ws = null
let reconnectTimer = null
let retries = 0

const ACTIVE = ['pending', 'planning', 'executing', 'reviewing', 'revising', 'delivering']
const isActive = computed(() => currentTask.value && ACTIVE.includes(currentTask.value.status))

const filteredTasks = computed(() => {
  const q = searchText.value.toLowerCase()
  if (!q) return tasks.value
  return tasks.value.filter(t => (t.user_request || '').toLowerCase().includes(q))
})

const downloadUrl = computed(() => currentTask.value ? taskAPI.downloadUrl(currentTask.value.task_id) : '#')

onMounted(async () => {
  await taskStore.fetchTasks()
  if (tasks.value.length && !currentTask.value) selectTask(tasks.value[0])
  taskStore.startPolling()
})

onUnmounted(() => {
  disconnectWs()
  taskStore.stopPolling()
})

watch(selectedLayer, () => {
  if (currentTask.value) taskStore.fetchMessages(currentTask.value.task_id, selectedLayer.value)
})

watch(messages, async () => {
  await nextTick()
  highlightDom(messagesRef.value)
  scrollDown()
}, { deep: true })

function selectTask(task) {
  taskStore.setCurrentTask(task)
  messages.value.length = 0
  taskStore.fetchMessages(task.task_id, selectedLayer.value)
  taskStore.fetchBoard(task.task_id)
  connectWs(task.task_id)
}

function connectWs(taskId) {
  disconnectWs()
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
  try {
    ws = createWebSocket(taskId)
    ws.onopen = () => { wsConnected.value = true; retries = 0 }
    ws.onclose = () => { wsConnected.value = false; scheduleReconnect(taskId) }
    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        taskStore.addWsMessage({ ...data, task_id: taskId })
        if (data.type === 'progress' && currentTask.value?.task_id === taskId) {
          taskStore.fetchTaskDetail(taskId).then(() => taskStore.fetchBoard(taskId))
        }
        scrollDown()
      } catch {
        if (e.data === 'ping') ws?.send('pong')
      }
    }
    ws.onerror = () => { wsConnected.value = false }
  } catch {
    wsConnected.value = false
  }
}

function scheduleReconnect(taskId) {
  if (reconnectTimer) return
  const delay = Math.min(1000 * 2 ** retries, 15000)
  retries += 1
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    connectWs(taskId)
  }, delay)
}

function disconnectWs() {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
  if (ws) { ws.close(); ws = null }
  wsConnected.value = false
}

function openCreate() {
  modalRef.value?.open()
}

async function onTaskCreated(request, capId, uploadId) {
  loading.value = true
  try {
    const task = await taskStore.createTask(request, capId, uploadId)
    toast.success(uploadId ? '任务已创建（含参考文件）' : '任务已创建')
    selectTask(task)
  } catch (e) {
    toast.error('创建失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

async function cancelCurrent() {
  if (!currentTask.value) return
  try {
    await taskStore.cancelTask(currentTask.value.task_id)
    toast.info('任务已取消')
  } catch (e) {
    toast.error('取消失败: ' + e.message)
  }
}

async function resumeCurrent() {
  if (!currentTask.value) return
  try {
    await taskStore.resumeTask(currentTask.value.task_id)
    toast.success('任务已恢复')
  } catch (e) {
    toast.error('恢复失败: ' + e.message)
  }
}

async function sendMsg() {
  if (!inputText.value.trim() || !currentTask.value) return
  const text = inputText.value
  inputText.value = ''
  try {
    await taskStore.sendMessage(currentTask.value.task_id, text, selectedLayer.value)
    await nextTick()
    scrollDown()
  } catch (e) {
    toast.error('发送失败: ' + e.message)
    inputText.value = text
  }
}

function handleKeydown(e) {
  if (e.key === 'Enter' && !e.shiftKey) {
    e.preventDefault()
    sendMsg()
  }
}

function onLayerChange() {
  if (currentTask.value) taskStore.fetchMessages(currentTask.value.task_id, selectedLayer.value)
}

function scrollDown() {
  if (messagesRef.value) messagesRef.value.scrollTop = messagesRef.value.scrollHeight
}

function avatarText(role) {
  const map = {
    executor: 'E', scheduler: 'S', reviewer: 'R', reviewer_correctness: 'R',
    reviewer_efficiency: 'A', deliverer: 'D', user: 'U', system: 'AI',
    security_scanner: 'SC', creative: 'C', learner: 'L', tool_manager: 'T'
  }
  return map[role] || '?'
}

function formatTime(ts) {
  if (!ts) return ''
  return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
}

function renderContent(msg) {
  if (msg.msg_type === 'task_board_update') {
    return renderMarkdown(msg.content.split('\n').slice(2).join('\n') || msg.content)
  }
  return renderMarkdown(msg.content)
}
</script>

<style scoped>
.chat-page {
  padding: 30px 34px 26px;
  max-width: 1440px;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.chat-headbar {
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.chat-shell {
  flex: 1;
  min-height: 0;
  display: flex;
  gap: 12px;
}

/* 左侧任务列表 */
.chat-side {
  width: 268px;
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  min-height: 0;
  overflow: hidden;
}

.chat-side-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 12px 14px;
  border-bottom: 1px solid var(--border);
}

.chat-side-search {
  padding: 10px 12px;
  border-bottom: 1px solid var(--border);
}

.chat-side-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
}

.chat-task {
  padding: 9px 10px;
  border-radius: var(--radius);
  cursor: pointer;
  transition: background 0.12s ease;
  border: 1px solid transparent;
  margin-bottom: 2px;
}

.chat-task:hover {
  background: var(--bg-hover);
}

.chat-task.active {
  background: var(--accent-soft);
  border-color: var(--accent-border);
}

.chat-task-top {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 2px;
}

.chat-task.active .chat-task-name {
  color: var(--accent);
  font-weight: 600;
}

.chat-task-name {
  flex: 1;
  font-size: 13px;
  font-weight: 500;
}

.chat-task-meta {
  display: flex;
  justify-content: space-between;
  font-size: 11px;
  color: var(--text-muted);
}

/* 主区域 */
.chat-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  overflow: hidden;
}

.chat-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-subtle);
}

.chat-title {
  font-size: 14px;
  font-weight: 600;
  margin-left: 4px;
}

.chat-head-actions {
  flex-shrink: 0;
}

.conn-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.conn-dot.on { background: var(--success); box-shadow: 0 0 0 3px var(--success-soft); }
.conn-dot.off { background: var(--warning); animation: blink 1.5s infinite; }

@keyframes blink {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.3; }
}

.layer-select {
  width: auto;
  padding: 5px 26px 5px 10px;
  font-size: 12px;
  background-color: var(--bg-surface);
}

.chat-body {
  flex: 1;
  display: flex;
  min-height: 0;
}

.chat-messages {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  padding: 20px 24px;
  background: var(--bg);
}

.msg-list {
  display: flex;
  flex-direction: column;
  gap: 18px;
}

.msg {
  display: flex;
  gap: 10px;
  max-width: 82%;
}

.msg.own {
  flex-direction: row-reverse;
  align-self: flex-end;
}

.msg.sys {
  align-self: center;
  max-width: 90%;
}

.msg-avatar {
  width: 28px;
  height: 28px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 10.5px;
  font-weight: 700;
  color: #fff;
  flex-shrink: 0;
  margin-top: 2px;
}

.msg.own .msg-avatar {
  background: var(--accent) !important;
}

.msg-body {
  min-width: 0;
}

.msg-meta {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 4px;
  padding: 0 2px;
}

.msg-role {
  font-size: 12px;
  font-weight: 600;
}

.msg-tag {
  font-size: 10px;
  padding: 0 7px;
  border-radius: 999px;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  color: var(--text-muted);
  line-height: 1.7;
}

.msg-tag.danger {
  background: var(--error-soft);
  color: var(--error);
  border-color: transparent;
}

.msg-time {
  font-size: 11px;
  color: var(--text-muted);
}

.msg-content {
  padding: 11px 14px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  font-size: 13px;
  line-height: 1.7;
  color: var(--text);
  box-shadow: var(--shadow-sm);
}

.msg.own .msg-content {
  background: var(--accent);
  border-color: transparent;
  color: var(--accent-contrast);
}

.msg.own .msg-content :deep(:not(pre) > code) {
  background: rgba(255, 255, 255, 0.18);
  border-color: rgba(255, 255, 255, 0.18);
  color: #fff;
}

.msg.own .msg-content :deep(a) {
  color: #e0e7ff;
}

.msg.sys .msg-content {
  background: transparent;
  border-color: transparent;
  box-shadow: none;
  text-align: center;
  font-size: 12px;
  color: var(--text-muted);
}

.msg-loading {
  display: flex;
  gap: 4px;
  padding: 10px 0;
  align-self: flex-start;
}

.msg-loading .dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent);
  animation: bounce 1.2s infinite ease-in-out both;
}

.msg-loading .dot:nth-child(2) { animation-delay: 0.15s; }
.msg-loading .dot:nth-child(3) { animation-delay: 0.3s; }

@keyframes bounce {
  0%, 80%, 100% { opacity: 0.3; transform: scale(0.8); }
  40% { opacity: 1; transform: scale(1); }
}

/* 右侧看板 */
.chat-board {
  width: 276px;
  flex-shrink: 0;
  border-left: 1px solid var(--border);
  padding: 18px;
  overflow-y: auto;
  background: var(--bg-subtle);
}

.chat-input-bar {
  display: flex;
  gap: 10px;
  padding: 13px 16px;
  border-top: 1px solid var(--border);
  align-items: flex-end;
  background: var(--bg-surface);
}

.chat-input-bar textarea {
  flex: 1;
  min-height: 38px;
  max-height: 120px;
  resize: none;
  padding: 9px 13px;
  border-radius: var(--radius-lg);
  background: var(--bg-subtle);
}

.chat-input-bar textarea:focus {
  background: var(--bg-surface);
}

@media (max-width: 1100px) {
  .chat-board { display: none; }
}

@media (max-width: 768px) {
  .chat-page {
    padding: 16px 12px 16px;
  }

  .chat-shell {
    flex-direction: column;
    gap: 8px;
  }

  .chat-side {
    width: 100%;
    max-height: 30%;
  }

  .chat-side-search { display: none; }

  .msg { max-width: 94%; }
}
</style>
