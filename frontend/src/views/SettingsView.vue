<template>
  <div class="view-root">
    <PageHeader title="设置" subtitle="系统配置与更新管理">
    </PageHeader>

  <div class="settings-grid">
    <div class="panel">
      <div class="panel-title">更新管理</div>
      <p class="panel-desc">检查并应用系统更新</p>

      <div class="update-info" v-if="updateStatus">
        <div class="update-row">
          <span class="update-label">当前版本</span>
          <span class="mono">{{ updateStatus.current_version }}</span>
        </div>
        <div class="update-row" v-if="updateStatus.latest_version">
          <span class="update-label">最新版本</span>
          <span class="mono">{{ updateStatus.latest_version }}</span>
        </div>
        <div class="update-row">
          <span class="update-label">状态</span>
          <span v-if="updateStatus.update_available" class="pill st-warning">有可用更新</span>
          <span v-else class="pill st-completed">已是最新</span>
        </div>
      </div>

      <div class="flex gap-8" style="margin-top: 14px;">
        <button class="btn btn-secondary" :disabled="checking" @click="checkUpdate">
          {{ checking ? '检查中...' : '检查更新' }}
        </button>
        <button class="btn btn-primary" :disabled="!updateStatus?.update_available || applying" @click="applyUpdate">
          {{ applying ? '更新中...' : '立即更新' }}
        </button>
      </div>
    </div>

    <div class="panel">
      <div class="panel-title">系统配置</div>
      <p class="panel-desc">当前运行时配置（YAML，修改 config/config.yaml 后自动热重载）</p>
      <div class="config-list">
        <div v-for="(val, key) in topLevelKeys" :key="key" class="config-row">
          <span class="config-key mono">{{ key }}</span>
          <span class="config-val mono overflow-ellipsis">{{ formatValue(val) }}</span>
        </div>
        <div v-if="!topLevelKeys.length" class="text-sm text-muted" style="padding: 12px;">加载配置中...</div>
      </div>
    </div>

    <div class="panel">
      <div class="panel-title">关于</div>
      <div class="about-row">
        <span>IReckon AI Factory</span>
        <span class="mono text-muted">v{{ version }}</span>
      </div>
      <p class="text-sm text-muted" style="margin-top: 6px;">
        多智能体自主编程系统 — 由专业 AI 智能体团队完成规划、编码、审查与交付。
      </p>
    </div>
  </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { configAPI, updateAPI, healthAPI } from '../api/index.js'
import { useToast } from '../composables/useToast.js'
import PageHeader from '../components/PageHeader.vue'

const toast = useToast()
const config = ref({})
const updateStatus = ref(null)
const version = ref('—')
const checking = ref(false)
const applying = ref(false)

const topLevelKeys = computed(() => Object.keys(config.value))

onMounted(async () => {
  try {
    const [cfg, health] = await Promise.all([configAPI.get(), healthAPI.check()])
    config.value = cfg.data
    version.value = health.data?.version || '—'
  } catch {
    /* ignore */
  }
})

async function checkUpdate() {
  checking.value = true
  try {
    const res = await updateAPI.check()
    updateStatus.value = res.data
    if (res.data.update_available) toast.info(`发现新版本 v${res.data.latest_version}`)
    else toast.success('已是最新版本')
  } catch (e) {
    toast.error('检查更新失败: ' + e.message)
  } finally {
    checking.value = false
  }
}

async function applyUpdate() {
  applying.value = true
  try {
    const res = await updateAPI.apply()
    if (res.data.status === 'ok') toast.success('更新完成，请重启应用')
    else toast.error(res.data.error || '更新失败')
  } catch (e) {
    toast.error('更新失败: ' + e.message)
  } finally {
    applying.value = false
  }
}

function formatValue(val) {
  if (val && typeof val === 'object') return JSON.stringify(val).slice(0, 60)
  return String(val ?? '')
}
</script>

<style scoped>
.settings-grid {
  display: flex;
  flex-direction: column;
  gap: 12px;
  max-width: 680px;
}

.update-info {
  display: flex;
  flex-direction: column;
  gap: 8px;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  padding: 13px 15px;
}

.update-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
}

.update-label {
  color: var(--text-secondary);
}

.config-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.config-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 12px;
  padding: 7px 10px;
  background: var(--bg-subtle);
  border-radius: var(--radius);
  font-size: 12px;
}

.config-key {
  color: var(--text-secondary);
  flex-shrink: 0;
}

.config-val {
  color: var(--text);
  max-width: 60%;
}

.about-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
}
</style>