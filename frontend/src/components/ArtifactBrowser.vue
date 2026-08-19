<template>
  <div class="artifact-browser">
    <div class="ab-side">
      <div class="ab-task-search">
        <input v-model="searchText" class="input" placeholder="搜索任务..." />
      </div>
      <div class="ab-task-list">
        <div
          v-for="task in filteredTasks"
          :key="task.task_id"
          class="ab-task"
          :class="{ active: selected?.task_id === task.task_id }"
          @click="selectTask(task)"
          :title="task.user_request"
        >
          <span class="ab-task-name overflow-ellipsis">{{ taskTitle(task) }}</span>
          <StatusPill :status="task.status" />
        </div>
        <div v-if="!filteredTasks.length" class="text-muted text-sm" style="padding: 20px; text-align: center;">
          暂无任务
        </div>
      </div>
    </div>

    <div class="ab-main">
      <template v-if="selected">
        <div class="ab-head">
          <div class="ab-head-info">
            <div class="text-sm text-secondary overflow-ellipsis" style="max-width: 400px;">
              {{ selected.user_request?.slice(0, 60) || '无描述' }}
            </div>
            <div class="flex-center gap-8">
              <StatusPill :status="selected.status" />
              <span class="mono text-muted">{{ selected.task_id }}</span>
            </div>
          </div>
          <div class="flex-center">
            <a :href="downloadUrl" class="btn btn-secondary btn-sm" target="_blank">
              <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>
              下载 ZIP
            </a>
          </div>
        </div>

        <div class="ab-body">
          <div class="ab-files">
            <div v-if="!files.length" class="empty-state">
              <p class="text-sm">该任务暂无产物</p>
            </div>
            <div
              v-for="f in files"
              :key="f.path"
              class="ab-file"
              :class="{ active: current?.path === f.path }"
              @click="openFile(f)"
            >
              <span class="ab-file-icon">
                <svg v-if="isText(f)" width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"/><polyline points="14 2 14 8 20 8"/></svg>
                <svg v-else width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9z"/><path d="M13 2v7h7"/></svg>
              </span>
              <span class="ab-file-path mono overflow-ellipsis">{{ f.path }}</span>
              <span class="ab-file-size mono text-muted">{{ formatSize(f.size) }}</span>
            </div>
          </div>

          <div class="ab-preview">
            <template v-if="current">
              <div class="ab-preview-head">
                <span class="mono text-sm">{{ current.path }}</span>
                <span class="mono text-muted text-xs">{{ formatSize(current.size) }}</span>
              </div>
              <pre v-if="content !== null" class="ab-code"><code class="hljs" v-html="highlighted"></code></pre>
              <div v-else class="empty-state">
                <p class="text-sm">二进制或超大文件，无法预览</p>
              </div>
            </template>
            <div v-else class="empty-state">
              <p class="text-sm">选择左侧文件查看内容</p>
            </div>
          </div>
        </div>
      </template>

      <div v-else class="empty-state" style="flex: 1;">
        <p class="text-sm">选择左侧任务查看交付产物</p>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { useTaskStore } from '../stores/taskStore.js'
import { taskAPI } from '../api/index.js'
import { highlightCode } from '../utils/markdown.js'
import { taskTitle } from '../utils/task.js'
import StatusPill from './StatusPill.vue'

const taskStore = useTaskStore()
const tasks = computed(() => taskStore.tasks)
const selected = ref(null)
const files = ref([])
const current = ref(null)
const content = ref(null)
const searchText = ref('')

const TEXT_EXTS = ['py', 'js', 'ts', 'vue', 'json', 'yaml', 'yml', 'toml', 'md', 'txt', 'html', 'css', 'sh', 'bat', 'sql', 'xml', 'ini', 'env', 'cfg', 'log', 'tsx', 'jsx', 'dockerfile', 'gitignore']

const filteredTasks = computed(() => {
  const q = searchText.value.toLowerCase()
  if (!q) return tasks.value
  return tasks.value.filter(t => (t.user_request || '').toLowerCase().includes(q))
})

