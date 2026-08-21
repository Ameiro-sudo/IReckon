<template>
  <Teleport to="body">
    <AppModal :open="visible" title="创建新任务" width="560" desc="输入自然语言需求，可附加上传参考文件，AI 智能体团队将自主完成规划、编码、审查与交付。" @close="close">
      <div class="mb-4">
        <label class="form-label" for="task-request">任务描述</label>
        <textarea
          id="task-request"
          v-model="request"
          class="input"
          placeholder="例如：用 Python 写一个命令行待办事项管理工具，支持增删改查和持久化存储…"
          rows="4"
          autofocus
          @keydown.ctrl.enter.prevent="submit"
          @keydown.meta.enter.prevent="submit"
        ></textarea>
        <div class="mt-1 text-xs text-ink-3">Ctrl+Enter / ⌘+Enter 快捷提交</div>
      </div>

      <div class="mb-4">
        <label class="form-label" id="file-upload-label">参考文件（可选）</label>
        <div
          class="flex cursor-pointer flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed p-6 text-center transition-colors duration-150"
          :class="dragging ? 'border-accent bg-accent-soft' : 'border-line-strong text-ink-3 hover:border-accent hover:bg-accent-soft'"
          role="button"
          tabindex="0"
          aria-labelledby="file-upload-label"
          @click="fileInput?.click()"
          @keydown.enter.prevent="fileInput?.click()"
          @keydown.space.prevent="fileInput?.click()"
          @dragover.prevent="dragging = true"
          @dragleave="dragging = false"
          @drop.prevent="onDrop"
        >
          <input ref="fileInput" type="file" multiple class="hidden" tabindex="-1" aria-hidden="true" @change="onPick" />
          <AppIcon name="upload" :size="16" />
          <span class="text-[13px] text-ink-2">点击选择或拖拽文件到此处</span>
          <span class="text-xs text-ink-3">每个文件 ≤ 10MB，最多 20 个</span>
        </div>

        <div v-if="files.length" class="mt-2 flex max-h-[140px] flex-col gap-1.5 overflow-y-auto">
          <div v-for="(f, i) in files" :key="f.name + i" class="flex items-center gap-2 rounded-md border border-line bg-subtle px-2.5 py-1.5">
            <AppIcon name="file" :size="12" />
            <span class="flex-1 truncate font-mono text-xs text-ink" :title="f.name">{{ f.name }}</span>
            <span class="font-mono text-xs text-ink-3">{{ formatSize(f.size) }}</span>
            <button type="button" class="btn btn-ghost btn-icon p-1!" aria-label="移除文件" @click="removeFile(i)">
              <AppIcon name="x" :size="11" :stroke-width="2" />
            </button>
          </div>
        </div>
      </div>

      <div v-if="schedulers.length" class="mb-4">
        <label class="form-label">调度智能体（可选）</label>
        <select v-model="schedulerCapId" class="input">
          <option value="">自动选择</option>
          <option v-for="s in schedulers" :key="s.id" :value="s.id">{{ s.name }} ({{ s.model }})</option>
        </select>
      </div>

      <template #footer>
        <button class="btn btn-secondary" :disabled="submitting || uploading" @click="close">取消</button>
        <button class="btn btn-primary" :disabled="!request.trim() || submitting || uploading" @click="submit">
          <span v-if="submitting" class="size-3 animate-spin rounded-full border-2 border-accent-ink/35 border-t-accent-ink"></span>
          {{ submitting ? '创建中...' : '创建任务' }}
        </button>
      </template>
    </AppModal>
  </Teleport>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { aiInstanceAPI, uploadAPI } from '../api/index.js'
import { useToast } from '../composables/useToast.js'
import { formatSize } from '../utils/format.js'
import AppModal from './ui/AppModal.vue'
import AppIcon from './ui/AppIcon.vue'

const toast = useToast()

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
  } catch (e) {
    toast.error('创建失败: ' + (e.response?.data?.detail || e.message))
  } finally {
    uploading.value = false
    submitting.value = false
  }
}

defineExpose({ open })
</script>
