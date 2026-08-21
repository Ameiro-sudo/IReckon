<template>
  <Teleport to="body">
    <Transition name="modal">
      <div
        v-if="state"
        class="fixed inset-0 z-[110] flex items-center justify-center bg-overlay p-5 backdrop-blur-[3px]"
        @click.self="answer(false)"
      >
        <div ref="panelRef" class="modal-panel w-[400px]!" tabindex="-1" role="alertdialog" aria-modal="true" :aria-label="state.title">
          <div class="flex items-start gap-3">
            <span
              class="flex size-9 shrink-0 items-center justify-center rounded-md"
              :class="state.danger ? 'bg-error-soft text-error' : 'bg-accent-soft text-accent'"
            >
              <AppIcon :name="state.danger ? 'alert' : 'info'" :size="17" />
            </span>
            <div class="min-w-0">
              <h2 class="font-display text-[15px] font-bold tracking-wide text-ink">{{ state.title }}</h2>
              <p v-if="state.message" class="mt-1.5 text-[13px] leading-relaxed break-words text-ink-2">
                {{ state.message }}
              </p>
            </div>
          </div>

          <div class="mt-6 flex justify-end gap-2.5">
            <button class="btn btn-secondary" @click="answer(false)">{{ state.cancelText }}</button>
            <button class="btn" :class="state.danger ? 'btn-danger' : 'btn-primary'" @click="answer(true)">
              {{ state.confirmText }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>

<script setup>
import { computed, ref } from 'vue'
import { state, resolveConfirm } from '../../composables/useConfirm.js'
import AppIcon from './AppIcon.vue'
import { useModalA11y } from '../../composables/useModalA11y.js'

const panelRef = ref(null)
const isOpen = computed(() => Boolean(state.value))

function answer(ok) {
  resolveConfirm(ok)
}

// 打开时聚焦取消按钮(安全默认),ESC=取消,关闭后焦点归还触发处
// 契约：统一传 getter 函数（组合式内部虽已兼容 ref，显式 getter 意图更清晰）
useModalA11y(() => isOpen.value, panelRef, () => answer(false), { focusFirstFocusable: true })
</script>
