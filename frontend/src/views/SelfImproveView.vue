<template>
  <div class="view-root">
    <PageHeader title="自我进化" subtitle="AI 自主分析代码并生成改进">
    <template #actions>
      <button class="btn btn-secondary" :disabled="!lastResult || pushing" @click="pushChanges">
        {{ pushing ? '推送中...' : '推送分支' }}
      </button>
      <button class="btn btn-primary" :disabled="analyzing" @click="analyze">
        {{ analyzing ? '分析中...' : '开始分析' }}
      </button>
    </template>
  </PageHeader>

  <div class="evolve-grid">
    <div class="panel">
      <div class="panel-title">进化引擎</div>
      <p class="panel-desc">让 IReckon 分析自身代码，识别优化机会并自动生成改进方案。分析完成后可推送独立分支到远程仓库。</p>

      <div v-if="analyzing" class="analyzing">
        <div class="progress-track">
          <div class="progress-fill indeterminate"></div>
        </div>
        <p class="text-sm text-muted">AI 正在检查代码...</p>
      </div>

      <div v-if="lastResult" class="result">
        <div class="result-row">
          <span class="result-label">分析摘要</span>
          <span class="text-sm">{{ lastResult.analysis || '—' }}</span>
        </div>
        <div class="result-row" v-if="lastResult.branch">
          <span class="result-label">分支</span>
          <code class="mono">{{ lastResult.branch }}</code>
        </div>
        <div class="result-row" v-if="lastResult.files_changed?.length">
          <span class="result-label">修改文件</span>
          <span class="text-sm">{{ lastResult.files_changed.length }} 个</span>
        </div>
        <div class="file-list" v-if="lastResult.files_changed?.length">
          <div v-for="file in lastResult.files_changed" :key="file" class="file-item mono">{{ file }}</div>
        </div>
        <div class="result-ok" v-if="lastResult.status === 'ok'">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
          分析完成
        </div>
      </div>

      <div v-if="error" class="result-error">
        <p class="text-sm">{{ error }}</p>
      </div>
    </div>
  </div>
  </div>
</template>
<script setup>
import {ref} from 'vue'
import {selfImproveAPI} from '../api/index.js'
import {useToast} from '../composables/useToast.js'
import PageHeader from '../components/PageHeader.vue'

const toast = useToast()
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
        analysis: data.analysis || '',
        branch: data.result?.branch || data.branch,
        files_changed: data.result?.files_changed || []
      }
      toast.success('分析完成')
    } else {
      error.value = data.error || '分析失败'
      toast.error(error.value)
    }
  } catch (e) {
    error.value = e.message
    toast.error('分析失败: ' + e.message)
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
      toast.success('已推送到远程分支')
    } else {
      toast.error('推送失败')
    }
  } catch (e) {
    error.value = e.message
    toast.error('推送失败: ' + e.message)
  } finally {
    pushing.value = false
  }
}
</script>

<style scoped>
.evolve-grid {
  max-width: 680px;
}

.analyzing {
  margin-top: 12px;
}

.progress-fill.indeterminate {
  width: 40%;
  animation: indeterminate 1.4s infinite ease-in-out;
}

@keyframes indeterminate {
  0% { transform: translateX(-100%); }
  100% { transform: translateX(350%); }
}

.analyzing p {
  margin-top: 8px;
}

.result {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-top: 8px;
}

.result-row {
  display: flex;
  gap: 10px;
  font-size: 13px;
}

.result-label {
  color: var(--text-muted);
  min-width: 70px;
  flex-shrink: 0;
}

.result-row code {
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  padding: 1px 8px;
  border-radius: 6px;
  font-size: 12px;
}

.file-list {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-top: 4px;
}

.file-item {
  font-size: 12px;
  color: var(--text-secondary);
  padding: 6px 10px;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.result-ok {
  display: flex;
  align-items: center;
  gap: 6px;
  color: var(--success);
  font-size: 13px;
  font-weight: 600;
}

.result-error {
  margin-top: 14px;
  padding: 10px 14px;
  border-radius: var(--radius);
  background: var(--error-soft);
  color: var(--error);
  border: 1px solid transparent;
}
</style>