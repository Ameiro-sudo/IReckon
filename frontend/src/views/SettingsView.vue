<template>
  <div class="page-view">
    <div class="page-header">
      <div>
        <h1 class="page-title">设置</h1>
        <p class="page-subtitle">系统配置与更新管理</p>
      </div>
    </div>

    <div class="settings-grid">
      <div class="section card">
        <h3 class="section-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 0 1 0 2.83 2 2 0 0 1-2.83 0l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-2 2 2 2 0 0 1-2-2v-.09A1.65 1.65 0 0 0 9 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 0 1-2.83 0 2 2 0 0 1 0-2.83l.06-.06A1.65 1.65 0 0 0 4.68 15a1.65 1.65 0 0 0-1.51-1H3a2 2 0 0 1-2-2 2 2 0 0 1 2-2h.09A1.65 1.65 0 0 0 4.6 9a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 0 1 0-2.83 2 2 0 0 1 2.83 0l.06.06A1.65 1.65 0 0 0 9 4.68a1.65 1.65 0 0 0 1-1.51V3a2 2 0 0 1 2-2 2 2 0 0 1 2 2v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 0 1 2.83 0 2 2 0 0 1 0 2.83l-.06.06A1.65 1.65 0 0 0 19.4 9a1.65 1.65 0 0 0 1.51 1H21a2 2 0 0 1 2 2 2 2 0 0 1-2 2h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>
          系统配置
        </h3>
        <div class="config-list">
          <div v-for="(val, key) in config" :key="key" class="config-row">
            <span class="config-key">{{ key }}</span>
            <span class="config-val">{{ formatValue(val) }}</span>
          </div>
          <div v-if="!Object.keys(config).length" class="config-empty">
            加载配置中...
          </div>
        </div>
      </div>

      <div class="section card">
        <h3 class="section-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
          更新管理
        </h3>
        <p class="section-desc">检查并应用系统更新</p>
        <div class="update-section">
          <div class="update-info" v-if="updateStatus">
            <div class="update-row" v-if="updateStatus.current_version">
              <span class="update-label">当前版本</span>
              <span class="update-value">{{ updateStatus.current_version }}</span>
            </div>
            <div class="update-row" v-if="updateStatus.latest_version">
              <span class="update-label">最新版本</span>
              <span class="update-value">{{ updateStatus.latest_version }}</span>
            </div>
            <div class="update-badge-row" v-if="updateStatus.update_available">
              <span class="badge badge-warning">有可用更新</span>
            </div>
            <div class="update-badge-row" v-else>
              <span class="badge badge-success">已是最新</span>
            </div>
          </div>
          <div class="update-actions">
            <button class="btn btn-secondary" @click="checkUpdate" :disabled="checking">
              {{ checking ? '检查中...' : '检查更新' }}
            </button>
            <button
              class="btn btn-primary"
              @click="applyUpdate"
              :disabled="!updateStatus?.update_available || applying"
            >
              {{ applying ? '更新中...' : '立即更新' }}
            </button>
          </div>
        </div>
      </div>

      <div class="section card">
        <h3 class="section-title">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><line x1="2" y1="12" x2="22" y2="12"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
          关于
        </h3>
        <div class="about-info">
          <div class="about-row">
            <span class="about-label">IReckon AI Factory</span>
            <span class="about-value">{{ version }}</span>
          </div>
          <p class="about-desc">多智能体自主编程系统 — AI 工厂</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { configAPI, updateAPI, healthAPI } from '../api/index.js'

const config = ref({})
const updateStatus = ref(null)
const version = ref('v1.0.0')
const checking = ref(false)
const applying = ref(false)

onMounted(async () => {
  try {
    const [cfg, health] = await Promise.all([
      configAPI.get(),
      healthAPI.check()
    ])
    config.value = cfg.data
    version.value = health.data?.version || 'v1.0.0'
  } catch {}
})

async function checkUpdate() {
  checking.value = true
  try {
    const res = await updateAPI.check()
    updateStatus.value = res.data
  } catch {} finally {
    checking.value = false
  }
}

async function applyUpdate() {
  applying.value = true
  try {
    const res = await updateAPI.apply()
    if (res.data.status === 'ok') {
      alert('更新完成，请重启应用')
    }
  } catch (e) {
    alert('更新失败: ' + e.message)
  } finally {
    applying.value = false
  }
}

function formatValue(val) {
  if (typeof val === 'object') return JSON.stringify(val)
  return String(val)
}
</script>

<style scoped>
.settings-grid {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 700px;
}

.section {
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.section:hover {
  box-shadow: var(--shadow-md);
}

.section-title {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 14px;
  font-family: 'Noto Serif SC', serif;
}

.section-desc {
  font-size: 13px;
  color: var(--text-secondary);
  margin-bottom: 12px;
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
  padding: 7px 10px;
  background: var(--bg-glass);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  border-radius: var(--radius-sm);
  font-size: 12px;
  border: 1px solid var(--glass-border-subtle);
}

.config-key {
  color: var(--text-secondary);
  font-family: 'JetBrains Mono', monospace;
}

.config-val {
  color: var(--text-primary);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  max-width: 60%;
  overflow: hidden;
  text-overflow: ellipsis;
}

.config-empty {
  text-align: center;
  color: var(--text-muted);
  font-size: 13px;
  padding: 16px;
}

.update-section {
  display: flex;
  flex-direction: column;
  gap: 14px;
}

.update-info {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.update-row {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
}

.update-label {
  color: var(--text-secondary);
}

.update-value {
  color: var(--text-primary);
  font-weight: 500;
}

.update-badge-row {
  margin-top: 4px;
}

.update-actions {
  display: flex;
  gap: 10px;
}

.about-info {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.about-row {
  display: flex;
  justify-content: space-between;
  font-size: 13px;
}

.about-label {
  font-weight: 600;
}

.about-value {
  color: var(--text-muted);
}

.about-desc {
  color: var(--text-muted);
  font-size: 12px;
}

@media (max-width: 480px) {
  .settings-grid { max-width: 100% !important; }
  .update-actions { flex-direction: column; }
  .update-actions .btn { width: 100%; }
  .config-row { flex-wrap: wrap; gap: 4px; }
  .config-val { max-width: 100% !important; }
}
</style>
