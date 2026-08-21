import axios from 'axios'

const api = axios.create({
  baseURL: '/api',
  timeout: 60000
})

api.interceptors.request.use(
  (config) => {
    const token = localStorage.getItem('ireckon_api_token')
    if (token) config.headers['X-API-Token'] = token
    return config
  },
  error => Promise.reject(error)
)

api.interceptors.response.use(
  response => response,
  error => {
    // 令牌失效/缺失：清除本地令牌并回到登录页（登录页自身的请求除外）
    if (error.response?.status === 401 && !location.pathname.startsWith('/login')) {
      localStorage.removeItem('ireckon_api_token')
      const redirect = encodeURIComponent(location.pathname + location.search)
      location.href = `/login?redirect=${redirect}`
    }
    return Promise.reject(error)
  }
)

export const taskAPI = {
  create: (userRequest, schedulerCapId, uploadId) =>
    api.post('/tasks', { user_request: userRequest, scheduler_cap_id: schedulerCapId, upload_id: uploadId }),

  list: (params = {}) => api.get('/tasks', { params }),

  get: (taskId) => api.get(`/tasks/${taskId}`),

  cancel: (taskId) => api.post(`/tasks/${taskId}/cancel`),

  resume: (taskId) => api.post(`/tasks/${taskId}/resume`),

  delete: (taskId) => api.delete(`/tasks/${taskId}`),

  getBoard: (taskId) => api.get(`/tasks/${taskId}/board`),

  getArtifacts: (taskId) => api.get(`/tasks/${taskId}/artifacts`),

  getArtifact: (taskId, path) => api.get(`/tasks/${taskId}/artifact`, { params: { path } }),

  downloadUrl: (taskId) => `/api/tasks/${taskId}/download`,

  getMessages: (taskId, layer = 'L1', since, limit = 200) =>
    api.get(`/tasks/${taskId}/messages`, { params: { layer, since, limit } }),

  sendMessage: (taskId, content, layer = 'L1') =>
    api.post(`/tasks/${taskId}/messages`, { content, layer })
}

export const aiInstanceAPI = {
  list: () => api.get('/ai-instances'),

  create: (instance) => api.post('/ai-instances', instance),

  update: (instanceId, instance) => api.put(`/ai-instances/${instanceId}`, instance),

  delete: (instanceId) => api.delete(`/ai-instances/${instanceId}`),

  test: (instanceId) => api.post(`/ai-instances/${instanceId}/test`),

  // 探测 OpenAI 兼容 /models 列表；编辑态传 instance_id 复用存量密钥
  scanModels: (payload) => api.post('/ai-instances/scan-models', payload)
}

export const configAPI = {
  get: () => api.get('/config'),

  update: (updates) => api.post('/config/update', { updates })
}

export const uploadAPI = {
  upload: (files) => {
    const form = new FormData()
    for (const f of files) form.append('files', f)
    return api.post('/uploads', form, {
      headers: { 'Content-Type': 'multipart/form-data' },
      timeout: 120000
    })
  }
}

export const healthAPI = {
  check: () => api.get('/health')
}

export const statsAPI = {
  get: () => api.get('/stats'),

  usage: () => api.get('/usage'),

  logs: (limit = 200, level) => api.get('/logs', { params: { limit, level } })
}

export const selfImproveAPI = {
  // 后台任务化：立即返回 started/busy/error，进度经 status 轮询
  analyze: () => api.post('/self-improve'),

  status: () => api.get('/self-improve/status'),

  history: () => api.get('/self-improve/history'),

  push: () => api.post('/self-improve/push')
}

export const updateAPI = {
  check: () => api.get('/update/check'),

  apply: (channel = null, silent = false) =>
    api.post('/update/apply', { channel, silent })
}

export function createWebSocket(taskId = null) {
  const protocol = location.protocol === 'https:' ? 'wss:' : 'ws:'
  const path = taskId ? `/ws/${taskId}` : '/ws'
  const token = localStorage.getItem('ireckon_api_token') || ''
  // token 走 Sec-WebSocket-Protocol 子协议头（['ireckon.v1', <token>]），
  // 不再拼进 URL——避免 token 落入反代 access_log / 浏览器历史 / Referer。
  // 无 token（回环免鉴权模式）时只带服务名，空字符串不是合法子协议必须剔除。
  const protocols = ['ireckon.v1']
  if (token) protocols.push(token)
  return new WebSocket(`${protocol}//${location.host}${path}`, protocols)
}

export default api
