<template>
  <div class="view-root mx-auto flex w-full max-w-[1440px] flex-col min-h-0 px-3 pt-4 pb-4 md:px-[34px]">
    <div class="mb-4 flex items-end justify-between gap-4 max-md:flex-wrap max-md:gap-2">
      <div>
        <h1 class="font-display text-[22px] font-bold leading-tight tracking-wide text-ink">聊天</h1>
        <p class="mt-1.5 text-[13px] text-ink-2">与 AI 智能体团队对话，实时跟踪任务执行</p>
      </div>
      <button class="btn btn-primary" @click="openCreate">
        <AppIcon name="plus" :size="13" :stroke-width="2" />
        新建任务
      </button>
    </div>

    <div class="flex min-h-0 flex-1 flex-col gap-2 md:flex-row md:gap-3">
      <!-- 左侧任务轨道 -->
      <aside class="flex max-h-44 shrink-0 flex-col overflow-hidden rounded-lg border border-line bg-surface md:max-h-none md:w-[268px]">
        <TaskListRail :tasks="tasks" v-model="selectedTaskProxy" show-meta />
      </aside>

      <!-- 主对话区 -->
      <section class="flex min-w-0 flex-1 flex-col overflow-hidden rounded-lg border border-line bg-surface">
        <div class="flex items-center justify-between gap-3 border-b border-line bg-subtle px-4 py-2.5">
          <div class="flex min-w-0 items-center gap-2">
            <span class="lamp shrink-0" :class="connected ? 'lamp-ok' : 'lamp-warn'" :title="connected ? '实时连接' : '连接断开，重连中...'"></span>
            <h2 class="truncate text-sm font-semibold text-ink" :title="currentTask?.user_request">{{ taskTitle(currentTask) }}</h2>
          </div>
          <div class="flex shrink-0 items-center gap-2">
            <select v-model="selectedLayer" class="input w-auto! py-1! text-xs!" aria-label="消息层级">
              <option value="L1">公共广场</option>
              <option value="L2">会议层</option>
            </select>
            <template v-if="currentTask">
              <button v-if="isActive" class="btn btn-danger btn-sm" @click="cancelCurrent">
                <AppIcon name="x" :size="11" :stroke-width="2.2" />
                取消
              </button>
              <button v-else-if="['failed', 'paused'].includes(currentTask.status)" class="btn btn-secondary btn-sm" @click="resumeCurrent">
                <AppIcon name="play" :size="11" :stroke-width="2.2" />
                恢复
              </button>
              <a :href="downloadUrl" class="btn btn-secondary btn-sm" target="_blank" title="下载交付产物">
                <AppIcon name="download" :size="11" :stroke-width="2.2" />
                产物
              </a>
            </template>
          </div>
        </div>

        <div class="flex min-h-0 flex-1">
          <div ref="messagesRef" class="min-w-0 flex-1 overflow-y-auto bg-bg px-5 py-5 md:px-6">
            <div v-if="!currentTask" class="empty-state h-full justify-center">
              <div class="empty-icon"><AppIcon name="chat" :size="19" /></div>
              <p>选择左侧任务，或创建一个新任务</p>
              <button class="btn btn-primary" @click="openCreate">创建新任务</button>
            </div>

            <div v-else class="flex flex-col gap-4">
              <div v-if="!messages.length && !loading" class="empty-state py-14!">
                <div class="empty-icon"><AppIcon name="chat" :size="19" /></div>
                <p>暂无消息。丢个需求过来，我看行。</p>
              </div>
              <div
                v-for="(msg, i) in messages"
                :key="msg.msg_id || i"
                class="msg flex max-w-[82%] gap-2.5"
                :class="{ own: msg.role === 'user', sys: msg.role === 'system' }"
              >
                <div
                  class="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-lg text-[11px] font-bold text-white"
                  :style="msg.role !== 'user' ? { background: roleColor(msg.role) } : null"
                >{{ avatarText(msg.role) }}</div>
                <div class="min-w-0">
                  <div class="mb-1 flex items-center gap-2 px-0.5">
                    <span class="text-xs font-semibold" :style="{ color: roleColor(msg.role) }">{{ roleTag(msg.role) }}</span>
                    <span v-if="msg.msg_type === 'task_board_update'" class="rounded-full border border-line bg-subtle px-[7px] text-[10px] leading-[1.7] text-ink-3">看板</span>
                    <span v-else-if="msg.msg_type === 'security_warning'" class="rounded-full bg-error-soft px-[7px] text-[10px] leading-[1.7] text-error">安全</span>
                    <span v-else-if="msg.msg_type === 'code'" class="rounded-full border border-line bg-subtle px-[7px] text-[10px] leading-[1.7] text-ink-3">代码</span>
                    <span class="text-[11px] text-ink-3">{{ formatTime(msg.timestamp) }}</span>
                  </div>
                  <div class="bubble rounded-lg border border-line bg-surface px-3.5 py-2.5 text-[13px] leading-relaxed text-ink shadow-sm" v-html="renderContent(msg)"></div>
                </div>
              </div>
              <div v-if="loading || isActive" class="flex items-center gap-2.5 self-start py-2.5">
                <span class="flex gap-1">
                  <span class="msg-dot"></span><span class="msg-dot"></span><span class="msg-dot"></span>
                </span>
                <span class="text-xs text-ink-3">{{ activeHint }}</span>
              </div>
            </div>
          </div>

          <aside v-if="taskStore.board" class="hidden w-[276px] shrink-0 overflow-y-auto border-l border-line bg-subtle px-[18px] py-[18px] desk:block">
            <TaskBoardPanel :board="taskStore.board" />
          </aside>
        </div>

        <div class="flex items-end gap-2.5 border-t border-line bg-surface px-4 py-3">
          <textarea
            v-model="inputText"
            class="input flex-1 resize-none overflow-y-auto rounded-lg bg-subtle py-2! focus:bg-surface!"
            placeholder="输入消息... (Enter 发送, Shift+Enter 换行)"
            rows="1"
            aria-label="消息输入框"
            :disabled="!currentTask"
            @keydown="handleKeydown"
            @input="autoGrow"
          ></textarea>
          <button class="btn btn-primary" :disabled="!inputText.trim() || !currentTask" @click="sendMsg" aria-label="发送消息">
            <AppIcon name="send" :size="13" :stroke-width="1.8" />
            发送
          </button>
        </div>
      </section>
    </div>

    <NewTaskModal ref="modalRef" @created="onTaskCreated" />
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { useTaskStore } from '../stores/taskStore.js'
import { taskAPI } from '../api/index.js'
import { useLiveSocket } from '../composables/useLiveSocket.js'
import { highlightDom, renderMarkdown, roleColor, roleLabel } from '../utils/markdown.js'
import { loadingCopy, roleEmoji } from '../utils/persona.js'
import { taskTitle } from '../utils/task.js'
import { timeHM } from '../utils/format.js'
import { useToast } from '../composables/useToast.js'
import NewTaskModal from '../components/NewTaskModal.vue'
import TaskBoardPanel from '../components/TaskBoardPanel.vue'
import TaskListRail from '../components/TaskListRail.vue'
import AppIcon from '../components/ui/AppIcon.vue'

