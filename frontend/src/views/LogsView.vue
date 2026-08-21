<template>
  <div class="view-root">
    <PageHeader title="系统日志" subtitle="后端实时日志流（WebSocket 推送 + 历史加载）">
      <template #actions>
        <button class="btn btn-secondary" @click="reload">
          <AppIcon name="refresh" :size="13" />
          重载历史
        </button>
      </template>
    </PageHeader>

    <div class="fill-view pb-4 md:pb-6">
      <LogViewer ref="viewerRef" />
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted, ref } from 'vue'
import { useTaskStore } from '../stores/taskStore.js'
import PageHeader from '../components/PageHeader.vue'
import LogViewer from '../components/LogViewer.vue'
import AppIcon from '../components/ui/AppIcon.vue'

const taskStore = useTaskStore()
const viewerRef = ref(null)

onMounted(() => taskStore.stopPolling())
onUnmounted(() => taskStore.startPolling())

function reload() {
  viewerRef.value?.reload()
}
</script>
