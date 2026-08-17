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