const taskStore = useTaskStore()
const toast = useToast()

const tasks = computed(() => taskStore.tasks)
const currentTask = computed(() => taskStore.currentTask)
const messages = computed(() => taskStore.messages)

const inputText = ref('')
const selectedLayer = ref('L1')
const messagesRef = ref(null)
const loading = ref(false)
const modalRef = ref(null)
// 当前连接的任务：WS 回调据此归属事件，防止切任务后旧事件串台
let activeTaskId = null

// WS 生命周期统一由 useLiveSocket 管理（代数守卫 + 退避重连 + 心跳应答）
const socket = useLiveSocket({ onMessage: handleWsMsg })
const connected = socket.connected

const ACTIVE = ['pending', 'planning', 'executing', 'reviewing', 'revising', 'delivering']
const isActive = computed(() => currentTask.value && ACTIVE.includes(currentTask.value.status))

// IR-01 人格层：活跃阶段轮播文案池（6s 换一句，任务切换归零）；
// 创建请求在途（loading）期间固定用 creating 池，避免闪现上一个任务的阶段文案
const phaseTick = ref(0)
let hintTimer = null
const activeHint = computed(() => {
  if (loading.value) return loadingCopy('creating', 1)
  return loadingCopy(currentTask.value?.status || '', phaseTick.value)
})

watch(isActive, (on) => {
  if (on && !hintTimer) hintTimer = setInterval(() => { phaseTick.value++ }, 6000)
  if (!on && hintTimer) {
    clearInterval(hintTimer)
    hintTimer = null
  }
}, { immediate: true })

