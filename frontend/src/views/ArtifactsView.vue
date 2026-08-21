<template>
  <div class="view-root">
    <PageHeader title="交付产物" subtitle="浏览所有任务生成的交付文件" />

    <div class="fill-view">
      <ArtifactBrowser />
    </div>
  </div>
</template>

<script setup>
import { onMounted, onUnmounted } from 'vue'
import { useTaskStore } from '../stores/taskStore.js'
import PageHeader from '../components/PageHeader.vue'
import ArtifactBrowser from '../components/ArtifactBrowser.vue'

const taskStore = useTaskStore()

onMounted(() => taskStore.stopPolling())
onUnmounted(() => taskStore.startPolling())
</script>
