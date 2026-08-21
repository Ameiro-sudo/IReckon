<template>
  <div class="flex min-h-0 flex-col">
    <div class="flex items-center justify-between border-b border-line px-3.5 py-2.5">
      <span class="eyebrow">任务队列</span>
      <span class="font-mono text-xs text-ink-3">{{ tasks.length }}</span>
    </div>

    <div class="border-b border-line p-2.5">
      <input v-model="search" class="input" placeholder="搜索任务..." aria-label="搜索任务" />
    </div>

    <div class="min-h-0 flex-1 overflow-y-auto p-1.5" role="listbox" aria-label="任务列表">
      <button
        v-for="task in filteredTasks"
        :key="task.task_id"
        class="sig mb-0.5 w-full rounded-md border border-transparent px-2.5 py-2 text-left transition-colors duration-100 hover:bg-hover"
        :class="{ 'on border-accent-border bg-accent-soft': isActive(task) }"
        role="option"
        :aria-selected="isActive(task)"
        :aria-label="taskTitle(task)"
        :title="task.user_request"
        @click="$emit('update:modelValue', task)"
      >
        <div class="flex items-center justify-between gap-2">
          <span
            class="truncate text-[13px]"
            :class="isActive(task) ? 'font-semibold text-accent' : 'font-medium text-ink'"
          >{{ taskTitle(task) }}</span>
          <StatusPill :status="task.status" />
        </div>
        <div v-if="showMeta" class="mt-0.5 flex items-center justify-between text-[11px] text-ink-3">
          <span>{{ timeHM(task.created_at) }}</span>
          <span v-if="task.tokens" class="font-mono">{{ task.tokens.toLocaleString() }}</span>
        </div>
      </button>

      <div v-if="!filteredTasks.length" class="px-3 py-8 text-center text-[13px] text-ink-3">
        {{ tasks.length ? '无匹配任务' : emptyText }}
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, ref } from 'vue'
import { taskTitle } from '../utils/task.js'
import { timeHM } from '../utils/format.js'
import StatusPill from './StatusPill.vue'

// 共享任务侧栏：聊天工作台与产物浏览器共用同一条任务轨道。
// 无自带外框，由宿主容器提供边框/圆角/底色（聊天为独立卡片，产物浏览器嵌入分栏）。
const props = defineProps({
  tasks: { type: Array, required: true },
  modelValue: { type: Object, default: null },
  showMeta: { type: Boolean, default: false },
  emptyText: { type: String, default: '暂无任务' }
})

defineEmits(['update:modelValue'])

const search = ref('')

const filteredTasks = computed(() => {
  const q = search.value.toLowerCase()
  if (!q) return props.tasks
  return props.tasks.filter(t => (t.user_request || '').toLowerCase().includes(q))
})

function isActive(task) {
  return props.modelValue?.task_id === task.task_id
}
</script>
