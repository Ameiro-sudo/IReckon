<template>
  <div class="page-view">
    <div class="page-header">
      <div>
        <h1 class="page-title">AI 实例</h1>
        <p class="page-subtitle">管理 AI 模型连接与能力实例</p>
      </div>
      <button class="btn btn-primary" @click="openCreate">
        <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5"><line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/></svg>
        添加实例
      </button>
    </div>

    <div class="instances-grid">
      <div v-for="inst in instances" :key="inst.id" class="instance-card card">
        <div class="instance-top">
          <div class="instance-avatar">{{ inst.name?.charAt(0) || '?' }}</div>
          <div class="instance-info">
            <span class="instance-name">{{ inst.name }}</span>
            <span class="instance-model">{{ inst.model }}</span>
          </div>
          <span class="badge" :class="inst.enabled ? 'badge-success' : 'badge-warning'">
            {{ inst.enabled ? '启用' : '禁用' }}
          </span>
        </div>

        <div class="instance-details">
          <div class="detail-row">
            <span class="detail-label">Endpoint</span>
            <span class="detail-value">{{ inst.endpoint }}</span>
          </div>
          <div class="detail-row">
            <span class="detail-label">Tokens</span>
            <span class="detail-value">${{ inst.cost_per_1k_tokens }}/1k</span>
          </div>
          <div class="detail-row" v-if="inst.tags?.length">
            <span class="detail-label">标签</span>
            <span class="detail-tags">
              <span v-for="tag in inst.tags" :key="tag" class="tag">{{ tag }}</span>
            </span>
          </div>
        </div>

        <div class="instance-actions">
          <button class="btn btn-secondary btn-sm" @click="testInstance(inst.id)">
            {{ testingId === inst.id ? '...' : '测试' }}
          </button>
          <button class="btn btn-secondary btn-sm" @click="openEdit(inst)">编辑</button>
          <button class="btn btn-danger btn-sm" @click="deleteInstance(inst.id)">删除</button>
        </div>
      </div>

      <div v-if="!instances.length" class="empty-state" style="grid-column: 1 / -1;">
        <div class="empty-icon">
          <svg width="48" height="48" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 2a10 10 0 0 1 10 10c0 2.5-1 4.8-2.6 6.5"/><path d="M12 2a10 10 0 0 0-7.4 16.5"/><circle cx="12" cy="12" r="3"/></svg>
        </div>
        <p>暂无 AI 实例</p>
        <button class="btn btn-primary" @click="openCreate">添加第一个实例</button>
      </div>
    </div>

    <Teleport to="body">
      <div v-if="showModal" class="modal-overlay" @click.self="closeModal">
        <div class="modal card">
          <h2 class="modal-title">{{ editingInstance ? '编辑实例' : '添加实例' }}</h2>
          <form @submit.prevent="saveInstance">
            <div class="form-row">
              <div class="form-group flex-1">
                <label>名称</label>
                <input v-model="form.name" class="input" required />
              </div>
              <div class="form-group flex-1">
                <label>模型</label>
                <input v-model="form.model" class="input" placeholder="gpt-4" required />
              </div>
            </div>
            <div class="form-group">
              <label>Endpoint</label>
              <input v-model="form.endpoint" class="input" placeholder="https://api.example.com/v1" required />
            </div>
            <div class="form-group">
              <label>API Key</label>
              <input v-model="form.api_key" class="input" type="password" placeholder="sk-..." />
            </div>
            <div class="form-row">
              <div class="form-group flex-1">
                <label>最大上下文</label>
                <input v-model.number="form.max_context" class="input" type="number" />
              </div>
              <div class="form-group flex-1">
                <label>价格 /1k tokens</label>
                <input v-model.number="form.cost_per_1k_tokens" class="input" type="number" step="0.001" />
              </div>
            </div>
            <div class="form-group">
              <label>标签 (逗号分隔)</label>
              <input v-model="tagsInput" class="input" placeholder="python, coding, smart" />
            </div>
            <div class="form-group">
              <label class="switch-label">
                <input type="checkbox" v-model="form.enabled" />
                <span class="switch-track">
                  <span class="switch-thumb"></span>
                </span>
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
import { ref, onMounted } from 'vue'
import { aiInstanceAPI } from '../api/index.js'

const instances = ref([])
const showModal = ref(false)
const editingInstance = ref(null)
const testingId = ref(null)
const tagsInput = ref('')

const form = ref(emptyForm())

function emptyForm() {
  return { name: '', endpoint: '', model: '', api_key: '', max_context: 4096, cost_per_1k_tokens: 0, tags: [], enabled: true }
}

onMounted(fetchInstances)

async function fetchInstances() {
  try {
    const res = await aiInstanceAPI.list()
    instances.value = res.data
  } catch {}
}

function openCreate() {
  editingInstance.value = null
  form.value = emptyForm()
  tagsInput.value = ''
  showModal.value = true
}

function openEdit(inst) {
  editingInstance.value = inst
  form.value = { ...inst }
  tagsInput.value = inst.tags?.join(', ') || ''
  showModal.value = true
}

function closeModal() {
  showModal.value = false
  editingInstance.value = null
}

