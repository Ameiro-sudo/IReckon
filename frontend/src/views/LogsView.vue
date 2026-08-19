<template>
  <div class="view-root">
    <PageHeader title="系统日志" subtitle="后端实时日志流（WebSocket 推送 + 历史加载）">
      <template #actions>
        <button class="btn btn-secondary" @click="reload">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polyline points="23 4 23 10 17 10"/><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"/></svg>
          重载历史
        </button>
      </template>
    </PageHeader>

    <div class="fill-view">
      <LogViewer ref="viewerRef" />
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import { useTaskStore } from '../stores/taskStore.js'
import PageHeader from '../components/PageHeader.vue'
import LogViewer from '../components/LogViewer.vue'

const taskStore = useTaskStore()
const viewerRef = ref(null)

onMounted(() => taskStore.stopPolling())
onUnmounted(() => taskStore.startPolling())

function reload() {
  viewerRef.value?.reload()
}
</script>
