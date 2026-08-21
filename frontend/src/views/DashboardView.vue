<template>
  <div class="view-root">
    <PageHeader title="仪表盘" subtitle="系统概览与运行状态">
      <template #actions>
        <router-link to="/logs" class="btn btn-secondary">
          <AppIcon name="zap" :size="13" />
          系统日志
        </router-link>
        <button class="btn btn-secondary" @click="refreshAll">
          <AppIcon name="refresh" :size="13" />
          刷新
        </button>
      </template>
    </PageHeader>

    <!-- 生产线总览：传送带流水线 -->
    <div class="panel mb-4 overflow-hidden px-5! pt-4! pb-0!">
      <div class="mb-3.5 flex items-baseline justify-between gap-3">
        <span class="eyebrow">Production Line</span>
        <span class="font-mono text-xs text-accent">ACTIVE {{ stats?.active_tasks ?? 0 }} · TOTAL {{ stats?.total_tasks ?? 0 }}</span>
      </div>
      <div class="flex items-stretch gap-1" role="img" aria-label="生产线各工序任务数量">
        <div
          v-for="s in lineStages"
          :key="s.code"
          class="conv-stage"
          :class="{ live: s.count > 0 && s.active, done: s.status === 'completed' && s.count > 0, bad: s.bad && s.count > 0, has: s.count > 0 && !s.active && s.status !== 'completed' && !s.bad }"
          :style="{ '--lamp': `var(--st-${s.status})` }"
          :title="`${s.label}: ${s.count}`"
        >
          <span class="conv-lamp"></span>
          <span class="conv-code">{{ s.code }}</span>
          <span class="conv-count" :class="{ zero: s.count === 0 }">{{ s.count }}</span>
          <span class="conv-label">{{ s.label }}</span>
        </div>
      </div>
      <div class="belt"><div class="belt-ticks"></div></div>
    </div>

    <!-- KPI -->
    <div class="mb-4 grid grid-cols-2 gap-3 min-[600px]:grid-cols-3 min-[1000px]:grid-cols-5">
      <div v-for="kpi in kpiCards" :key="kpi.label" class="panel card-hover p-4!">
        <div class="flex items-center justify-between gap-2">
          <div class="text-xs font-medium text-ink-2">{{ kpi.label }}</div>
          <span class="flex size-7 shrink-0 items-center justify-center rounded-md" :class="kpi.tone">
            <AppIcon :name="kpi.icon" :size="14" />
          </span>
        </div>
        <div class="mt-2 mb-0.5 font-display text-[27px] font-bold tabular-nums tracking-wide" :style="kpi.valueStyle">{{ kpi.value }}</div>
        <div class="text-[11px] text-ink-3">{{ kpi.sub }}</div>
      </div>
    </div>

    <div class="mb-3 grid gap-3 min-[1000px]:grid-cols-2">
      <!-- 任务状态分布 -->
      <div class="panel">
        <div class="plate">任务状态分布</div>
        <template v-if="hasStatusData">
          <div class="mb-3.5 flex h-2.5 overflow-hidden rounded-full border border-line bg-subtle">
            <div
              v-for="s in statusSegments"
              :key="s.status"
              class="h-full transition-[width] duration-300"
              :style="{ width: s.pct + '%', background: statusColor(s.status) }"
              :title="`${statusLabel(s.status)}: ${s.count}`"
            ></div>
          </div>
          <div class="flex flex-wrap gap-3">
            <div v-for="s in statusSegments" :key="s.status" class="flex items-center gap-1.5">
              <span class="size-2.5 rounded-sm" :style="{ background: statusColor(s.status) }"></span>
              <span class="text-[13px]">{{ statusLabel(s.status) }}</span>
              <span class="font-mono font-semibold text-ink">{{ s.count }}</span>
            </div>
          </div>
        </template>
        <div v-else class="empty-state py-6!">
          <p>暂无数据</p>
        </div>
      </div>

      <!-- Token 用量 -->
      <div class="panel">
        <div class="plate">Token 用量</div>
        <div class="flex items-start gap-6 max-sm:flex-col">
          <div>
            <div class="font-display text-[27px] font-bold tabular-nums tracking-wide">{{ formatNumber(usage?.total_tokens) }}</div>
            <div class="text-xs text-ink-3">总 Tokens</div>
          </div>
          <div class="flex min-w-0 flex-1 flex-col gap-1.5">
            <div class="flex items-center justify-between rounded-md border border-line bg-subtle px-2.5 py-1.5 text-[13px]">
              <span class="text-ink-2">本月 Tokens</span>
              <span class="font-mono">{{ formatNumber(usage?.month_tokens) }}</span>
            </div>
            <div class="flex items-center justify-between rounded-md border border-line bg-subtle px-2.5 py-1.5 text-[13px]">
              <span class="text-ink-2">总成本</span>
              <span class="font-mono">${{ usage?.total_cost ?? '0.0000' }}</span>
            </div>
            <div class="flex items-center justify-between rounded-md border border-line bg-subtle px-2.5 py-1.5 text-[13px]">
              <span class="text-ink-2">本月成本</span>
              <span class="font-mono">${{ usage?.month_cost ?? '0.0000' }}</span>
            </div>
          </div>
        </div>

        <div v-if="usage?.by_task?.length" class="mt-4">
          <div class="eyebrow mb-2.5">TOP 任务消耗</div>
          <div v-for="t in usage.by_task.slice(0, 5)" :key="t.task_id" class="mb-1.5 flex items-center gap-2.5">
            <span class="w-[100px] shrink-0 truncate font-mono text-[11px] text-ink-2">{{ t.task_id }}</span>
            <div class="progress-track flex-1">
              <div class="progress-fill" :style="{ width: barWidth(t.tokens) + '%' }"></div>
            </div>
            <span class="w-16 shrink-0 text-right font-mono text-xs text-ink-3">{{ formatNumber(t.tokens) }}</span>
          </div>
        </div>
      </div>
    </div>

    <div class="grid gap-3 pb-3 min-[1000px]:grid-cols-2">
      <!-- 系统状态 -->
      <div class="panel">
        <div class="plate">系统状态</div>
        <div class="flex flex-col">
          <div class="flex items-center justify-between border-b border-line py-2.5 last:border-b-0">
            <span class="text-[13px] text-ink-2">版本</span>
            <span class="font-mono">{{ health.version || '—' }}</span>
          </div>
          <div class="flex items-center justify-between border-b border-line py-2.5 last:border-b-0">
            <span class="text-[13px] text-ink-2">运行状态</span>
            <span class="flex items-center gap-2">
              <span class="lamp" :class="health.status === 'ok' ? 'lamp-ok' : 'lamp-bad'"></span>
              <span :class="health.status === 'ok' ? 'text-success' : 'text-error'">
                {{ health.status === 'ok' ? '正常运行' : '异常' }}
              </span>
            </span>
          </div>
          <div class="flex items-center justify-between border-b border-line py-2.5 last:border-b-0">
            <span class="text-[13px] text-ink-2">运行时间</span>
            <span class="font-mono">{{ uptime }}</span>
          </div>
          <div class="flex items-center justify-between border-b border-line py-2.5 last:border-b-0">
            <span class="text-[13px] text-ink-2">WebSocket 连接</span>
            <span class="font-mono">{{ health.ws_connections ?? '—' }}</span>
          </div>
          <div class="flex items-center justify-between py-2.5 last:border-b-0">
            <span class="text-[13px] text-ink-2">版本更新</span>
            <span v-if="health.update_available" class="pill st-warning">新版本 v{{ health.latest_version }}</span>
            <span v-else class="text-[13px] text-ink-2">已是最新</span>
          </div>
        </div>
      </div>

      <!-- 最近活动 -->
      <div class="panel">
        <div class="plate">最近活动</div>
        <div class="flex flex-col gap-1">
          <div
            v-for="task in recentTasks"
            :key="task.task_id"
            class="card-hover flex cursor-pointer items-center gap-2.5 rounded-md border border-transparent px-2.5 py-2 hover:bg-hover"
            @click="goTask(task)"
          >
            <StatusPill :status="task.status" />
            <span class="flex-1 truncate text-[13px] text-ink" :title="task.user_request">{{ taskTitle(task) }}</span>
            <span class="text-xs text-ink-3">{{ shortTime(task.updated_at) }}</span>
          </div>
          <div v-if="!recentTasks.length" class="empty-state py-6!">
            <p>暂无活动</p>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { useTaskStore } from '../stores/taskStore.js'
