<template>
  <div class="view-root">
    <PageHeader title="自我进化" subtitle="AI 自主分析代码并生成改进" content-class="max-w-[680px]">
      <template #actions>
        <button class="btn btn-secondary" :disabled="!lastResult || pushing" @click="pushChanges">
          {{ pushing ? '推送中...' : '推送分支' }}
        </button>
        <button class="btn btn-primary" :disabled="analyzing" @click="analyze">
          {{ analyzing ? '分析中...' : '开始分析' }}
        </button>
      </template>
    </PageHeader>

    <div class="max-w-[680px] pb-3">
      <div class="panel">
        <div class="plate">进化引擎</div>
        <p class="plate-desc">让 IReckon 分析自身代码，识别优化机会并自动生成改进方案。分析完成后可推送独立分支到远程仓库。</p>

        <div v-if="analyzing" class="mt-3">
          <div class="progress-track">
            <div class="progress-fill w-[40%] animate-[indeterminate_1.4s_infinite_ease-in-out]"></div>
          </div>
          <p class="mt-2 text-[13px] text-ink-3">AI 正在检查代码...</p>
        </div>

        <div v-if="lastResult" class="mt-2 flex flex-col gap-2.5">
          <div class="flex gap-2.5 text-[13px]">
            <span class="w-[70px] shrink-0 text-ink-3">分析摘要</span>
            <span>{{ lastResult.analysis || '—' }}</span>
          </div>
          <div v-if="lastResult.branch" class="flex items-center gap-2.5 text-[13px]">
            <span class="w-[70px] shrink-0 text-ink-3">分支</span>
            <code class="rounded-md border border-line bg-subtle px-2 py-0.5 font-mono text-xs">{{ lastResult.branch }}</code>
          </div>
          <div v-if="lastResult.files_changed?.length" class="flex gap-2.5 text-[13px]">
            <span class="w-[70px] shrink-0 text-ink-3">修改文件</span>
            <span>{{ lastResult.files_changed.length }} 个</span>
          </div>
          <div v-if="lastResult.files_changed?.length" class="mt-1 flex flex-col gap-1">
            <div v-for="file in lastResult.files_changed" :key="file" class="rounded-md border border-line bg-subtle px-2.5 py-1.5 font-mono text-xs text-ink-2">
              {{ file }}
            </div>
          </div>
          <div v-if="lastResult.status === 'ok'" class="flex items-center gap-1.5 text-[13px] font-semibold text-success">
            <AppIcon name="check" :size="13" :stroke-width="2.2" />
            分析完成
          </div>
        </div>

        <div v-if="error" class="mt-3.5 rounded-md bg-error-soft px-3.5 py-2.5 text-error">
          <p class="text-[13px]">{{ error }}</p>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { selfImproveAPI } from '../api/index.js'
import { useToast } from '../composables/useToast.js'
import PageHeader from '../components/PageHeader.vue'
import AppIcon from '../components/ui/AppIcon.vue'

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
