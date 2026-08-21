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
            <label class="form-label">快速预设</label>
            <div class="flex flex-wrap gap-1.5">
              <button
                v-for="p in PRESETS"
                :key="p.key"
                type="button"
                class="rounded-full border px-3 py-1 text-xs font-medium transition-colors"
                :class="activePreset === p.key
                  ? 'border-accent-border bg-accent-soft text-accent'
                  : 'border-line bg-surface text-ink-2 hover:border-accent-border hover:text-accent'"
                :title="p.hint || p.endpoint"
                @click="applyPreset(p)"
              >
                {{ p.label }}
              </button>
            </div>
            <div v-if="activePresetObj?.hint" class="mt-1.5 text-xs text-ink-3">{{ activePresetObj.hint }}</div>
          </div>
          <div class="mb-4">
            <label class="form-label">名称</label>
            <input v-model="form.name" class="input" required />
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
          <div class="mb-4">
            <label class="form-label">模型</label>
            <div class="flex gap-2">
              <input v-model="form.model" class="input min-w-0 flex-1" placeholder="gpt-4 / deepseek-v4-flash" required />
              <button
                type="button"
                class="btn btn-secondary shrink-0"
                :disabled="!form.endpoint.trim() || scanning"
                title="探测端点的 OpenAI 兼容 /models 列表"
                @click="scanModels"
              >
                <AppIcon name="search" :size="13" />
                {{ scanning ? '扫描中...' : '扫描模型' }}
              </button>
            </div>
            <div v-if="scanError" class="mt-1.5 break-all text-xs text-error">{{ scanError }}</div>
            <div v-if="scanResults.length" class="mt-2 rounded-lg border border-line bg-subtle p-2">
              <div class="mb-1.5 px-0.5 text-xs text-ink-3">扫描到 {{ scanResults.length }} 个模型，点击勾选填入：</div>
              <div class="flex max-h-40 flex-wrap gap-1.5 overflow-y-auto">
                <button
                  v-for="m in scanResults"
                  :key="m"
                  type="button"
                  class="flex items-center gap-1 rounded-full border px-2.5 py-1 font-mono text-[11px] transition-colors"
                  :class="form.model === m
                    ? 'border-accent-fill bg-accent-fill text-accent-ink'
                    : 'border-line bg-surface text-ink-2 hover:border-accent-border'"
                  @click="toggleModel(m)"
                >
                  <AppIcon v-if="form.model === m" name="check" :size="11" :stroke-width="2.5" />
                  {{ m }}
                </button>
              </div>
            </div>
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
import { computed, onMounted, reactive, ref, watch } from 'vue'
import { aiInstanceAPI } from '../api/index.js'
import { useToast } from '../composables/useToast.js'
import { useConfirm } from '../composables/useConfirm.js'
import PageHeader from '../components/PageHeader.vue'
import AppModal from '../components/ui/AppModal.vue'
import AppIcon from '../components/ui/AppIcon.vue'

// 常见服务商预设：一键填端点；Ollama 为本机推理服务，需开 allow_private_endpoints
const PRESETS = [
  { key: 'deepseek', label: 'DeepSeek', endpoint: 'https://api.deepseek.com', name: 'DeepSeek' },
  { key: 'openai', label: 'OpenAI', endpoint: 'https://api.openai.com/v1', name: 'OpenAI' },
  { key: 'kimi', label: 'Kimi', endpoint: 'https://api.moonshot.cn/v1', name: 'Kimi' },
  {
    key: 'ollama',
    label: 'Ollama',
    endpoint: 'http://localhost:11434/v1',
    name: 'Ollama 本地',
    hint: '本地端点需在 config.yaml 设置 security.allow_private_endpoints: true 后重启'
  }
]

const toast = useToast()
const { confirm } = useConfirm()
const instances = ref([])
const showModal = ref(false)
const editingInstance = ref(null)
const testingId = ref(null)
const tagsInput = ref('')
const testResults = reactive({})
const form = ref(emptyForm())
const scanning = ref(false)
const scanResults = ref([])
const scanError = ref('')

const activePresetObj = computed(() => PRESETS.find(p => p.endpoint === (form.value.endpoint || '').trim()))
const activePreset = computed(() => activePresetObj.value?.key || '')

// 端点或密钥变化后，旧扫描结果即失效
watch(() => [form.value.endpoint, form.value.api_key], () => {
  scanResults.value = []
  scanError.value = ''
})

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

function applyPreset(p) {
  form.value.endpoint = p.endpoint
  if (!String(form.value.name || '').trim()) form.value.name = p.name
}

function toggleModel(m) {
  form.value.model = form.value.model === m ? '' : m
}

async function scanModels() {
  const endpoint = (form.value.endpoint || '').trim()
  if (!endpoint || scanning.value) return
  scanning.value = true
  scanResults.value = []
  scanError.value = ''
  try {
    const payload = { endpoint, api_key: form.value.api_key || '' }
    // 编辑态未重填密钥时，让后端复用存量密钥探测
    if (editingInstance.value && !String(form.value.api_key || '').trim()) {
      payload.instance_id = editingInstance.value.id
    }
    const res = await aiInstanceAPI.scanModels(payload)
    const body = res.data
    if (body.status === 'ok') {
      scanResults.value = [...body.models].sort((a, b) => a.localeCompare(b))
      toast.success(`扫描到 ${scanResults.value.length} 个模型`)
    } else {
      scanError.value = body.error || '扫描失败'
    }
  } catch (e) {
    let detail = e.response?.data?.detail || e.message
    if (/内网|环回|组播/.test(detail)) {
      detail += ' —— 本地端点需在 config.yaml 设置 security.allow_private_endpoints: true 并重启'
    }
    scanError.value = detail
  } finally {
    scanning.value = false
  }
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