import { healthAPI, statsAPI } from '../api/index.js'
import { taskTitle } from '../utils/task.js'
import { formatNumber, timeHM } from '../utils/format.js'
import PageHeader from '../components/PageHeader.vue'
import StatusPill from '../components/StatusPill.vue'
import AppIcon from '../components/ui/AppIcon.vue'

const router = useRouter()
const taskStore = useTaskStore()
const health = ref({})
const usage = ref(null)
let timer = null

const stats = computed(() => taskStore.stats)
const tasks = computed(() => taskStore.tasks)

const ORDER = ['executing', 'reviewing', 'revising', 'planning', 'pending', 'completed', 'failed', 'paused']
const LABELS = {
  executing: '执行中', reviewing: '审查中', revising: '修订中', planning: '规划中',
  pending: '排队中', completed: '已完成', failed: '失败', paused: '已暂停'
}

const hasStatusData = computed(() => Object.keys(stats.value?.by_status || {}).length > 0)

// 生产线工序：真实流水线顺序（QUE→PLN→EXE→REV→RVS→DLV→DONE），FAIL/HOLD 为旁路
const LINE_FLOW = [
  { status: 'pending', code: 'QUE', label: '排队' },
  { status: 'planning', code: 'PLN', label: '规划' },
  { status: 'executing', code: 'EXE', label: '执行' },
  { status: 'reviewing', code: 'REV', label: '审查' },
  { status: 'revising', code: 'RVS', label: '修订' },
  { status: 'delivering', code: 'DLV', label: '交付' },
  { status: 'completed', code: 'DONE', label: '完成' }
]
const LINE_BYPASS = [
  { status: 'failed', code: 'FAIL', label: '失败' },
  { status: 'paused', code: 'HOLD', label: '暂停' }
]
const ACTIVE_SET = ['planning', 'executing', 'reviewing', 'revising', 'delivering']

