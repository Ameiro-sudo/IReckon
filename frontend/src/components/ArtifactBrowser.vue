<template>
  <div class="flex min-h-0 flex-1 overflow-hidden rounded-lg border border-line bg-surface">
    <aside class="flex w-[280px] shrink-0 flex-col bg-subtle max-md:w-full max-md:max-h-[200px] max-md:border-b">
      <TaskListRail :tasks="tasks" v-model="selected" empty-text="暂无任务" />
    </aside>

    <section class="flex min-w-0 flex-1 flex-col max-md:hidden" :class="{ 'flex!': selected }">
      <template v-if="selected">
        <div class="flex items-center justify-between gap-3 border-b border-line px-4 py-3 max-sm:flex-wrap">
          <div class="flex min-w-0 flex-col gap-1">
            <div class="max-w-[400px] truncate text-[13px] text-ink-2">{{ selected.user_request?.slice(0, 60) || '无描述' }}</div>
            <div class="flex items-center gap-2">
              <StatusPill :status="selected.status" />
              <span class="font-mono text-xs text-ink-3">{{ selected.task_id }}</span>
            </div>
          </div>
          <a :href="downloadUrl" class="btn btn-secondary btn-sm shrink-0" target="_blank">
            <AppIcon name="download" :size="12" />
            下载 ZIP
          </a>
        </div>

        <div class="flex min-h-0 flex-1 max-md:flex-col">
          <div class="w-[260px] shrink-0 overflow-y-auto border-r border-line bg-subtle p-1.5 max-md:w-full max-md:max-h-[150px] max-md:border-r-0 max-md:border-b">
            <div v-if="!files.length" class="p-5 text-center text-[13px] text-ink-3">该任务暂无产物</div>
            <button
              v-for="f in files"
              :key="f.path"
              class="sig mb-0.5 flex w-full items-center gap-2 rounded-md border border-transparent px-2.5 py-1.5 text-left transition-colors duration-100 hover:bg-hover"
              :class="{ 'on border-line-strong bg-surface shadow-sm': current?.path === f.path }"
              @click="openFile(f)"
            >
              <span class="flex shrink-0 text-ink-3">
                <AppIcon :name="isText(f) ? 'file' : 'fileBinary'" :size="12" />
              </span>
              <span class="flex-1 truncate font-mono text-xs text-ink">{{ f.path }}</span>
              <span class="shrink-0 font-mono text-xs text-ink-3">{{ formatSize(f.size) }}</span>
            </button>
          </div>

          <div class="flex min-h-0 min-w-0 flex-1 flex-col">
            <template v-if="current">
              <div class="flex items-center justify-between border-b border-line bg-subtle px-4 py-2">
                <span class="truncate font-mono text-[13px] text-ink">{{ current.path }}</span>
                <span class="ml-3 shrink-0 font-mono text-xs text-ink-3">{{ formatSize(current.size) }}</span>
              </div>
              <pre v-if="content !== null" class="m-0 min-h-0 flex-1 overflow-auto p-4 font-mono text-[13px] leading-relaxed whitespace-pre text-code"><code class="hljs" v-html="highlighted"></code></pre>
              <div v-else class="empty-state flex-1">
                <p>二进制或超大文件，无法预览</p>
              </div>
            </template>
            <div v-else class="empty-state flex-1">
              <p>选择左侧文件查看内容</p>
            </div>
          </div>
        </div>
      </template>

      <div v-else class="empty-state flex-1">
        <div class="empty-icon"><AppIcon name="box" :size="19" /></div>
        <p>选择左侧任务查看交付产物</p>
      </div>
    </section>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useTaskStore } from '../stores/taskStore.js'
import { taskAPI } from '../api/index.js'
import { highlightCode } from '../utils/markdown.js'
import { taskTitle } from '../utils/task.js'
import { formatSize } from '../utils/format.js'
import StatusPill from './StatusPill.vue'
import TaskListRail from './TaskListRail.vue'
import AppIcon from './ui/AppIcon.vue'

const taskStore = useTaskStore()
const tasks = computed(() => taskStore.tasks)
const selected = ref(null)
const files = ref([])
const current = ref(null)
const content = ref(null)

const TEXT_EXTS = ['py', 'js', 'ts', 'vue', 'json', 'yaml', 'yml', 'toml', 'md', 'txt', 'html', 'css', 'sh', 'bat', 'sql', 'xml', 'ini', 'env', 'cfg', 'log', 'tsx', 'jsx', 'dockerfile', 'gitignore']

const downloadUrl = computed(() => selected.value ? taskAPI.downloadUrl(selected.value.task_id) : '#')

const highlighted = computed(() => {
  if (content.value === null || !current.value) return ''
  return highlightCode(content.value, current.value.path)
})

onMounted(() => taskStore.fetchTasks())

async function selectArtifacts(task) {
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

watch(selected, (task) => {
  if (task) selectArtifacts(task)
})
</script>