const downloadUrl = computed(() => selected.value ? taskAPI.downloadUrl(selected.value.task_id) : '#')

const highlighted = computed(() => {
  if (content.value === null || !current.value) return ''
  return highlightCode(content.value, current.value.path)
})

onMounted(() => taskStore.fetchTasks())

async function selectTask(task) {
  selected.value = task
  files.value = []
  current.value = null
  content.value = null
  try {
    const res = await taskAPI.getArtifacts(task.task_id)
    files.value = res.data.files || []
  } catch {
    /* ignore */
  }
}

function isText(f) {
  const ext = f.path.split('.').pop()?.toLowerCase()
  return TEXT_EXTS.includes(ext) || !f.path.includes('.')
}

async function openFile(f) {
  current.value = f
  content.value = null
  if (!isText(f) || f.size > 512 * 1024) return
  try {
    const res = await taskAPI.getArtifact(selected.value.task_id, f.path)
    if (res.data.truncated) return
    content.value = res.data.content
  } catch {
    content.value = null
  }
}

function formatSize(bytes) {
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
  return `${(bytes / 1024 / 1024).toFixed(2)} MB`
}
</script>

<style scoped>
.artifact-browser {
  display: flex;
  height: 100%;
  min-height: 0;
  background: var(--bg-surface);
  border: 1px solid var(--border);
  border-radius: var(--radius-xl);
  overflow: hidden;
}

.ab-side {
  width: 280px;
  flex-shrink: 0;
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  min-height: 0;
  background: var(--bg-subtle);
}

.ab-task-search {
  padding: 12px;
  border-bottom: 1px solid var(--border);
}

.ab-task-list {
  flex: 1;
  overflow-y: auto;
  padding: 6px;
}

.ab-task {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 7px 9px;
  border-radius: var(--radius);
  cursor: pointer;
  transition: background 0.1s ease;
  border: 1px solid transparent;
}

.ab-task:hover {
  background: var(--bg-hover);
}

.ab-task.active {
  background: var(--bg-surface);
  border-color: var(--border-strong);
  box-shadow: var(--shadow-sm);
}

.ab-task-name {
  font-size: 13px;
  color: var(--text);
  flex: 1;
}

.ab-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
}

.ab-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 12px 16px;
  border-bottom: 1px solid var(--border);
}

.ab-head-info {
  display: flex;
  flex-direction: column;
  gap: 4px;
  min-width: 0;
}

.ab-body {
  flex: 1;
  display: flex;
  min-height: 0;
}

.ab-files {
  width: 260px;
  flex-shrink: 0;
  border-right: 1px solid var(--border);
  overflow-y: auto;
  padding: 6px;
  background: var(--bg-subtle);
}

.ab-file {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 6px 9px;
  border-radius: var(--radius);
  cursor: pointer;
  transition: background 0.1s ease;
  border: 1px solid transparent;
}

.ab-file:hover {
  background: var(--bg-hover);
}

.ab-file.active {
  background: var(--bg-surface);
  border-color: var(--border-strong);
  box-shadow: var(--shadow-sm);
}

.ab-file-icon {
  color: var(--text-muted);
  flex-shrink: 0;
  display: flex;
}

.ab-file-path {
  flex: 1;
  font-size: 12px;
  color: var(--text);
}

.ab-file-size {
  flex-shrink: 0;
}

.ab-preview {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  min-height: 0;
}

.ab-preview-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  border-bottom: 1px solid var(--border);
  background: var(--bg-subtle);
}

.ab-code {
  flex: 1;
  overflow: auto;
  padding: 16px;
  font-family: var(--font-mono);
  font-size: 12.5px;
  line-height: 1.7;
  color: var(--code-text);
  background: var(--code-bg);
  white-space: pre;
  margin: 0;
}

.ab-code code {
  font-family: var(--font-mono);
  background: transparent;
  white-space: pre;
}

@media (max-width: 768px) {
  .ab-side { width: 220px; }
  .ab-files { width: 180px; }
}
</style>
