<template>
  <div class="view-root">
    <PageHeader title="AI 实例" subtitle="管理 AI 模型连接与能力实例">
    <template #actions>
      <button class="btn btn-primary" @click="openCreate">
        <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        添加实例
      </button>
    </template>
  </PageHeader>

  <div class="inst-grid">
    <div v-for="inst in instances" :key="inst.id" class="panel inst-card card-hover">
      <div class="inst-top">
        <div class="inst-avatar">{{ inst.name?.charAt(0) || '?' }}</div>
        <div class="inst-info">
          <div class="inst-name overflow-ellipsis">{{ inst.name }}</div>
          <div class="mono inst-model overflow-ellipsis">{{ inst.model }}</div>
        </div>
        <span class="pill" :class="inst.enabled ? 'st-completed' : 'st-paused'">{{ inst.enabled ? '启用' : '禁用' }}</span>
        <span v-if="inst.has_key" class="pill st-key" title="已配置 API Key">密钥已配置</span>
      </div>

      <div class="inst-details">
        <div class="detail-row">
          <span class="detail-label">Endpoint</span>
          <span class="mono detail-value overflow-ellipsis" :title="inst.endpoint">{{ inst.endpoint }}</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">价格</span>
          <span class="mono">${{ inst.cost_per_1k_tokens }}/1k tokens</span>
        </div>
        <div class="detail-row">
          <span class="detail-label">上下文</span>
          <span class="mono">{{ formatContext(inst.max_context) }}</span>
        </div>
        <div class="detail-row" v-if="inst.tags?.length">
          <span class="detail-label">标签</span>
          <span class="tags">
            <span v-for="tag in inst.tags.slice(0, 6)" :key="tag" class="tag mono">{{ tag }}</span>
            <span v-if="inst.tags.length > 6" class="tag mono text-muted">+{{ inst.tags.length - 6 }}</span>
          </span>
        </div>
      </div>

      <div v-if="testResults[inst.id]" class="test-result" :class="testResults[inst.id].status === 'reachable' ? 'ok' : 'bad'">
        <span class="test-dot"></span>
        <span class="text-sm" v-if="testResults[inst.id].status === 'reachable'">
          可达 (HTTP {{ testResults[inst.id].http_status }})
        </span>
        <span class="text-sm overflow-ellipsis" v-else :title="testResults[inst.id].error">
          不可达: {{ testResults[inst.id].error }}
        </span>
        <button class="btn btn-ghost btn-icon" style="margin-left: auto;" @click="clearTest(inst.id)">×</button>
      </div>

      <div class="inst-actions">
        <button class="btn btn-secondary btn-sm" :disabled="testingId === inst.id" @click="testInstance(inst.id)">
          {{ testingId === inst.id ? '测试中...' : '测试' }}
        </button>
        <button class="btn btn-secondary btn-sm" @click="openEdit(inst)">编辑</button>
        <button class="btn btn-danger btn-sm" @click="deleteInstance(inst.id)">删除</button>
      </div>
    </div>

    <div v-if="!instances.length" class="panel empty-state" style="grid-column: 1 / -1;">
      <div class="empty-icon">
        <svg width="19" height="19" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3"/></svg>
      </div>
      <p>暂无 AI 实例</p>
      <button class="btn btn-primary btn-sm" @click="openCreate">添加第一个实例</button>
    </div>
  </div>

  <Teleport to="body">
    <div v-if="showModal" class="modal-overlay" @click.self="closeModal">
      <div class="modal">
        <h2 class="modal-title">{{ editingInstance ? '编辑实例' : '添加实例' }}</h2>
        <p class="modal-desc">OpenAI 兼容端点可直接接入，API Key 将加密存储。</p>
        <form @submit.prevent="saveInstance">
          <div class="form-group">
            <label class="form-label">名称</label>
            <input v-model="form.name" class="input" required />
          </div>
          <div class="form-group">
            <label class="form-label">模型</label>
            <input v-model="form.model" class="input" placeholder="gpt-4 / deepseek-v4-flash" required />
          </div>
          <div class="form-group">
            <label class="form-label">Endpoint</label>
            <input v-model="form.endpoint" class="input" placeholder="https://api.example.com/v1" required />
          </div>
          <div class="form-group">
            <label class="form-label">API Key</label>
            <input v-model="form.api_key" class="input" type="password" placeholder="sk-..." autocomplete="new-password" />
            <div v-if="editingInstance?.has_key" class="text-xs text-muted" style="margin-top: 4px;">留空表示保持不变，已配置密钥</div>
          </div>
          <div class="flex gap-12">
            <div class="form-group" style="flex: 1;">
              <label class="form-label">最大上下文</label>
              <input v-model.number="form.max_context" class="input" type="number" />
            </div>
            <div class="form-group" style="flex: 1;">
              <label class="form-label">价格 ($/1k tokens)</label>
              <input v-model.number="form.cost_per_1k_tokens" class="input" type="number" step="0.001" />
            </div>
          </div>
          <div class="form-group">
            <label class="form-label">标签 (逗号分隔)</label>
            <input v-model="tagsInput" class="input" placeholder="python, coding, smart" />
          </div>
          <div class="form-group">
            <label class="switch-label">
              <input type="checkbox" v-model="form.enabled" />
              <span class="switch-track"><span class="switch-thumb"></span></span>
              启用
            </label>
          </div>
          <div class="form-actions">
            <button type="button" class="btn btn-secondary" @click="closeModal">取消</button>
            <button type="submit" class="btn btn-primary">保存</button>
          </div>
        </form>
      </div>
    </div>
  </Teleport>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { aiInstanceAPI } from '../api/index.js'
