import { ref } from 'vue'

// 应用内确认对话框（替代原生 confirm）：模块级单例状态，
// 由 App.vue 挂载一次 <ConfirmDialog/>，任意处 useConfirm().confirm() 调用。
export const state = ref(null)

export function useConfirm() {
  function confirm(opts = {}) {
    return new Promise((resolve) => {
      state.value = {
        title: opts.title || '确认操作',
        message: opts.message || '',
        confirmText: opts.confirmText || '确认',
        cancelText: opts.cancelText || '取消',
        danger: opts.danger !== false,
        resolve
      }
    })
  }

  return { state, confirm }
}

export function resolveConfirm(ok) {
  state.value?.resolve(ok)
  state.value = null
}
