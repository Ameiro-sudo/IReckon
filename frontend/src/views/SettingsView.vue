<template>
  <div class="view-root">
    <PageHeader title="设置" subtitle="系统配置与更新管理" content-class="max-w-[680px]" />

    <div class="flex max-w-[680px] flex-col gap-3 pb-3">
      <div class="panel">
        <div class="plate">API 访问令牌</div>
        <p class="plate-desc">后端已启用鉴权（config.yaml → security.api_token）。令牌仅保存在本浏览器 localStorage，用于请求头 X-API-Token。</p>
        <div class="flex gap-2">
          <input
            v-model="apiToken"
            class="input flex-1 font-mono"
            :type="showToken ? 'text' : 'password'"
            placeholder="粘贴 API Token"
            autocomplete="off"
          />
          <button class="btn btn-secondary" @click="showToken = !showToken">{{ showToken ? '隐藏' : '显示' }}</button>
        </div>
        <div class="mt-2.5 flex gap-2">
          <button class="btn btn-primary" :disabled="savingToken" @click="saveToken">
            {{ savingToken ? '验证中...' : '保存并验证' }}
          </button>
          <button v-if="apiToken" class="btn btn-secondary" @click="clearToken">清除</button>
        </div>
        <p v-if="tokenState" class="mt-1.5 text-[13px] text-ink-3">{{ tokenState }}</p>
      </div>

      <div class="panel">
        <div class="plate">更新管理</div>
        <p class="plate-desc">检查并应用系统更新</p>

        <div v-if="updateStatus" class="mb-3.5 flex flex-col gap-2 rounded-lg border border-line bg-subtle px-4 py-3">
          <div class="flex items-center justify-between text-[13px]">
            <span class="text-ink-2">当前版本</span>
            <span class="font-mono">{{ updateStatus.current_version }}</span>
          </div>
          <div v-if="updateStatus.latest_version" class="flex items-center justify-between text-[13px]">
            <span class="text-ink-2">最新版本</span>
            <span class="font-mono">{{ updateStatus.latest_version }}</span>
          </div>
          <div class="flex items-center justify-between text-[13px]">
            <span class="text-ink-2">状态</span>
            <span v-if="updateStatus.update_available" class="pill st-warning">有可用更新</span>
            <span v-else class="pill st-completed">已是最新</span>
          </div>
        </div>

        <label class="mb-1.5 block text-xs text-ink-3">检查</label>
        <button class="btn btn-secondary w-fit" :disabled="checking" @click="checkUpdate">
          {{ checking ? '检查中...' : '检查更新' }}
        </button>

        <label class="mb-1.5 mt-4 block text-xs text-ink-3">应用更新（渠道）</label>
        <div class="flex items-center gap-2.5">
          <select v-model="updateChannel" class="input h-8! w-64 py-0! text-[13px]" title="更新渠道：auto 按安装形态自动选择">
            <option value="auto">自动选择渠道</option>
            <option value="portable">便携版 ZIP（直接启动）</option>
            <option value="installer">安装器 EXE（Setup）</option>
          </select>
          <button class="btn btn-primary" :disabled="!updateStatus?.update_available || applying" @click="applyUpdate">
            {{ applying ? '更新中...' : '立即更新' }}
          </button>
        </div>
      </div>

      <div class="panel">
        <div class="plate">系统配置</div>
        <p class="plate-desc">当前运行时配置（YAML，修改 config/config.yaml 后自动热重载）</p>
        <div class="flex flex-col gap-1">
          <div v-for="(val, key) in topLevelKeys" :key="key" class="flex items-center justify-between gap-3 rounded-md bg-subtle px-2.5 py-[7px] text-xs">
            <span class="shrink-0 font-mono text-ink-2">{{ key }}</span>
            <span class="max-w-[60%] truncate font-mono text-ink">{{ formatValue(val) }}</span>
          </div>
          <div v-if="!topLevelKeys.length" class="p-3 text-[13px] text-ink-3">加载配置中...</div>
        </div>
      </div>

      <div class="panel">
        <div class="plate">关于</div>
        <div class="flex items-center justify-between font-semibold">
          <span>IReckon AI Factory</span>
          <span class="font-mono text-ink-3">v{{ version }}</span>
        </div>
        <p class="mt-1.5 text-[13px] text-ink-3">
          多智能体自主编程系统 — 由专业 AI 智能体团队完成规划、编码、审查与交付。
        </p>
      </div>
    </div>
  </div>
</template>

<script setup>
import axios from 'axios'
import { computed, onMounted, ref } from 'vue'
import { configAPI, healthAPI, updateAPI } from '../api/index.js'
import { useToast } from '../composables/useToast.js'
import PageHeader from '../components/PageHeader.vue'

const toast = useToast()
const config = ref({})
const updateStatus = ref(null)
const updateChannel = ref('auto')
const version = ref('—')
const checking = ref(false)
const applying = ref(false)

const TOKEN_KEY = 'ireckon_api_token'
const apiToken = ref(localStorage.getItem(TOKEN_KEY) || '')
const showToken = ref(false)
const savingToken = ref(false)
const tokenState = ref('')

async function saveToken() {
  savingToken.value = true
  tokenState.value = ''
  const candidate = apiToken.value.trim()
  try {
    await healthAPI.check()
    await axios.get('/api/stats', { headers: { 'X-API-Token': candidate }, timeout: 10000 })
    localStorage.setItem(TOKEN_KEY, candidate)
    tokenState.value = '令牌有效，已保存'
    toast.success('API Token 已保存')
  } catch (e) {
    tokenState.value = e?.response?.status === 401 ? '令牌无效（401），未保存' : '验证请求失败，未保存'
    toast.error(tokenState.value)
  } finally {
    savingToken.value = false
  }
}

function clearToken() {
  apiToken.value = ''
  localStorage.removeItem(TOKEN_KEY)
  tokenState.value = '已清除本地令牌'
}

const topLevelKeys = computed(() => Object.keys(config.value))

onMounted(async () => {
  try {
    const [cfg, health] = await Promise.all([configAPI.get(), healthAPI.check()])
    config.value = cfg.data
    version.value = health.data?.version || '—'
  } catch {
    /* ignore */
  }
})

async function checkUpdate() {
  checking.value = true
  try {
    const res = await updateAPI.check()
    updateStatus.value = res.data
    if (res.data.update_available) toast.info(`发现新版本 v${res.data.latest_version}`)
    else toast.success('已是最新版本')
  } catch (e) {
    toast.error('检查更新失败: ' + e.message)
  } finally {
    checking.value = false
  }
}

async function applyUpdate() {
  applying.value = true
  try {
    const res = await updateAPI.apply(
      updateChannel.value === 'auto' ? null : updateChannel.value
    )
    if (res.data.status === 'ok') {
      // 安装器渠道：向导已拉起，应用随后退出；便携渠道：文件已就地替换
      toast.success(res.data.message || '更新完成，请重启应用')
    } else {
      toast.error(res.data.error || res.data.message || '更新失败')
    }
  } catch (e) {
    toast.error('更新失败: ' + e.message)
  } finally {
    applying.value = false
  }
}

function formatValue(val) {
  if (val && typeof val === 'object') return JSON.stringify(val).slice(0, 60)
  return String(val ?? '')
}
</script>