import { useToast } from '../composables/useToast.js'
import PageHeader from '../components/PageHeader.vue'

const toast = useToast()
const instances = ref([])
const showModal = ref(false)
const editingInstance = ref(null)
const testingId = ref(null)
const tagsInput = ref('')
const testResults = reactive({})
const form = ref(emptyForm())

function emptyForm() {
  return { name: '', endpoint: '', model: '', api_key: '', max_context: 4096, cost_per_1k_tokens: 0, tags: [], enabled: true }
}

onMounted(fetchInstances)

async function fetchInstances() {
  try {
    instances.value = (await aiInstanceAPI.list()).data
  } catch (e) {
    toast.error('加载实例失败: ' + e.message)
  }
}

function openCreate() {
  editingInstance.value = null
  form.value = emptyForm()
  tagsInput.value = ''
  showModal.value = true
}

function openEdit(inst) {
  editingInstance.value = inst
  form.value = { ...inst, api_key: '' }
  tagsInput.value = inst.tags?.join(', ') || ''
  showModal.value = true
}

function closeModal() {
  showModal.value = false
  editingInstance.value = null
}

async function saveInstance() {
  form.value.tags = tagsInput.value.split(',').map(t => t.trim()).filter(Boolean)
  const payload = { ...form.value }
  if (editingInstance.value && !payload.api_key.trim()) {
    delete payload.api_key
  }
  try {
    if (editingInstance.value) {
      await aiInstanceAPI.update(editingInstance.value.id, payload)
      toast.success('实例已更新')
    } else {
      await aiInstanceAPI.create(payload)
      toast.success('实例已添加')
    }
    await fetchInstances()
    closeModal()
  } catch (e) {
    toast.error('保存失败: ' + (e.response?.data?.detail || e.message))
  }
}

async function testInstance(id) {
  testingId.value = id
  try {
    const res = await aiInstanceAPI.test(id)
    testResults[id] = res.data
    if (res.data.status === 'reachable') toast.success('端点可达')
    else toast.warning('端点不可达')
  } catch (e) {
    testResults[id] = { status: 'unreachable', error: e.message }
    toast.error('测试失败: ' + e.message)
  } finally {
    testingId.value = null
  }
}

function clearTest(id) {
  delete testResults[id]
}

async function deleteInstance(id) {
  if (!confirm('确定删除?')) return
  try {
    await aiInstanceAPI.delete(id)
    await fetchInstances()
    toast.success('实例已删除')
  } catch (e) {
    toast.error('删除失败: ' + e.message)
  }
}

function formatContext(n) {
  return n >= 1024 ? `${Math.round(n / 1024)}k` : String(n)
}
</script>

<style scoped>
.inst-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 12px;
}

.inst-card {
  display: flex;
  flex-direction: column;
  gap: 12px;
  padding: 18px;
}

.inst-top {
  display: flex;
  align-items: center;
  gap: 12px;
}

.inst-avatar {
  width: 36px;
  height: 36px;
  border-radius: 9px;
  background: var(--accent);
  color: var(--accent-contrast);
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 15px;
  flex-shrink: 0;
}

.st-key {
  background: var(--success-soft);
  color: var(--success);
}

.inst-info {
  flex: 1;
  min-width: 0;
}

.inst-name {
  font-size: 14px;
  font-weight: 600;
}

.inst-model {
  font-size: 11px;
  color: var(--text-muted);
}

.inst-details {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 11px 13px;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius-lg);
  font-size: 12px;
}

.detail-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: 8px;
}

.detail-label {
  color: var(--text-muted);
  flex-shrink: 0;
}

.detail-value {
  max-width: 55%;
  color: var(--text-secondary);
}

.tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
  justify-content: flex-end;
}

.tag {
  font-size: 10px;
  padding: 1px 7px;
  border-radius: 4px;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  color: var(--text-secondary);
}

.test-result {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 8px 12px;
  border-radius: var(--radius);
  min-width: 0;
}

.test-result.ok {
  background: var(--success-soft);
  color: var(--success);
}

.test-result.bad {
  background: var(--error-soft);
  color: var(--error);
}

.test-dot {
  width: 7px;
  height: 7px;
  border-radius: 50%;
  flex-shrink: 0;
}

.test-result.ok .test-dot { background: var(--success); }
.test-result.bad .test-dot { background: var(--error); }

.inst-actions {
  display: flex;
  gap: 8px;
}

.inst-actions .btn { flex: 1; }
</style>
