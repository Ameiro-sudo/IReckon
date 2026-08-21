import { nextTick, onUnmounted, watch } from 'vue'

// 弹层无障碍组合式：ESC 关闭 / 焦点陷阱 / 开启聚焦面板 / 关闭焦点归还 / body 滚动锁(计数)
// 多层弹叠：栈顶实例才响应 ESC 与 Tab 陷阱，底层弹层不受影响。

const FOCUSABLE = 'a[href], button:not([disabled]), textarea, input, select, [tabindex]:not([tabindex="-1"])'
const stack = []
let lockCount = 0

export function useModalA11y(isOpen, panelRef, onClose, opts = {}) {
  const instance = {}
  let lastFocus = null

  instance.onKeydown = function (e) {
    if (stack[stack.length - 1] !== instance) return // 只让栈顶响应
    if (e.key === 'Escape') {
      e.stopImmediatePropagation()
      e.preventDefault()
      onClose?.()
      return
    }
    if (e.key !== 'Tab') return
    const panel = panelRef.value
    if (!panel) return
    const items = Array.from(panel.querySelectorAll(FOCUSABLE)).filter(
      el => el.offsetParent !== null || el === document.activeElement
    )
    if (!items.length) {
      e.preventDefault()
      panel.focus()
      return
    }
    const first = items[0]
    const last = items[items.length - 1]
    const active = document.activeElement
    if (e.shiftKey && (active === first || !panel.contains(active))) {
      last.focus()
      e.preventDefault()
    } else if (!e.shiftKey && (active === last || !panel.contains(active))) {
      first.focus()
      e.preventDefault()
    }
  }

  watch(
    isOpen,
    (open, was) => {
      if (open === was) return
      if (open) {
        lastFocus = document.activeElement
        stack.push(instance)
        window.addEventListener('keydown', instance.onKeydown, true)
        lockCount++
        if (lockCount === 1) document.body.style.overflow = 'hidden'
        nextTick(() => {
        const p = panelRef.value
        if (!p) return
        if (opts.focusFirstFocusable) p.querySelector(FOCUSABLE)?.focus({ preventScroll: true })
        else p.focus({ preventScroll: true })
      })
      } else {
        const i = stack.indexOf(instance)
        if (i !== -1) stack.splice(i, 1)
        window.removeEventListener('keydown', instance.onKeydown, true)
        lockCount = Math.max(0, lockCount - 1)
        if (lockCount === 0) document.body.style.overflow = ''
        if (lastFocus && document.contains(lastFocus)) {
          try { lastFocus.focus({ preventScroll: true }) } catch { /* 已不可聚焦 */ }
        }
        lastFocus = null
      }
    },
    { flush: 'post' }
  )

  onUnmounted(() => {
    const i = stack.indexOf(instance)
    if (i !== -1) stack.splice(i, 1)
    window.removeEventListener('keydown', instance.onKeydown, true)
    if (isOpen()) {
      lockCount = Math.max(0, lockCount - 1)
      if (lockCount === 0) document.body.style.overflow = ''
    }
  })
}
