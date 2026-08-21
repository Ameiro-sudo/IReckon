<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="open"
        class="fixed inset-0 z-[100] flex items-center justify-center bg-overlay p-5 backdrop-blur-[3px]"
        @click.self="$emit('close')"
      >
        <div
          ref="panelRef"
          class="modal-panel"
          tabindex="-1"
          :style="width ? { width: width + 'px' } : null"
          role="dialog"
          aria-modal="true"
          :aria-label="title"
        >
          <div class="mb-5 flex items-start justify-between gap-4">
            <div class="min-w-0">
              <h2 class="font-display text-base font-bold tracking-wide text-ink">{{ title }}</h2>
              <p v-if="desc" class="mt-1 text-[13px] leading-relaxed text-ink-2">{{ desc }}</p>
            </div>
            <button class="btn btn-ghost btn-icon -mr-1.5 -mt-1 shrink-0" aria-label="关闭" @click="$emit('close')">
              <AppIcon name="x" :size="15" />
            </button>
          </div>

          <slot />

          <footer v-if="$slots.footer" class="mt-6 flex justify-end gap-2.5">
            <slot name="footer" />
          </footer>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { ref } from 'vue'
import AppIcon from './AppIcon.vue'
import { useModalA11y } from '../../composables/useModalA11y.js'

const props = defineProps({
  open: { type: Boolean, default: false },
  title: { type: String, required: true },
  desc: { type: String, default: '' },
  width: { type: Number, default: 0 }
})

const emit = defineEmits(['close'])

const panelRef = ref(null)
useModalA11y(() => props.open, panelRef, () => emit('close'))
</script>
