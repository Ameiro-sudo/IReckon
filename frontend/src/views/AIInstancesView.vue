<template>
  <div class="view-root">
    <PageHeader title="AI 实例" subtitle="管理 AI 模型连接与能力实例">
      <template #actions>
        <button class="btn btn-primary" @click="openCreate">
          <AppIcon name="plus" :size="13" :stroke-width="2" />
          添加实例
        </button>
      </template>
    </PageHeader>

    <div class="grid gap-3 pb-3 [grid-template-columns:repeat(auto-fill,minmax(340px,1fr))]">
      <div v-for="inst in instances" :key="inst.id" class="panel card-hover flex flex-col gap-3">
        <div class="flex items-center gap-3">
          <div class="flex size-9 shrink-0 items-center justify-center rounded-md bg-accent-fill font-display text-[15px] font-bold text-accent-ink shadow-[inset_0_-2px_0_rgba(0,0,0,0.18)]">
            {{ inst.name?.charAt(0) || '?' }}
          </div>
          <div class="min-w-0 flex-1">
            <div class="truncate text-sm font-semibold text-ink">{{ inst.name }}</div>
            <div class="truncate font-mono text-[11px] text-ink-3">{{ inst.model }}</div>
          </div>
          <span class="pill" :class="inst.enabled ? 'st-completed' : 'st-paused'">{{ inst.enabled ? '启用' : '禁用' }}</span>
          <span v-if="inst.has_key" class="pill st-completed" title="已配置 API Key">密钥已配置</span>
        </div>

        <div class="flex flex-col gap-1.5 rounded-lg border border-line bg-subtle px-3 py-2.5 text-xs">
          <div class="flex items-center justify-between gap-2">
            <span class="shrink-0 text-ink-3">Endpoint</span>
            <span class="max-w-[55%] truncate font-mono text-ink-2" :title="inst.endpoint">{{ inst.endpoint }}</span>
          </div>
          <div class="flex items-center justify-between gap-2">
            <span class="shrink-0 text-ink-3">价格</span>
            <span class="font-mono">${{ inst.cost_per_1k_tokens }}/1k tokens</span>
          </div>
          <div class="flex items-center justify-between gap-2">
            <span class="shrink-0 text-ink-3">上下文</span>
            <span class="font-mono">{{ formatContext(inst.max_context) }}</span>
          </div>
          <div v-if="inst.tags?.length" class="flex items-center justify-between gap-2">
            <span class="shrink-0 text-ink-3">标签</span>
            <span class="flex flex-wrap justify-end gap-1">
              <span v-for="tag in inst.tags.slice(0, 6)" :key="tag" class="rounded border border-line bg-surface px-[7px] py-px font-mono text-[10px] text-ink-2">{{ tag }}</span>
              <span v-if="inst.tags.length > 6" class="rounded border border-line bg-surface px-[7px] py-px font-mono text-[10px] text-ink-3">+{{ inst.tags.length - 6 }}</span>
            </span>
          </div>
        </div>

        <div
          v-if="testResults[inst.id]"
          class="flex min-w-0 items-center gap-2 rounded-md px-3 py-2"
          :class="testResults[inst.id].status === 'reachable' ? 'bg-success-soft text-success' : 'bg-error-soft text-error'"
        >
          <span class="size-[7px] shrink-0 rounded-full bg-current"></span>
          <span v-if="testResults[inst.id].status === 'reachable'" class="text-[13px]">
            可达 (HTTP {{ testResults[inst.id].http_status }}<template v-if="testResults[inst.id].latency_ms"> · {{ testResults[inst.id].latency_ms }}ms</template>)
          </span>
          <span v-else class="truncate text-[13px]" :title="testResults[inst.id].error">
            不可达: {{ testResults[inst.id].error }}
          </span>
          <button class="btn btn-ghost btn-icon ml-auto p-1!" aria-label="清除测试结果" @click="clearTest(inst.id)">
            <AppIcon name="x" :size="12" />
          </button>
        </div>

        <div class="flex gap-2">
          <button class="btn btn-secondary btn-sm flex-1" :disabled="testingId === inst.id" @click="testInstance(inst.id)">
            {{ testingId === inst.id ? '测试中...' : '测试' }}
          </button>
          <button class="btn btn-secondary btn-sm flex-1" @click="openEdit(inst)">编辑</button>
          <button class="btn btn-danger btn-sm flex-1" @click="deleteInstance(inst)">删除</button>
        </div>
      </div>

      <div v-if="!instances.length" class="panel empty-state [grid-column:1/-1]">
        <div class="empty-icon"><AppIcon name="cpu" :size="19" /></div>
        <p>暂无 AI 实例</p>
        <button class="btn btn-primary btn-sm" @click="openCreate">添加第一个实例</button>
      </div>
    </div>

    <Teleport to="body">
      <AppModal :open="showModal" :title="editingInstance ? '编辑实例' : '添加实例'" desc="OpenAI 兼容端点可直接接入，API Key 将加密存储。" @close="closeModal">
        <form @submit.prevent="saveInstance">
          <div class="mb-4">
            <label class="form-label">名称</label>
            <input v-model="form.name" class="input" required />
          </div>
          <div class="mb-4">
            <label class="form-label">模型</label>
            <input v-model="form.model" class="input" placeholder="gpt-4 / deepseek-v4-flash" required />
          </div>
          <div class="mb-4">
            <label class="form-label">Endpoint</label>
            <input v-model="form.endpoint" class="input" placeholder="https://api.example.com/v1" required />
          </div>
          <div class="mb-4">
            <label class="form-label">API Key</label>
            <input v-model="form.api_key" class="input" type="password" placeholder="sk-..." autocomplete="new-password" />
            <div v-if="editingInstance?.has_key" class="mt-1 text-xs text-ink-3">留空表示保持不变，已配置密钥</div>
          </div>
          <div class="mb-4 flex gap-3">
            <div class="flex-1">
              <label class="form-label">最大上下文</label>
              <input v-model.number="form.max_context" class="input" type="number" />
            </div>
            <div class="flex-1">
              <label class="form-label">价格 ($/1k tokens)</label>
              <input v-model.number="form.cost_per_1k_tokens" class="input" type="number" step="0.001" />
            </div>
          </div>
          <div class="mb-4">
            <label class="form-label">标签 (逗号分隔)</label>
            <input v-model="tagsInput" class="input" placeholder="python, coding, smart" />
          </div>
          <div class="mb-4">
            <label class="switch-label">
              <input type="checkbox" v-model="form.enabled" />
              <span class="switch-track"><span class="switch-thumb"></span></span>
              启用
            </label>
          </div>

          <div class="mt-6 flex justify-end gap-2.5">
            <button type="button" class="btn btn-secondary" @click="closeModal">取消</button>
            <button type="submit" class="btn btn-primary">保存</button>
          </div>
        </form>
      </AppModal>
    </Teleport>
  </div>
</template>

<script setup>
import { onMounted, reactive, ref } from 'vue'
import { aiInstanceAPI } from '../api/index.js'
import { useToast } from '../composables/useToast.js'
import { useConfirm } from '../composables/useConfirm.js'
import PageHeader from '../components/PageHeader.vue'
import AppModal from '../components/ui/AppModal.vue'
import AppIcon from '../components/ui/AppIcon.vue'

const toast = useToast()
const { confirm } = useConfirm()
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

async function deleteInstance(inst) {
  const ok = await confirm({
    title: '删除实例',
    message: `确定删除 "${inst.name}"？此操作不可恢复。`,
    confirmText: '删除',
    danger: true
  })
  if (!ok) return
  try {
    await aiInstanceAPI.delete(inst.id)
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
