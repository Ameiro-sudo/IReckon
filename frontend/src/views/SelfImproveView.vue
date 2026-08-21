<template>
  <div class="view-root">
    <PageHeader title="自我进化" subtitle="AI 自主分析代码并生成改进" content-class="max-w-[680px]">
      <template #actions>
        <button class="btn btn-secondary" :disabled="!canPush || pushing" @click="pushChanges">
          {{ pushing ? '推送中...' : '推送分支' }}
        </button>
        <button class="btn btn-primary" :disabled="running" @click="startRun">
          {{ running ? '运行中...' : '开始分析' }}
        </button>
      </template>
    </PageHeader>

    <div class="max-w-[680px] pb-3">
      <div class="panel">
        <div class="plate">进化引擎</div>
        <p class="plate-desc">让 IReckon 分析自身代码，识别优化机会并自动生成改进方案。流水线在后台执行，进度实时轮询，刷新页面不丢状态。</p>

        <!-- 运行中：阶段指示 -->
        <div v-if="running && run" class="mt-3">
          <div class="progress-track">
            <div class="progress-fill w-[40%] animate-[indeterminate_1.4s_infinite_ease-in-out]"></div>
          </div>
          <p class="mt-2 text-[13px] text-ink-3">
            {{ run.phase === 'applying' ? 'AI 正在落地修改并提交分支...' : 'AI 正在检查代码...' }}
          </p>
        </div>

        <!-- 完成态结果卡 -->
        <div v-if="run && !running" class="mt-2 flex flex-col gap-2.5">
          <div v-if="run.error" class="rounded-md bg-error-soft px-3.5 py-2.5 text-error">
            <p class="text-[13px]">{{ run.error }}</p>
          </div>
          <template v-if="run.status === 'ok'">
            <div class="flex gap-2.5 text-[13px]">
              <span class="w-[70px] shrink-0 text-ink-3">分析摘要</span>
              <span>{{ run.analysis || '—' }}</span>
            </div>
            <div v-if="run.branch" class="flex items-center gap-2.5 text-[13px]">
              <span class="w-[70px] shrink-0 text-ink-3">分支</span>
              <code class="rounded-md border border-line bg-subtle px-2 py-0.5 font-mono text-xs">{{ run.branch }}</code>
            </div>
            <div v-if="run.files_changed?.length" class="flex gap-2.5 text-[13px]">
              <span class="w-[70px] shrink-0 text-ink-3">修改文件</span>
              <span>{{ run.files_changed.length }} 个</span>
            </div>
            <div v-if="run.files_changed?.length" class="mt-1 flex flex-col gap-1">
              <div v-for="file in run.files_changed" :key="file" class="rounded-md border border-line bg-subtle px-2.5 py-1.5 font-mono text-xs text-ink-2">
                {{ file }}
              </div>
            </div>
            <div class="flex items-center gap-1.5 text-[13px] font-semibold text-success">
              <AppIcon name="check" :size="13" :stroke-width="2.2" />
              改进完成
            </div>
          </template>
        </div>
      </div>

      <div class="panel mt-0.5">
        <div class="plate">历史运行
          <button class="btn btn-ghost btn-icon ml-auto" aria-label="刷新历史" @click="loadHistory">
            <AppIcon name="refresh" :size="14" />
          </button>
        </div>
        <div v-if="history.length" class="flex flex-col gap-1.5">
          <div v-for="item in history" :key="item.run_id" class="flex items-center justify-between gap-3 rounded-md border border-line bg-subtle px-3 py-2">
            <div class="flex min-w-0 items-center gap-2.5">
              <span class="pill" :class="item.status === 'ok' ? 'st-completed' : item.status === 'running' ? 'st-warning' : 'st-failed'">{{ statusLabel(item.status) }}</span>
              <code class="truncate font-mono text-xs text-ink-2">{{ item.branch || item.error || '—' }}</code>
            </div>
            <div class="flex shrink-0 items-center gap-2.5 text-xs text-ink-3">
              <span v-if="item.files_changed?.length">{{ item.files_changed.length }} 文件</span>
              <span class="font-mono">{{ shortTime(item.started_at) }}</span>
            </div>
          </div>
        </div>
        <div v-else class="p-3 text-[13px] text-ink-3">还没有运行记录，点上方「开始分析」启动第一次自我进化。</div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { selfImproveAPI } from '../api/index.js'
import { useToast } from '../composables/useToast.js'
import PageHeader from '../components/PageHeader.vue'
import AppIcon from '../components/ui/AppIcon.vue'

const toast = useToast()
const run = ref(null) // 运行态：{run_id,status,phase?,analysis,branch,files_changed,error,...}
const history = ref([])
const pushing = ref(false)
const pushedForRun = ref(null) // 已推送过的 run_id，防重复推同一分支
let pollTimer = null

const running = computed(() => run.value?.status === 'running')
const canPush = computed(() => run.value?.status === 'ok' && !!run.value.branch)

function startPolling() {
  stopPolling()
  pollTimer = setInterval(refreshStatus, 2000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
}

async function refreshStatus() {
  try {
    const res = await selfImproveAPI.status()
    const wasRunning = running.value
    run.value = res.data.run
    if (wasRunning && res.data.active === false && res.data.run) {
      stopPolling()
      loadHistory()
      if (res.data.run.status === 'ok') toast.success('自我改进完成')
      else toast.error(res.data.run.error || '自我改进失败')
    }
    if (res.data.active) startPolling()
    else if (!wasRunning) stopPolling()
  } catch {
    /* 后端离线时静默，保留现有界面 */
  }
}

async function loadHistory() {
  try {
    const res = await selfImproveAPI.history()
    history.value = res.data.items || []
  } catch {
    /* 静默 */
  }
}

async function startRun() {
  try {
    const res = await selfImproveAPI.analyze()
    const data = res.data
    if (data.status === 'started' || data.status === 'busy') {
      run.value = data.run
      startPolling()
      if (data.status === 'started') toast.success('已启动后台分析')
      else toast.info('已有任务在运行中')
    } else {
      toast.error(data.error || '无法启动')
    }
  } catch (e) {
    toast.error('启动失败: ' + e.message)
  }
}

async function pushChanges() {
  pushing.value = true
  try {
    const res = await selfImproveAPI.push()
    if (res.data.status === 'ok') {
      pushedForRun.value = run.value?.run_id
      toast.success('已推送到远程分支')
    } else {
      toast.error('推送失败')
    }
  } catch (e) {
    toast.error('推送失败: ' + e.message)
  } finally {
    pushing.value = false
  }
}

function statusLabel(s) {
  return s === 'ok' ? '完成' : s === 'running' ? '运行中' : s === 'error' ? '失败' : s
}

function shortTime(iso) {
  return typeof iso === 'string' && iso.length >= 16 ? iso.slice(11, 16) : iso || ''
}

onMounted(async () => {
  await refreshStatus() // 刷新恢复：active 则接续轮询，否则展示最近完成态
  loadHistory()
})

onUnmounted(stopPolling)
</script>