const lineStages = computed(() => {
  const by = stats.value?.by_status || {}
  return [...LINE_FLOW, ...LINE_BYPASS].map(s => ({
    ...s,
    count: by[s.status] || 0,
    active: ACTIVE_SET.includes(s.status),
    bad: s.status === 'failed'
  }))
})

const kpiCards = computed(() => [
  {
    label: '总任务数', icon: 'box', value: stats.value?.total_tasks ?? '—',
    sub: '全部历史任务', tone: 'bg-accent-soft text-accent'
  },
  {
    label: '进行中', icon: 'clock', value: stats.value?.active_tasks ?? '—',
    sub: '规划/执行/审查/修订', tone: 'bg-warning-soft',
    valueStyle: { color: 'var(--st-executing)' }
  },
  {
    label: '已完成', icon: 'success', value: stats.value?.completed_tasks ?? '—',
    sub: '交付成功', tone: 'bg-success-soft text-success',
    valueStyle: { color: 'var(--success)' }
  },
  {
    label: '失败', icon: 'error', value: stats.value?.failed_tasks ?? '—',
    sub: '需要关注', tone: 'bg-error-soft text-error',
    valueStyle: { color: 'var(--error)' }
  },
  {
    label: 'AI 实例', icon: 'cpu', value: `${stats.value?.ai_enabled ?? '—'}/${stats.value?.ai_instances ?? '—'}`,
    sub: '启用/总数', tone: 'bg-info-soft text-info'
  }
])

