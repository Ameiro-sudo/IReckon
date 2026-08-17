<template>
  <div v-if="board" class="board-panel">
    <div class="flex-between">
      <span class="board-title">任务看板</span>
      <StatusPill :status="phaseStatus" />
    </div>

    <div>
      <div class="progress-track">
        <div class="progress-fill" :style="{ width: progressPercent + '%' }"></div>
      </div>
      <div class="flex-between" style="margin-top: 5px;">
        <span class="text-xs text-muted">阶段 {{ (board.current_stage || 0) + 1 }}/{{ board.total_stages || 1 }} · {{ board.stage_name || '待规划' }}</span>
        <span class="mono text-xs" style="color: var(--accent); font-weight: 600;">{{ progressPercent }}%</span>
      </div>
    </div>

    <p v-if="board.stage_goal" class="board-goal">{{ board.stage_goal }}</p>

    <div v-if="board.expected_artifacts?.length" class="board-section">
      <div class="board-section-title">预期产出</div>
      <div class="board-chips">
        <span v-for="a in board.expected_artifacts" :key="a" class="board-chip mono">{{ a }}</span>
      </div>
    </div>

    <div v-if="board.completed_work?.length" class="board-section">
      <div class="board-section-title">已完成</div>
      <div class="board-list">
        <div v-for="(w, i) in board.completed_work" :key="i" class="board-item done">
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"/></svg>
          {{ w }}
        </div>
      </div>
    </div>

    <div v-if="board.pending_actions?.length" class="board-section">
      <div class="board-section-title">待办</div>
      <div class="board-list">
        <div v-for="(p, i) in board.pending_actions" :key="i" class="board-item">
          <span class="pending-dot"></span>
          {{ p }}
        </div>
      </div>
    </div>

    <p v-if="board.notes" class="board-notes">{{ board.notes }}</p>
  </div>
</template>

<script setup>
import { computed } from 'vue'
import StatusPill from './StatusPill.vue'

const props = defineProps({
  board: { type: Object, default: null }
})

const phaseBonus = {
  planning: 0.05, executing: 0.35, reviewing: 0.55, revising: 0.55,
  delivering: 0.8, completed: 1, failed: 1
}

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

<style scoped>
.board-panel {
  display: flex;
  flex-direction: column;
  gap: 14px;
  min-width: 0;
}

.board-title {
  font-size: 12px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-muted);
}

.board-goal {
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.6;
}

.board-section-title {
  font-size: 11px;
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.06em;
  color: var(--text-muted);
  margin-bottom: 6px;
}

.board-chips {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}

.board-chip {
  font-size: 11px;
  padding: 2px 8px;
  border-radius: var(--radius-sm);
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  color: var(--text-secondary);
}

.board-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
}

.board-item {
  display: flex;
  align-items: flex-start;
  gap: 7px;
  font-size: 12px;
  color: var(--text-secondary);
  line-height: 1.5;
}

.board-item.done {
  color: var(--success);
}

.board-item svg {
  margin-top: 3px;
  flex-shrink: 0;
}

.pending-dot {
  width: 6px;
  height: 6px;
  border-radius: 50%;
  background: var(--warning);
  margin-top: 6px;
  flex-shrink: 0;
}

.board-notes {
  font-size: 11px;
  color: var(--text-muted);
  font-style: italic;
}
</style>
