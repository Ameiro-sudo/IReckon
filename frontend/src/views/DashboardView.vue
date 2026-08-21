<template>
  <PageHeader title="仪表盘" subtitle="系统概览与运行状态">
    <template #actions>
      <router-link to="/logs" class="btn btn-secondary">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2L3 14h9l-1 8 10-12h-9l1-8z"/></svg>
        系统日志
      </router-link>
      <button class="btn btn-secondary" @click="refreshAll">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        刷新
      </button>
    </template>
  </PageHeader>

  <!-- 生产线总览：传送带流水线 -->
  <div class="line-hero panel">
    <div class="line-head">
      <span class="line-eyebrow">Production Line</span>
      <span class="line-meta mono">ACTIVE {{ stats?.active_tasks ?? 0 }} · TOTAL {{ stats?.total_tasks ?? 0 }}</span>
    </div>
    <div class="conveyor" role="img" aria-label="生产线各工序任务数量">
      <div
        v-for="s in lineStages"
        :key="s.code"
        class="conv-stage"
        :class="{ live: s.count > 0 && s.active, done: s.status === 'completed' && s.count > 0, bad: s.bad && s.count > 0, has: s.count > 0 && !s.active && s.status !== 'completed' && !s.bad }"
        :style="{ '--lamp': s.color }"
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
  <div class="kpi-grid">
    <div class="panel kpi card-hover">
      <div class="kpi-head">
        <div class="kpi-label">总任务数</div>
        <span class="kpi-icon kpi-total">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><rect x="3" y="3" width="18" height="18" rx="2"/><line x1="3" y1="9" x2="21" y2="9"/><line x1="9" y1="21" x2="9" y2="9"/></svg>
        </span>
      </div>
      <div class="kpi-value">{{ stats?.total_tasks ?? '—' }}</div>
      <div class="kpi-sub">全部历史任务</div>
    </div>
    <div class="panel kpi card-hover">
      <div class="kpi-head">
        <div class="kpi-label">进行中</div>
        <span class="kpi-icon kpi-active">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>
        </span>
      </div>
      <div class="kpi-value" style="color: var(--st-executing);">{{ stats?.active_tasks ?? '—' }}</div>
      <div class="kpi-sub">规划/执行/审查/修订</div>
    </div>
    <div class="panel kpi card-hover">
      <div class="kpi-head">
        <div class="kpi-label">已完成</div>
        <span class="kpi-icon kpi-done">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><polyline points="22 4 12 14.01 9 11.01"/></svg>
        </span>
      </div>
      <div class="kpi-value" style="color: var(--success);">{{ stats?.completed_tasks ?? '—' }}</div>
      <div class="kpi-sub">交付成功</div>
    </div>
    <div class="panel kpi card-hover">
      <div class="kpi-head">
        <div class="kpi-label">失败</div>
        <span class="kpi-icon kpi-fail">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round"><circle cx="12" cy="12" r="10"/><line x1="15" y1="9" x2="9" y2="15"/><line x1="9" y1="9" x2="15" y2="15"/></svg>
        </span>
      </div>
      <div class="kpi-value" style="color: var(--error);">{{ stats?.failed_tasks ?? '—' }}</div>
      <div class="kpi-sub">需要关注</div>
    </div>
    <div class="panel kpi card-hover">
      <div class="kpi-head">
        <div class="kpi-label">AI 实例</div>
        <span class="kpi-icon kpi-ai">
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg>
        </span>
      </div>
      <div class="kpi-value">{{ stats?.ai_enabled ?? '—' }}/{{ stats?.ai_instances ?? '—' }}</div>
      <div class="kpi-sub">启用/总数</div>
    </div>
  </div>

  <div class="dash-grid">
    <!-- 任务状态分布 -->
    <div class="panel">
      <div class="panel-title">任务状态分布</div>
      <div v-if="hasStatusData">
        <div class="dist-track">
          <div
            v-for="s in statusSegments"
            :key="s.status"
            class="dist-seg"
            :style="{ width: s.pct + '%', background: statusColor(s.status) }"
            :title="`${statusLabel(s.status)}: ${s.count}`"
          ></div>
        </div>
        <div class="dist-legend">
          <div v-for="s in statusSegments" :key="s.status" class="legend-item">
            <span class="legend-dot" :style="{ background: statusColor(s.status) }"></span>
            <span class="text-sm">{{ statusLabel(s.status) }}</span>
            <span class="mono legend-count">{{ s.count }}</span>
          </div>
          <span v-if="!statusSegments.length" class="text-sm text-muted">暂无任务数据</span>
        </div>
      </div>
      <div v-else class="empty-state" style="padding: 24px;">
        <p class="text-sm">暂无数据</p>
      </div>
    </div>

    <!-- Token 用量 -->
    <div class="panel">
      <div class="panel-title">Token 用量</div>
      <div class="usage-top">
        <div>
          <div class="kpi-value">{{ formatNumber(usage?.total_tokens) }}</div>
          <div class="text-xs text-muted">总 Tokens</div>
        </div>
        <div class="usage-stats">
          <div class="usage-row">
            <span class="text-sm text-secondary">本月 Tokens</span>
            <span class="mono">{{ formatNumber(usage?.month_tokens) }}</span>
          </div>
          <div class="usage-row">
            <span class="text-sm text-secondary">总成本</span>
            <span class="mono">${{ usage?.total_cost ?? '0.0000' }}</span>
          </div>
          <div class="usage-row">
            <span class="text-sm text-secondary">本月成本</span>
            <span class="mono">${{ usage?.month_cost ?? '0.0000' }}</span>
          </div>
        </div>
      </div>

      <div v-if="usage?.by_task?.length" style="margin-top: 16px;">
        <div class="panel-title usage-sub-title">TOP 任务消耗</div>
        <div v-for="t in usage.by_task.slice(0, 5)" :key="t.task_id" class="top-task">
          <span class="mono top-task-id overflow-ellipsis">{{ t.task_id }}</span>
          <div class="progress-track" style="flex: 1;">
            <div class="progress-fill" :style="{ width: barWidth(t.tokens) + '%' }"></div>
          </div>
          <span class="mono text-xs text-muted" style="width: 64px; text-align: right;">{{ formatNumber(t.tokens) }}</span>
        </div>
      </div>
    </div>
  </div>

  <div class="dash-grid">
    <!-- 系统状态 -->
    <div class="panel">
      <div class="panel-title">系统状态</div>
      <div class="info-list">
        <div class="info-row">
          <span class="info-label">版本</span>
          <span class="mono">{{ health.version || '—' }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">运行状态</span>
          <span class="flex-center">
            <span class="sys-dot" :class="health.status === 'ok' ? 'on' : 'off'"></span>
            <span :style="{ color: health.status === 'ok' ? 'var(--success)' : 'var(--error)' }">
              {{ health.status === 'ok' ? '正常运行' : '异常' }}
            </span>
          </span>
        </div>
        <div class="info-row">
          <span class="info-label">运行时间</span>
          <span class="mono">{{ uptime }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">WebSocket 连接</span>
          <span class="mono">{{ health.ws_connections ?? '—' }}</span>
        </div>
        <div class="info-row">
          <span class="info-label">版本更新</span>
          <span v-if="health.update_available" class="pill st-warning">
            新版本 v{{ health.latest_version }}
          </span>
          <span v-else class="text-sm text-secondary">已是最新</span>
        </div>
      </div>
    </div>

    <!-- 最近活动 -->
    <div class="panel">
      <div class="panel-title">最近活动</div>
      <div class="activity-list">
        <div v-for="task in recentTasks" :key="task.task_id" class="activity-item card-hover" @click="goTask(task)">
          <StatusPill :status="task.status" />
          <span class="activity-text overflow-ellipsis" :title="task.user_request">{{ taskTitle(task) }}</span>
          <span class="text-xs text-muted">{{ shortTime(task.updated_at) }}</span>
        </div>
        <div v-if="!recentTasks.length" class="empty-state" style="padding: 24px;">
          <p class="text-sm">暂无活动</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import {computed, onMounted, onUnmounted, ref} from 'vue'
import {useRouter} from 'vue-router'
import {useTaskStore} from '../stores/taskStore.js'
import {healthAPI, statsAPI} from '../api/index.js'
import {taskTitle} from '../utils/task.js'
import PageHeader from '../components/PageHeader.vue'
import StatusPill from '../components/StatusPill.vue'

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
const COLORS = {
  executing: 'var(--st-executing)', reviewing: 'var(--st-reviewing)', revising: 'var(--st-revising)',
  planning: 'var(--st-planning)', pending: 'var(--st-pending)', completed: 'var(--st-completed)',
  failed: 'var(--st-failed)', paused: 'var(--st-paused)'
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
    bad: s.status === 'failed',
    color: `var(--st-${s.status})`
  }))
})