const downloadUrl = computed(() => currentTask.value ? taskAPI.downloadUrl(currentTask.value.task_id) : '#')
// 消息数量：仅监听长度变化触发高亮/滚动，避免对 800+ 条消息做深度遍历
const messagesLength = computed(() => messages.value.length)

// TaskListRail 的 v-model 代理：选中即切换任务
const selectedTaskProxy = computed({
  get: () => currentTask.value,
  set: (task) => {
    if (task && task.task_id !== currentTask.value?.task_id) selectTask(task)
  }
})

onMounted(async () => {
  await taskStore.fetchTasks()
  if (tasks.value.length && !currentTask.value) selectTask(tasks.value[0])
  taskStore.startPolling()
})

onUnmounted(() => {
  socket.disconnect()
  taskStore.stopPolling()
  if (hintTimer) {
    clearInterval(hintTimer)
    hintTimer = null
  }
})

watch(selectedLayer, () => {
  if (currentTask.value) taskStore.fetchMessages(currentTask.value.task_id, selectedLayer.value)
})

watch(messagesLength, async () => {
  await nextTick()
  highlightDom(messagesRef.value)
  scrollDown()
})

function handleWsMsg(data) {
  taskStore.addWsMessage({ ...data, task_id: activeTaskId })
  if (data.type === 'progress' && activeTaskId && currentTask.value?.task_id === activeTaskId) {
    taskStore.fetchTaskDetail(activeTaskId).then(() => taskStore.fetchBoard(activeTaskId))
  }
  scrollDown()
}

function selectTask(task) {
  taskStore.setCurrentTask(task)
  messages.value.length = 0
  activeTaskId = task.task_id
  phaseTick.value = 0
  taskStore.fetchMessages(task.task_id, selectedLayer.value)
  taskStore.fetchBoard(task.task_id)
  socket.connect(task.task_id)
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
    scrollDown(true)
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

function scrollDown(force = false) {
  const el = messagesRef.value
  if (!el) return
  if (force || el.scrollHeight - el.scrollTop - el.clientHeight < 80) {
    el.scrollTop = el.scrollHeight
  }
}

function autoGrow(e) {
  const el = e.target
  el.style.height = 'auto'
  el.style.height = Math.min(el.scrollHeight, 120) + 'px'
}

function avatarText(role) {
  const map = {
    executor: 'E', scheduler: 'S', reviewer: 'R', reviewer_correctness: 'R',
    reviewer_efficiency: 'A', deliverer: 'D', user: 'U', system: 'AI',
    security_scanner: 'SC', creative: 'C', learner: 'L', tool_manager: 'T'
  }
  return map[role] || '?'
}

// 消息头识别物：emoji + 角色名（未知角色回退纯名字，不留双空格）
function roleTag(role) {
  const emoji = roleEmoji(role)
  return emoji ? `${emoji} ${roleLabel(role)}` : roleLabel(role)
}

function formatTime(ts) {
  return timeHM(ts)
}

function renderContent(msg) {
  if (msg.msg_type === 'task_board_update') {
    return renderMarkdown(msg.content.split('\n').slice(2).join('\n') || msg.content)
  }
  return renderMarkdown(msg.content)
}
</script>

<style scoped>
.msg.own {
  flex-direction: row-reverse;
  align-self: flex-end;
}

.msg.sys {
  align-self: center;
  max-width: 90%;
}

.msg.own .bubble {
  background: var(--accent-fill);
  border-color: transparent;
  color: var(--accent-ink);
}

.msg.own .bubble :deep(:not(pre) > code) {
  background: rgba(255, 255, 255, 0.18);
  border-color: rgba(255, 255, 255, 0.18);
  color: var(--accent-ink);
}

.msg.own .bubble :deep(a) {
  color: var(--accent-ink);
  text-decoration: underline;
}

.msg.sys .bubble {
  background: transparent;
  border-color: transparent;
  box-shadow: none;
  text-align: center;
  font-size: 12px;
  color: var(--ink-3);
}

.msg-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--accent-fill);
  animation: msgBounce 1.2s infinite ease-in-out both;
}

.msg-dot:nth-child(2) {
  animation-delay: 0.15s;
}

.msg-dot:nth-child(3) {
  animation-delay: 0.3s;
}
</style>
