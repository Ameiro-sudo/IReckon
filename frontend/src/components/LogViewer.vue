<template>
  <div class="flex h-full min-h-0 flex-col overflow-hidden rounded-lg border border-line bg-surface">
    <div class="flex flex-wrap items-center justify-between gap-3 border-b border-line bg-subtle px-3.5 py-2.5">
      <div class="flex items-center gap-2">
        <span class="lamp" :class="connected ? 'lamp-ok' : 'lamp-warn'"></span>
        <span class="text-[13px] text-ink-2">{{ connected ? '实时连接中' : '连接断开' }}</span>
        <span class="font-mono text-xs text-ink-3">{{ filtered.length }} 条</span>
      </div>
      <div class="flex items-center gap-2">
        <select v-model="levelFilter" class="input w-[110px]! px-2! py-1! text-xs" aria-label="日志级别筛选">
          <option value="">全部级别</option>
          <option value="DEBUG">DEBUG</option>
          <option value="INFO">INFO</option>
          <option value="WARNING">WARNING</option>
          <option value="ERROR">ERROR</option>
        </select>
        <button class="btn btn-secondary btn-sm" @click="clear">清空</button>
        <button class="btn btn-secondary btn-sm" :class="{ 'border-accent-border! bg-accent-soft! text-accent!': !autoscroll }" @click="pauseToggle">
          {{ autoscroll ? '暂停滚动' : '恢复滚动' }}
        </button>
      </div>
    </div>

    <div ref="bodyRef" class="min-h-0 flex-1 overflow-y-auto py-2.5 font-mono text-xs leading-relaxed" role="log" aria-live="polite" aria-label="系统日志">
      <div
        v-for="(l, i) in filtered"
        :key="i"
        class="flex items-start gap-3 border-l-2 border-transparent px-4 py-0.5 break-all whitespace-pre-wrap hover:bg-hover"
      >
        <span class="w-[58px] shrink-0 select-none text-[11px] text-ink-3">{{ l.time || '--:--:--' }}</span>
        <span
          class="w-[74px] shrink-0 rounded border border-line px-1 py-px text-center text-[10px] font-semibold tracking-wide select-none"
          :class="levelBadge(l.level)"
        >{{ l.level }}</span>
        <span class="min-w-0 flex-1 text-ink-2">{{ l.message }}</span>
      </div>
      <div v-if="!filtered.length" class="py-10 text-center text-ink-3">暂无日志…</div>
    </div>
  </div>
</template>

<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref, watch } from 'vue'
import { statsAPI } from '../api/index.js'
import { useLiveSocket } from '../composables/useLiveSocket.js'

const logs = ref([])
const levelFilter = ref('')
const autoscroll = ref(true)
const bodyRef = ref(null)
const MAX_LOGS = 1000

// WS 生命周期统一由 useLiveSocket 管理（代数守卫 + 退避重连 + 心跳应答）
const socket = useLiveSocket({ onMessage: handleMsg })
const connected = socket.connected

const filtered = computed(() => {
  if (!levelFilter.value) return logs.value
  return logs.value.filter(l => l.level === levelFilter.value)
})

onMounted(async () => {
  await loadHistory()
  socket.connect(null)
  await nextTick(() => scrollBottom())
})

onUnmounted(() => socket.disconnect())

async function loadHistory() {
  try {
    const res = await statsAPI.logs(300)
    logs.value = res.data.slice(-MAX_LOGS)
  } catch {
    /* ignore */
  }
}

function handleMsg(data) {
  if (data.type === 'log') {
    logs.value.push({ level: data.level || 'INFO', message: data.message })
    if (logs.value.length > MAX_LOGS) logs.value.shift()
    if (autoscroll.value) scrollBottom()
  }
}

function clear() {
  logs.value = []
}

async function reload() {
  await loadHistory()
  await nextTick(() => scrollBottom())
}

function pauseToggle() {
  autoscroll.value = !autoscroll.value
}

function scrollBottom() {
  if (bodyRef.value) {
    bodyRef.value.scrollTop = bodyRef.value.scrollHeight
  }
}

function levelBadge(level) {
  return {
    DEBUG: 'text-ink-3 bg-subtle',
    INFO: 'text-info bg-info/10',
    SUCCESS: 'text-success bg-success/10',
    WARNING: 'text-warning bg-warning/10',
    ERROR: 'text-error bg-error/10',
    CRITICAL: 'text-error bg-error/20 font-bold'
  }[level] || 'text-ink-3 bg-subtle'
}

watch(levelFilter, () => nextTick(() => scrollBottom()))

defineExpose({ reload })
</script>