const statusSegments = computed(() => {
  const by = stats.value?.by_status || {}
  const total = stats.value?.total_tasks || 1
  return ORDER
    .filter(s => (by[s] || 0) > 0)
    .map(s => ({ status: s, count: by[s], pct: Math.round((by[s] / total) * 100) }))
})

const recentTasks = computed(() => tasks.value.slice(0, 6))

function statusLabel(s) { return LABELS[s] || s }
function statusColor(s) { return COLORS[s] || 'var(--text-muted)' }

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

function formatNumber(n) {
  if (n == null) return '—'
  return Number(n).toLocaleString('zh-CN')
}

function shortTime(ts) {
  if (!ts) return '—'
  return new Date(ts).toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })
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
.line-hero {
  flex-shrink: 0;
  padding: 16px 20px 0;
  margin-bottom: 16px;
  overflow: hidden;
}

.line-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.line-eyebrow {
  font-family: var(--font-display);
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.22em;
  text-transform: uppercase;
  color: var(--text-muted);
}

.line-meta {
  color: var(--accent);
}

.conveyor {
  display: flex;
  align-items: stretch;
  gap: 4px;
}

.conv-stage {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 3px;
  padding: 10px 4px 12px;
  border: 1px solid var(--border);
  border-bottom: none;
  border-radius: var(--radius) var(--radius) 0 0;
  background: var(--bg-subtle);
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
  background: var(--border-strong);
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

@keyframes lampPulse {
  0%, 100% { box-shadow: 0 0 4px var(--lamp); }
  50% { box-shadow: 0 0 11px var(--lamp); }
}

.conv-code {
  font-family: var(--font-mono);
  font-size: 10px;
  font-weight: 600;
  letter-spacing: 0.14em;
  color: var(--text-muted);
}

.conv-stage.live .conv-code { color: var(--text); }

.conv-count {
  font-family: var(--font-display);
  font-size: 21px;
  font-weight: 700;
  line-height: 1.1;
  color: var(--text);
  font-variant-numeric: tabular-nums;
}

.conv-stage .conv-count.zero {
  color: var(--text-muted);
  opacity: 0.55;
}

.conv-label {
  font-size: 10px;
  color: var(--text-muted);
}

/* 传送带 */
.belt {
  height: 7px;
  margin: 0 -20px;
  background: var(--bg-housing);
  border-top: 1px solid var(--border-strong);
  overflow: hidden;
}

.belt-ticks {
  height: 100%;
  background-image: repeating-linear-gradient(
    -60deg,
    transparent 0 9px,
    var(--border-strong) 9px 12px
  );
  animation: beltMove 1.1s linear infinite;
  opacity: 0.75;
}

@keyframes beltMove {
  to { background-position: 24px 0; }
}

/* ===== KPI ===== */
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.kpi {
  padding: 16px 18px;
}

.kpi-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
}