const statusSegments = computed(() => {
  const by = stats.value?.by_status || {}
  const total = stats.value?.total_tasks || 1
  return ORDER
    .filter(s => (by[s] || 0) > 0)
    .map(s => ({ status: s, count: by[s], pct: Math.round((by[s] / total) * 100) }))
})

const recentTasks = computed(() => tasks.value.slice(0, 6))

function statusLabel(s) {
  return LABELS[s] || s
}

function statusColor(s) {
  return `var(--st-${s})`
}

onMounted(async () => {
  await Promise.all([taskStore.fetchStats(), taskStore.fetchTasks()])
  await Promise.all([loadHealth(), loadUsage()])
  timer = setInterval(async () => {
    await Promise.all([taskStore.fetchStats(), taskStore.fetchTasks()])
  }, 10000)
})

onUnmounted(() => {
  if (timer) clearInterval(timer)
})

async function loadHealth() {
  try {
    health.value = (await healthAPI.check()).data
  } catch { /* ignore */ }
}

async function loadUsage() {
  try {
    usage.value = (await statsAPI.usage()).data
  } catch { /* ignore */ }
}

async function refreshAll() {
  await Promise.all([taskStore.fetchStats(), taskStore.fetchTasks(), loadHealth(), loadUsage()])
}

function goTask(task) {
  taskStore.setCurrentTask(task)
  router.push('/')
}

function barWidth(tokens) {
  const max = Math.max(1, usage.value?.total_tokens || 1)
  return Math.max(3, Math.round((tokens / max) * 100))
}

function shortTime(ts) {
  return timeHM(ts) || '—'
}

const uptime = computed(() => {
  const s = health.value?.uptime_seconds || 0
  const h = Math.floor(s / 3600)
  const m = Math.floor((s % 3600) / 60)
  if (h > 0) return `${h}h ${m}m`
  if (m > 0) return `${m}m ${s % 60}s`
  return `${s}s`
})
</script>

<style scoped>
/* ===== 生产线英雄区 ===== */
.conv-stage {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 10px 4px 12px;
  border: 1px solid var(--line);
  border-bottom: none;
  border-radius: 6px 6px 0 0;
  background: var(--subtle);
  position: relative;
}

.conv-stage + .conv-stage::before {
  content: '';
  position: absolute;
  left: -5px;
  top: 50%;
  width: 6px;
  height: 2px;
  transform: translateY(-50%);
  background: var(--line-strong);
}

.conv-lamp {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  border: 1.5px solid var(--lamp);
  background: transparent;
  margin-bottom: 2px;
  transition: background 0.2s ease, box-shadow 0.2s ease;
}

.conv-stage.live .conv-lamp,
.conv-stage.done .conv-lamp,
.conv-stage.bad .conv-lamp,
.conv-stage.has .conv-lamp {
  background: var(--lamp);
  box-shadow: 0 0 8px var(--lamp);
}

.conv-stage.live .conv-lamp {
  animation: lampPulse 1.6s ease-in-out infinite;
}

.conv-code {
  font-family: var(--ff-mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.14em;
  color: var(--ink-3);
}

.conv-stage.live .conv-code {
  color: var(--ink);
}

.conv-count {
  font-family: var(--ff-display);
  font-size: 21px;
  font-weight: 700;
  line-height: 1.1;
  color: var(--ink);
  font-variant-numeric: tabular-nums;
}

.conv-count.zero {
  color: var(--ink-3);
  opacity: 0.55;
}

.conv-label {
  font-size: 10px;
  color: var(--ink-3);
}

/* 传送带 */
.belt {
  height: 7px;
  margin: 0 -20px;
  background: var(--housing);
  border-top: 1px solid var(--line-strong);
  overflow: hidden;
}

.belt-ticks {
  height: 100%;
  background-image: repeating-linear-gradient(
    -60deg,
    transparent 0 9px,
    var(--line-strong) 9px 12px
  );
  animation: beltMove 1.1s linear infinite;
  opacity: 0.75;
}
</style>
