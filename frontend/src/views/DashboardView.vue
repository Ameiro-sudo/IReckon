<template>
  <PageHeader title="仪表盘" subtitle="系统概览与运行状态">
    <template #actions>
      <router-link to="/logs" class="btn btn-secondary">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M4 17l6-6-6-6"/><path d="M12 19h8"/></svg>
        系统日志
      </router-link>
      <button class="btn btn-secondary" @click="refreshAll">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
        刷新
      </button>
    </template>
  </PageHeader>

  <!-- KPI -->
  <div class="kpi-grid">
    <div class="panel kpi card-hover">
      <div class="kpi-label">总任务数</div>
      <div class="kpi-value">{{ stats?.total_tasks ?? '—' }}</div>
      <div class="kpi-sub">全部历史任务</div>
    </div>
    <div class="panel kpi card-hover">
      <div class="kpi-label">进行中</div>
      <div class="kpi-value" style="color: var(--warning);">{{ stats?.active_tasks ?? '—' }}</div>
      <div class="kpi-sub">规划/执行/审查/修订</div>
    </div>
    <div class="panel kpi card-hover">
      <div class="kpi-label">已完成</div>
      <div class="kpi-value" style="color: var(--success);">{{ stats?.completed_tasks ?? '—' }}</div>
      <div class="kpi-sub">交付成功</div>
    </div>
    <div class="panel kpi card-hover">
      <div class="kpi-label">失败</div>
      <div class="kpi-value" style="color: var(--error);">{{ stats?.failed_tasks ?? '—' }}</div>
      <div class="kpi-sub">需要关注</div>
    </div>
    <div class="panel kpi card-hover">
      <div class="kpi-label">AI 实例</div>
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
        <div class="panel-title" style="font-size: 12px; text-transform: uppercase; letter-spacing: 0.06em;">TOP 任务消耗</div>
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
          <span v-if="health.update_available" class="pill st-warning" style="background: var(--warning-soft); color: var(--warning);">
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
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRouter } from 'vue-router'
import { useTaskStore } from '../stores/taskStore.js'
import { healthAPI, statsAPI } from '../api/index.js'
import { taskTitle } from '../utils/task.js'
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
.kpi-grid {
  display: grid;
  grid-template-columns: repeat(5, 1fr);
  gap: 12px;
  margin-bottom: 16px;
}

.kpi {
  padding: 16px 18px;
}

.kpi-label {
  font-size: 12px;
  color: var(--text-secondary);
  font-weight: 500;
}

.kpi-value {
  font-size: 26px;
  font-weight: 700;
  letter-spacing: -0.02em;
  margin: 4px 0 2px;
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
  height: 12px;
  border-radius: 6px;
  overflow: hidden;
  background: var(--bg-subtle);
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
  padding: 9px 0;
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
  padding: 7px 10px;
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

@media (max-width: 480px) {
  .kpi-grid { grid-template-columns: repeat(2, 1fr); }
}
</style>