.kpi-label {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 500;
}

.kpi-icon {
  width: 28px;
  height: 28px;
  border-radius: var(--radius);
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
}

.kpi-total { background: var(--accent-soft); color: var(--accent); }
.kpi-active { background: var(--warning-soft); color: var(--st-executing); }
.kpi-done { background: var(--success-soft); color: var(--success); }
.kpi-fail { background: var(--error-soft); color: var(--error); }
.kpi-ai { background: rgba(79, 163, 216, 0.12); color: var(--st-planning); }

.kpi-value {
  font-size: 27px;
  font-weight: 700;
  font-family: var(--font-display);
  letter-spacing: 0.01em;
  margin: 9px 0 3px;
  font-variant-numeric: tabular-nums;
}

.kpi-sub {
  font-size: 11px;
  color: var(--text-muted);
}

.dash-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-bottom: 12px;
}

.dist-track {
  display: flex;
  height: 10px;
  border-radius: 5px;
  overflow: hidden;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  margin-bottom: 14px;
}

.dist-seg {
  height: 100%;
  transition: width 0.4s ease;
}

.dist-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 12px;
}

.legend-item {
  display: flex;
  align-items: center;
  gap: 6px;
}

.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 3px;
}

.legend-count {
  color: var(--text);
  font-weight: 600;
}

.usage-top {
  display: flex;
  gap: 24px;
  align-items: flex-start;
}

.usage-stats {
  flex: 1;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.usage-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 6px 10px;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.top-task {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 7px;
}

.top-task-id {
  width: 100px;
  font-size: 11px;
  color: var(--text-secondary);
}

.info-list {
  display: flex;
  flex-direction: column;
}

.info-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 0;
  border-bottom: 1px solid var(--border);
}

.info-row:last-child {
  border-bottom: none;
}

.info-label {
  font-size: 13px;
  color: var(--text-secondary);
}

.sys-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
}

.sys-dot.on { background: var(--success); box-shadow: 0 0 0 3px var(--success-soft); }
.sys-dot.off { background: var(--error); box-shadow: 0 0 0 3px var(--error-soft); }

.activity-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.activity-item {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 10px;
  border-radius: var(--radius);
  cursor: pointer;
  border: 1px solid transparent;
}

.activity-text {
  flex: 1;
  font-size: 13px;
  color: var(--text);
}

@media (max-width: 1000px) {
  .kpi-grid { grid-template-columns: repeat(3, 1fr); }
  .dash-grid { grid-template-columns: 1fr; }
}

@media (max-width: 600px) {
  .kpi-grid { grid-template-columns: repeat(2, 1fr); }
}

@media (max-width: 400px) {
  .kpi-grid { grid-template-columns: 1fr; }
}

.usage-sub-title {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-muted);
}
</style>