async function saveInstance() {
  form.value.tags = tagsInput.value.split(',').map(t => t.trim()).filter(t => t)
  try {
    if (editingInstance.value) {
      await aiInstanceAPI.update(editingInstance.value.id, form.value)
    } else {
      await aiInstanceAPI.create(form.value)
    }
    await fetchInstances()
    closeModal()
  } catch (e) { alert('保存失败: ' + e.message) }
}

async function testInstance(id) {
  testingId.value = id
  try {
    const res = await aiInstanceAPI.test(id)
    alert(`测试结果: ${res.data.status}`)
  } catch (e) { alert('测试失败: ' + e.message) }
  finally { testingId.value = null }
}

async function deleteInstance(id) {
  if (!confirm('确定删除?')) return
  try {
    await aiInstanceAPI.delete(id)
    await fetchInstances()
  } catch (e) { alert('删除失败: ' + e.message) }
}
</script>

<style scoped>
.instances-grid {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(340px, 1fr));
  gap: 16px;
}

.instance-card {
  display: flex;
  flex-direction: column;
  gap: 14px;
  transition: all 0.3s cubic-bezier(0.4, 0, 0.2, 1);
  position: relative;
  overflow: hidden;
}

.instance-card:hover {
  transform: translateY(-2px);
  box-shadow: var(--shadow-md);
}

.instance-card::before {
  content: '';
  position: absolute;
  top: 0;
  left: 0;
  right: 0;
  height: 2px;
  background: var(--accent-gradient);
  opacity: 0;
  transition: opacity 0.3s ease;
}

.instance-card:hover::before {
  opacity: 1;
}

.instance-top {
  display: flex;
  align-items: center;
  gap: 12px;
}

.instance-avatar {
  width: 44px;
  height: 44px;
  border-radius: 12px;
  background: var(--accent-gradient);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 16px;
  font-weight: 700;
  color: white;
  flex-shrink: 0;
  box-shadow: 0 2px 8px rgba(60, 150, 202, 0.2);
}

.instance-info {
  flex: 1;
  display: flex;
  flex-direction: column;
}

.instance-name {
  font-size: 15px;
  font-weight: 600;
}

.instance-model {
  font-size: 12px;
  color: var(--text-muted);
}

.instance-details {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: 10px 12px;
  background: var(--bg-glass);
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
  border: 1px solid var(--glass-border-subtle);
  border-radius: var(--radius-md);
}

.detail-row {
  display: flex;
  justify-content: space-between;
  font-size: 12px;
}

.detail-label {
  color: var(--text-muted);
}

.detail-value {
  color: var(--text-primary);
  font-family: 'JetBrains Mono', monospace;
  font-size: 12px;
  max-width: 180px;
  overflow: hidden;
  text-overflow: ellipsis;
}

.detail-tags {
  display: flex;
  gap: 4px;
  flex-wrap: wrap;
}

.tag {
  padding: 2px 8px;
  background: var(--bg-glass);
  backdrop-filter: blur(4px);
  -webkit-backdrop-filter: blur(4px);
  border-radius: 8px;
  font-size: 11px;
  color: var(--text-secondary);
}

.instance-actions {
  display: flex;
  gap: 8px;
}

.instance-actions .btn { flex: 1; }

.btn-sm { padding: 5px 12px; font-size: 12px; }

.modal-overlay {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.5);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 100;
  backdrop-filter: blur(8px);
  -webkit-backdrop-filter: blur(8px);
}

.modal {
  width: 520px;
  max-width: 92vw;
  max-height: 88vh;
  overflow-y: auto;
  animation: modalIn 0.2s ease;
}

@keyframes modalIn {
  from {
    opacity: 0;
    transform: scale(0.95) translateY(10px);
  }
  to {
    opacity: 1;
    transform: scale(1) translateY(0);
  }
}

.modal-title {
  font-size: 18px;
  font-weight: 600;
  margin-bottom: 20px;
  font-family: 'Noto Serif SC', serif;
}

.form-row {
  display: flex;
  gap: 14px;
}

.form-group {
  margin-bottom: 14px;
}

.form-group label {
  display: block;
  font-size: 12px;
  font-weight: 500;
  margin-bottom: 5px;
  color: var(--text-secondary);
}

.flex-1 { flex: 1; }

.form-actions {
  display: flex;
  gap: 10px;
  justify-content: flex-end;
  margin-top: 20px;
}

.switch-label {
  display: flex !important;
  align-items: center;
  gap: 10px;
  cursor: pointer;
  font-size: 13px !important;
}

.switch-label input { display: none; }

.switch-track {
  width: 36px;
  height: 20px;
  background: var(--bg-tertiary);
  border-radius: 10px;
  position: relative;
  transition: background 0.2s;
  border: 1px solid var(--border);
}

.switch-label input:checked + .switch-track {
  background: var(--accent-gradient);
  border-color: transparent;
}

.switch-thumb {
  width: 16px;
  height: 16px;
  background: white;
  border-radius: 50%;
  position: absolute;
  top: 1px;
  left: 1px;
  transition: transform 0.2s;
}

.switch-label input:checked + .switch-track .switch-thumb {
  transform: translateX(16px);
}

@media (max-width: 480px) {
  .instances-grid { grid-template-columns: 1fr !important; }
  .instance-card { gap: 10px; }
  .instance-actions { flex-wrap: wrap; }
  .instance-actions .btn { flex: 1; min-width: 60px; }
  .modal { width: 95vw !important; }
}
</style>
