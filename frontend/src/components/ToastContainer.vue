<template>
  <Teleport to="body">
    <div class="pointer-events-none fixed top-4 right-4 z-[200] flex max-w-[340px] flex-col gap-2" role="status" aria-live="polite">
      <TransitionGroup name="toast">
        <div
          v-for="t in toasts"
          :key="t.id"
          class="pointer-events-auto flex cursor-pointer items-start gap-2.5 rounded-lg border border-line-strong bg-surface px-3.5 py-2.5 text-[13px] text-ink shadow-md"
          @click="dismiss(t.id)"
        >
          <span
            class="mt-px shrink-0"
            :class="{
              'text-success': t.type === 'success',
              'text-error': t.type === 'error',
              'text-warning': t.type === 'warning',
              'text-info': t.type === 'info'
            }"
          >
            <AppIcon :name="iconName(t.type)" :size="14" :stroke-width="2.2" />
          </span>
          <span>{{ t.message }}</span>
        </div>
      </TransitionGroup>
    </div>
  </Teleport>
</template>

<script setup>
import { useToast } from '../composables/useToast.js'
import AppIcon from './ui/AppIcon.vue'

const { toasts, dismiss } = useToast()

function iconName(type) {
  return { success: 'success', error: 'error', warning: 'alert' }[type] || 'info'
}
</script>
