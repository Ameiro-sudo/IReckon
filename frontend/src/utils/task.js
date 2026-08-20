export function taskTitle(task) {
  if (!task) return ''
  if (task.title && String(task.title).trim()) return task.title
  const req = task.user_request || ''
  const text = req.split('\n')[0].trim()
  return text.length > 40 ? text.slice(0, 39) + '…' : (text || '未命名任务')
}

export function truncate(text, n = 40) {
  if (!text) return ''
  return text.length > n ? text.slice(0, n - 1) + '…' : text
}

export const phaseBonus = {
  planning: 0.05, executing: 0.35, reviewing: 0.55, revising: 0.55,
  delivering: 0.8, completed: 1, failed: 1
}
