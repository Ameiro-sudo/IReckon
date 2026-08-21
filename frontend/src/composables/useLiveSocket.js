import { ref } from 'vue'
import { createWebSocket } from '../api/index.js'

// 共享 WebSocket 生命周期：连接代数守卫 + 指数退避重连 + 心跳应答。
// 同一时刻只持有一条连接；connect(key) 切换目标前会安全断开旧连接。
export function useLiveSocket({ onMessage } = {}) {
  const connected = ref(false)

  let ws = null
  let reconnectTimer = null
  let retries = 0
  // 连接代数：每次 open/disconnect 递增，旧连接的异步回调据此自弃，
  // 防止组件卸载/切换目标后幽灵重连与旧 socket 继续写状态
  let generation = 0
  let target = null

  function connect(key = null) {
    disconnect()
    target = key
    open()
  }

  function open() {
    const gen = ++generation
    try {
      ws = createWebSocket(target)
      ws.onopen = () => {
        if (gen !== generation) return
        connected.value = true
        retries = 0
      }
      ws.onclose = () => {
        if (gen !== generation) return
        connected.value = false
        scheduleReconnect()
      }
      ws.onmessage = (e) => {
        if (gen !== generation) return
        try {
          onMessage?.(JSON.parse(e.data))
        } catch {
          if (e.data === 'ping') {
            // readyState 守卫：非 OPEN 状态 send 会抛未捕获异常
            if (ws && ws.readyState === WebSocket.OPEN) ws.send('pong')
          }
        }
      }
      ws.onerror = () => {
        if (gen !== generation) return
        connected.value = false
      }
    } catch {
      connected.value = false
      scheduleReconnect()
    }
  }

  function scheduleReconnect() {
    if (reconnectTimer) return
    const delay = Math.min(1000 * 2 ** retries, 15000)
    retries += 1
    reconnectTimer = setTimeout(() => {
      reconnectTimer = null
      open()
    }, delay)
  }

  function disconnect() {
    ++generation
    if (reconnectTimer) {
      clearTimeout(reconnectTimer)
      reconnectTimer = null
    }
    if (ws) {
      // 先摘除全部事件处理器再 close：close() 异步触发 onclose，
      // 否则会重新调度重连，形成卸载后的幽灵连接
      ws.onopen = ws.onclose = ws.onmessage = ws.onerror = null
      try {
        ws.close()
      } catch {
        /* ignore */
      }
      ws = null
    }
    connected.value = false
  }

  return { connected, connect, disconnect }
}
