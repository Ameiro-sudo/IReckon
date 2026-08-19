<template>
  <Teleport to="body">
    <div v-if="visible" class="modal-overlay" @click.self="close">
      <div class="modal">
        <h2 class="modal-title">创建新任务</h2>
        <p class="modal-desc">输入自然语言需求，可附加上传参考文件，AI 智能体团队将自主完成规划、编码、审查与交付。</p>

        <div class="form-group">
          <label class="form-label">任务描述</label>
          <textarea
            v-model="request"
            class="input"
            placeholder="例如：用 Python 写一个命令行待办事项管理工具，支持增删改查和持久化存储…"
            rows="4"
            autofocus
            @keydown.ctrl.enter.prevent="submit"
            @keydown.meta.enter.prevent="submit"
          ></textarea>
          <div class="text-xs text-muted" style="margin-top: 5px;">Ctrl+Enter / ⌘+Enter 快捷提交</div>
        </div>

        <div class="form-group">
          <label class="form-label">参考文件（可选）</label>
          <div
            class="dropzone"
            :class="{ over: dragging }"
            @click="fileInput?.click()"
            @dragover.prevent="dragging = true"
            @dragleave="dragging = false"
            @drop.prevent="onDrop"
          >
            <input ref="fileInput" type="file" multiple class="hidden-input" @change="onPick" />
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>
            <span class="text-sm text-secondary">点击选择或拖拽文件到此处</span>
            <span class="text-xs text-muted">每个文件 ≤ 10MB，最多 20 个</span>
          </div>

          <div v-if="files.length" class="file-list">
            <div v-for="(f, i) in files" :key="f.name + i" class="file-item">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
              <span class="mono file-name overflow-ellipsis" :title="f.name">{{ f.name }}</span>
              <span class="mono text-muted text-xs">{{ formatSize(f.size) }}</span>
              <button type="button" class="btn btn-ghost btn-icon" @click="removeFile(i)">
                <svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>
              </button>
            </div>
          </div>
        </div>

        <div class="form-group" v-if="schedulers.length">
          <label class="form-label">调度智能体（可选）</label>
          <select v-model="schedulerCapId" class="input">
            <option value="">自动选择</option>
            <option v-for="s in schedulers" :key="s.id" :value="s.id">{{ s.name }} ({{ s.model }})</option>
          </select>
        </div>

        <div class="form-actions">
          <button class="btn btn-secondary" @click="close" :disabled="submitting">取消</button>
          <button class="btn btn-primary" @click="submit" :disabled="!request.trim() || submitting || uploading">
            <span v-if="submitting" class="btn-spinner"></span>
            {{ submitting ? '创建中...' : '创建任务' }}
          </button>
        </div>
      </div>
    </div>
  </Teleport>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { aiInstanceAPI, uploadAPI } from '../api/index.js'

const visible = ref(false)
const request = ref('')
const submitting = ref(false)
const uploading = ref(false)
const schedulerCapId = ref('')
const schedulers = ref([])
const files = ref([])
const fileInput = ref(null)
const dragging = ref(false)

const emit = defineEmits(['created'])

const MAX_FILE_SIZE = 10 * 1024 * 1024
const MAX_FILES = 20

onMounted(async () => {
  try {
    const res = await aiInstanceAPI.list()
    schedulers.value = (res.data || []).filter(i => i.enabled)
  } catch {
    schedulers.value = []
  }
})

function open() {
  request.value = ''
  submitting.value = false
  files.value = []
  visible.value = true
}

function close() {
  if (submitting.value || uploading.value) return
  visible.value = false
}

function onPick(e) {
  addFiles([...e.target.files])
  e.target.value = ''
}

function onDrop(e) {
  dragging.value = false
  addFiles([...e.dataTransfer.files])
}

function addFiles(list) {
  for (const f of list) {
    if (files.value.length >= MAX_FILES) break
    if (f.size > MAX_FILE_SIZE) continue
    if (files.value.some(x => x.name === f.name)) continue
    files.value.push(f)
  }
}

function removeFile(i) {
  files.value.splice(i, 1)
}

async function submit() {
  if (!request.value.trim() || submitting.value || uploading.value) return
  submitting.value = true
  let uploadId = null
  try {
    if (files.value.length) {
      uploading.value = true
      const res = await uploadAPI.upload(files.value)
      if (res.data.status === 'ok') uploadId = res.data.upload_id
    }
    emit('created', request.value.trim(), schedulerCapId.value || null, uploadId)
    visible.value = false
  } finally {
    uploading.value = false
    submitting.value = false
  }
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}

defineExpose({ open })
</script>

<style scoped>
.modal {
  width: 560px;
}

.btn-spinner {
  width: 12px;
  height: 12px;
  border: 2px solid rgba(255, 255, 255, 0.35);
  border-top-color: #fff;
  border-radius: 50%;
  animation: spin 0.7s linear infinite;
}

@keyframes spin {
  to { transform: rotate(360deg); }
}

.hidden-input {
  display: none;
}

.dropzone {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 5px;
  padding: 24px 16px;
  border: 1.5px dashed var(--border-strong);
  border-radius: var(--radius-lg);
  cursor: pointer;
  color: var(--text-muted);
  transition: border-color 0.15s ease, background 0.15s ease;
  text-align: center;
}

.dropzone:hover {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.dropzone.over {
  border-color: var(--accent);
  background: var(--accent-soft);
}

.file-list {
  display: flex;
  flex-direction: column;
  gap: 5px;
  margin-top: 8px;
  max-height: 140px;
  overflow-y: auto;
}

.file-item {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 10px;
  background: var(--bg-subtle);
  border: 1px solid var(--border);
  border-radius: var(--radius);
}

.file-name {
  flex: 1;
  font-size: 12px;
  color: var(--text);
}
</style>
