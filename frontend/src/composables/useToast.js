import {ref} from 'vue'

const toasts = ref([])
let seed = 0

export function useToast() {
  function show(message, type = 'info', duration = 3200) {
    const id = ++seed
    toasts.value.push({ id, message, type })
    setTimeout(() => dismiss(id), duration)
  }

  function dismiss(id) {
    toasts.value = toasts.value.filter(t => t.id !== id)
  }

  return {
    toasts,
    show,
    success: (msg) => show(msg, 'success'),
    error: (msg) => show(msg, 'error'),
    info: (msg) => show(msg, 'info'),
    warning: (msg) => show(msg, 'warning')
  }
}
