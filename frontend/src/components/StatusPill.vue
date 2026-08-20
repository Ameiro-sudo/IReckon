<template>
  <span class="pill" :class="`st-${status}`">{{ label }}</span>
</template>

<script setup>
import {computed} from 'vue'

const props = defineProps({
  status: { type: String, required: true }
})

const labels = {
  pending: '排队中', planning: '规划中', executing: '执行中', reviewing: '审查中',
  revising: '修订中', delivering: '交付中', completed: '已完成', failed: '失败', paused: '已暂停'
}

const label = computed(() => labels[props.status] || props.status)
</script>
