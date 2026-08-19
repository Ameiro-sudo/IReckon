<template>
  <div class="log-viewer">
    <div class="log-toolbar">
      <div class="flex-center">
        <span class="live-dot" :class="{ on: connected }"></span>
        <span class="text-sm text-secondary">{{ connected ? '实时连接中' : '连接断开' }}</span>
        <span class="log-count text-xs text-muted">{{ filtered.length }} 条</span>
      </div>
      <div class="flex-center">
        <select v-model="levelFilter" class="input log-filter">
          <option value="">全部级别</option>
          <option value="DEBUG">DEBUG</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
        </select>
        <button class="btn btn-secondary btn-sm" @click="clear">清空</button>
        <button class="btn btn-secondary btn-sm" @click="pauseToggle" :class="{ active: !autoscroll }">
          {{ autoscroll ? '暂停滚动' : '恢复滚动' }}
        </button>
      </div>
    </div>

    <div class="log-body" ref="bodyRef">
      <div v-for="(l, i) in filtered" :key="i" class="log-line" :class="`lv-${l.level.toLowerCase()}`">
        <span class="log-level">{{ l.level }}</span>
        <span class="log-msg">{{ l.message }}</span>
      </div>
      <div v-if="!filtered.length" class="log-empty">暂无日志…</div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { statsAPI, createWebSocket } from '../api/index.js'

const logs = ref([])
const levelFilter = ref('')
const connected = ref(false)
const autoscroll = ref(true)
const bodyRef = ref(null)
const MAX_LOGS = 1000
let ws = null
let reconnectTimer = null
let retries = 0

const filtered = computed(() => {
  if (!levelFilter.value) return logs.value
  return logs.value.filter(l => l.level === levelFilter.value)
})

onMounted(async () => {
  try {
    const res = await statsAPI.logs(300)
    logs.value = res.data.slice(-MAX_LOGS)
  } catch {
    /* ignore */
  }
  connectWs()
  nextTick(() => scrollBottom())
})

onUnmounted(() => disconnectWs())

function connectWs() {
  disconnectWs()
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
  try {
    ws = createWebSocket()
    ws.onopen = () => { connected.value = true; retries = 0 }
    ws.onclose = () => { connected.value = false; scheduleReconnect() }
    ws.onmessage = (e) => {
      try {
        const data = JSON.parse(e.data)
        if (data.type === 'log') {
          logs.value.push({ level: data.level || 'INFO', message: data.message })
          if (logs.value.length > MAX_LOGS) logs.value.shift()
          if (autoscroll.value) scrollBottom()
        }
      } catch {
        if (e.data === 'ping') ws?.send('pong')
      }
    }
  } catch {
    connected.value = false
    scheduleReconnect()
  }
}

function scheduleReconnect() {
  if (reconnectTimer) return
  const delay = Math.min(1000 * 2 ** retries, 15000)
  retries += 1
  reconnectTimer = setTimeout(() => {
    reconnectTimer = null
    connectWs()
  }, delay)
}

function disconnectWs() {
  if (reconnectTimer) { clearTimeout(reconnectTimer); reconnectTimer = null }
  if (ws) {
    ws.close()
    ws = null
  }
}

function clear() {
  logs.value = []
}

async function reload() {
  try {
    const res = await statsAPI.logs(300)
    logs.value = res.data.slice(-MAX_LOGS)
    nextTick(() => scrollBottom())
  } catch {
    /* ignore */
  }
}

function pauseToggle() {
  autoscroll.value = !autoscroll.value
}

function scrollBottom() {
  if (bodyRef.value) {
    bodyRef.value.scrollTop = bodyRef.value.scrollHeight
  }
}

watch(levelFilter, () => nextTick(() => scrollBottom()))

defineExpose({ reload })
</script>

<style scoped>
.log-viewer {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  overflow: hidden;
}

.log-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 11px 14px;
  border-bottom: 1px solid var(--border);
  flex-wrap: wrap;
  background: var(--bg-subtle);
}

.live-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--text-muted);
}

.live-dot.on {
  background: var(--success);
  box-shadow: 0 0 0 3px var(--success-soft);
}

.log-count {
  font-family: var(--font-mono);
}

.log-filter {
  width: 110px;
  padding: 4px 8px;
  font-size: 12px;
}

.btn-sm.active {
  background: var(--accent-soft);
  border-color: var(--accent-border);
  color: var(--accent);
}

.log-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px 0;
  font-family: var(--font-mono);
  font-size: 12px;
  line-height: 1.7;
}

.log-line {
  display: flex;
  gap: 12px;
  padding: 2px 16px;
  white-space: pre-wrap;
  word-break: break-all;
  border-left: 2px solid transparent;
}

.log-line:hover {
  background: var(--bg-hover);
}

.log-line.lv-error {
  border-left-color: var(--error);
}

.log-level {
  flex-shrink: 0;
  width: 62px;
  font-weight: 600;
  user-select: none;
  font-size: 10.5px;
  letter-spacing: 0.03em;
}

.lv-debug .log-level { color: var(--text-muted); }
.lv-info .log-level { color: var(--info); }
.lv-warning .log-level { color: var(--warning); }
.lv-error .log-level { color: var(--error); }

.log-msg {
  color: var(--text-secondary);
}

.log-empty {
  text-align: center;
  color: var(--text-muted);
  padding: 40px 0;
}
</style>
