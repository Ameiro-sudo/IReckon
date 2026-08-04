import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 30000
})

api.interceptors.response.use(
  response => response,
  error => {
    console.error('API Error:', error)
    return Promise.reject(error)
  }
)

export const taskAPI = {
  create: (userRequest, schedulerCapId) =>
    api.post('/tasks', { user_request: userRequest, scheduler_cap_id: schedulerCapId }),

  list: () => api.get('/tasks'),

  get: (taskId) => api.get(`/tasks/${taskId}`),

  cancel: (taskId) => api.post(`/tasks/${taskId}/cancel`),

  resume: (taskId) => api.post(`/tasks/${taskId}/resume`),

  getMessages: (taskId, layer = 'L1', since, limit = 100) =>
    api.get(`/tasks/${taskId}/messages`, { params: { layer, since, limit } }),

  sendMessage: (taskId, content, layer = 'L1') =>
    api.post(`/tasks/${taskId}/messages`, { content, layer })
}

export const aiInstanceAPI = {
  list: () => api.get('/ai-instances'),

  create: (instance) => api.post('/ai-instances', instance),

  update: (instanceId, instance) => api.put(`/ai-instances/${instanceId}`, instance),

  delete: (instanceId) => api.delete(`/ai-instances/${instanceId}`),

  test: (instanceId) => api.post(`/ai-instances/${instanceId}/test`)
}

export const configAPI = {
  get: () => api.get('/config'),

  update: (updates) => api.post('/config/update', { updates })
}

export const healthAPI = {
  check: () => api.get('/health')
}

export const selfImproveAPI = {
  analyze: () => api.post('/self-improve'),

  push: () => api.post('/self-improve/push')
}

export const updateAPI = {
  check: () => api.get('/update/check'),

  apply: () => api.post('/update/apply')
}

export function createWebSocket(taskId) {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const wsUrl = `${protocol}//${location.host}/ws/${taskId}`
  return new WebSocket(wsUrl)
}

export default api
