<template>
  <div v-if="board" class="flex min-w-0 flex-col gap-3.5">
    <div class="flex items-center justify-between">
      <span class="eyebrow">任务看板</span>
      <StatusPill :status="phaseStatus" />
    </div>

    <div class="rounded-md border border-line bg-subtle p-3">
      <div class="progress-track">
        <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
      </div>
      <div class="mt-1.5 flex items-center justify-between">
        <span class="text-xs text-ink-3">阶段 {{ (board.current_stage || 0) + 1 }}/{{ board.total_stages || 1 }} · {{ board.stage_name || '待规划' }}</span>
        <span class="font-mono text-xs font-semibold text-accent">{{ progressPercent }}%</span>
      </div>
    </div>

    <p v-if="board.stage_goal" class="text-xs leading-relaxed text-ink-2">{{ board.stage_goal }}</p>

    <div v-if="board.expected_artifacts?.length">
      <div class="eyebrow mb-2">预期产出</div>
      <div class="flex flex-wrap gap-1.5">
        <span
          v-for="a in board.expected_artifacts"
          :key="a"
          class="rounded-full border border-accent-border bg-accent-soft px-2.5 py-px font-mono text-[11px] text-accent"
        >{{ a }}</span>
      </div>
    </div>

    <div v-if="board.completed_work?.length">
      <div class="eyebrow mb-2">已完成</div>
      <div class="flex flex-col gap-1.5">
        <div v-for="(w, i) in board.completed_work" :key="i" class="flex items-start gap-2 text-xs leading-relaxed text-success">
          <span class="mt-px flex size-[15px] shrink-0 items-center justify-center rounded border border-success/30 bg-success-soft">
            <AppIcon name="check" :size="10" :stroke-width="3" />
          </span>
          {{ w }}
        </div>
      </div>
    </div>

    <div v-if="board.pending_actions?.length">
      <div class="eyebrow mb-2">待办</div>
      <div class="flex flex-col gap-1.5">
        <div v-for="(p, i) in board.pending_actions" :key="i" class="flex items-start gap-2 text-xs leading-relaxed text-ink-2">
          <span class="mt-1.5 size-[7px] shrink-0 rounded-full bg-warning"></span>
          {{ p }}
        </div>
      </div>
    </div>

    <p v-if="board.notes" class="text-[11px] text-ink-3 italic">{{ board.notes }}</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import { phaseBonus } from '../utils/task.js'
import StatusPill from './StatusPill.vue'
import AppIcon from './ui/AppIcon.vue'

const props = defineProps({
  board: { type: Object, default: null }
})

const KNOWN_PHASES = ['planning', 'executing', 'reviewing', 'revising', 'delivering', 'completed', 'failed', 'pending']

const phaseStatus = computed(() => {
  const phase = props.board?.phase
  return KNOWN_PHASES.includes(phase) ? phase : 'planning'
})

const progressPercent = computed(() => {
  if (!props.board) return 0
  const total = Math.max(1, props.board.total_stages || 1)
  const stage = Math.min(props.board.current_stage || 0, total - 1)
  const base = (stage / total) * 100
  return Math.min(100, Math.round(base + (phaseBonus[props.board.phase] || 0) * 100 / total))
})
</script>
