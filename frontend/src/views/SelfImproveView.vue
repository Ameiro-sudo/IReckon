<template>
  <div class="page-view">
    <div class="page-header">
      <div>
        <h1 class="page-title">自我进化</h1>
        <p class="page-subtitle">AI 自主分析代码并生成改进</p>
      </div>
    </div>

    <div class="content-grid">
      <div class="panel card">
        <h3 class="panel-title">进化引擎</h3>
        <p class="panel-desc">让 IReckon 分析自身代码，识别优化机会并自动生成改进方案。</p>
        <div class="evolve-actions">
          <button class="btn btn-primary" @click="analyze" :disabled="analyzing">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="16 3 21 3 21 8"/><line x1="4" y1="20" x2="21" y2="3"/><polyline points="21 16 21 21 16 21"/><line x1="15" y1="15" x2="21" y2="21"/><line x1="4" y1="4" x2="9" y2="9"/></svg>
            {{ analyzing ? '分析中...' : '开始分析' }}
          </button>
          <button class="btn btn-secondary" @click="pushChanges" :disabled="!lastResult || pushing">
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M18 9v12H6V9"/><polyline points="16 5 12 9 8 5"/></svg>
            {{ pushing ? '推送中...' : '推送分支' }}
          </button>
        </div>
      </div>

      <div class="panel card" v-if="analyzing">
        <h3 class="panel-title">分析进度</h3>
        <div class="progress-bar">
          <div class="progress-fill indeterminate"></div>
        </div>
        <p class="progress-text">AI 正在检查代码...</p>
      </div>

      <div class="panel card" v-if="lastResult">
        <h3 class="panel-title">分析结果</h3>
        <div class="result-info">
          <div class="result-row" v-if="lastResult.branch">
            <span class="result-label">分支</span>
            <code class="result-value">{{ lastResult.branch }}</code>
          </div>
          <div class="result-row" v-if="lastResult.files_changed">
            <span class="result-label">修改文件</span>
            <span class="result-value">{{ lastResult.files_changed.length }} 个</span>
          </div>
        </div>
        <div v-if="lastResult.files_changed?.length" class="file-list">
          <div v-for="file in lastResult.files_changed" :key="file" class="file-item">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
            {{ file }}
          </div>
        </div>
        <div class="result-success" v-if="lastResult.status === 'ok'">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><polyline points="20 6 9 17 4 12"/></svg>
          分析完成
        </div>
      </div>

      <div class="panel card" v-if="error">
        <h3 class="panel-title" style="color: var(--error);">错误</h3>
        <p class="error-text">{{ error }}</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { selfImproveAPI } from '../api/index.js'

const analyzing = ref(false)
const pushing = ref(false)
const lastResult = ref(null)
const error = ref(null)

async function analyze() {
  analyzing.value = true
  error.value = null
  lastResult.value = null
  try {
    const res = await selfImproveAPI.analyze()
    const data = res.data
    if (data.status === 'ok') {
      lastResult.value = {
        status: 'ok',
        branch: data.branch,
        files_changed: data.result?.files_changed || []
      }
    } else {
      error.value = data.error || '分析失败'
    }
  } catch (e) {
    error.value = e.message
  } finally {
    analyzing.value = false
  }
}

async function pushChanges() {
  pushing.value = true
  error.value = null
  try {
    const res = await selfImproveAPI.push()
    if (res.data.status === 'ok') {
      lastResult.value = { ...lastResult.value, pushed: true }
      alert('已成功推送到远程分支')
    }
  } catch (e) {
    error.value = e.message
  } finally {
    pushing.value = false
  }
}
</script>

<style scoped>
.content-grid {
  display: flex;
  flex-direction: column;
  gap: 16px;
  max-width: 640px;
}

.panel {
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
}

.panel:hover {
  box-shadow: var(--shadow-md);
}

.panel-title {
  font-size: 15px;
  font-weight: 600;
  margin-bottom: 10px;
  font-family: 'Noto Serif SC', serif;
}

.panel-desc {
  font-size: 13px;
  color: var(--text-secondary);
  line-height: 1.6;
  margin-bottom: 16px;
}

.evolve-actions {
  display: flex;
  gap: 10px;
}

.progress-bar {
  height: 4px;
  background: var(--bg-tertiary);
  border-radius: 2px;
  overflow: hidden;
  margin-bottom: 10px;
}

.progress-fill {
  height: 100%;
  background: var(--accent-gradient);
  border-radius: 2px;
}

.progress-fill.indeterminate {
  width: 40%;
  animation: progressIndeterminate 1.5s infinite ease-in-out;
}

@keyframes progressIndeterminate {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(350%); }
}

.progress-text {
  font-size: 12px;
  color: var(--text-muted);
}

.result-info {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
}

.result-row {
  display: flex;
  gap: 10px;
  font-size: 13px;
}

.result-label {
  color: var(--text-muted);
  min-width: 70px;
}

.result-value {
  color: var(--text-primary);
}

.result-value code {
  font-family: 'JetBrains Mono', monospace;
  background: var(--bg-glass);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 12px;
}

.file-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
  color: var(--text-secondary);
  font-family: 'JetBrains Mono', monospace;
  padding: 6px 10px;
  background: var(--bg-glass);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  border-radius: 6px;
  border: 1px solid var(--glass-border-subtle);
}

.result-success {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--success);
  padding: 8px 0;
}

.error-text {
  font-size: 13px;
  color: var(--error);
}

@media (max-width: 480px) {
  .content-grid { max-width: 100% !important; }
  .evolve-actions { flex-direction: column; }
  .evolve-actions .btn { width: 100%; }
  .result-row { flex-direction: column; gap: 2px; }
}
</style>
