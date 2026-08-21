<template>
  <div class="grid-paper flex min-h-dvh items-center justify-center bg-bg p-5">
    <div class="flex w-full max-w-[400px] flex-col gap-3.5 rounded-xl border border-line-strong bg-surface p-7 shadow-lg">
      <div class="mb-1 h-[3px] rounded-sm bg-accent-fill"></div>

      <div class="flex items-center gap-2.5">
        <div class="brand-mark size-[38px]! text-lg!">I</div>
        <div>
          <div class="brand-name">IReckon</div>
          <div class="brand-sub">Multi-Agent AI Factory</div>
        </div>
      </div>

      <h1 class="mt-1 font-display text-lg font-bold tracking-wide text-ink">访问控制台</h1>
      <p class="text-[13px] leading-relaxed text-ink-2">
        请输入 API 访问令牌。首次启动时令牌由服务端生成并打印在控制台日志中。
      </p>

      <form class="flex flex-col gap-3" @submit.prevent="submit">
        <div class="flex gap-2">
          <input
            v-model="token"
            class="input flex-1 font-mono"
            :type="showToken ? 'text' : 'password'"
            placeholder="irk_..."
            autocomplete="off"
            autofocus
          />
          <button type="button" class="btn btn-secondary" @click="showToken = !showToken">
            {{ showToken ? '隐藏' : '显示' }}
          </button>
        </div>
        <p v-if="errorMsg" class="m-0 text-[13px] text-error">{{ errorMsg }}</p>
        <button type="submit" class="btn btn-primary btn-block" :disabled="loading || !token.trim()">
          {{ loading ? '验证中...' : '解锁控制台' }}
        </button>
      </form>

      <p class="text-[13px] text-ink-2">
        令牌保存在本浏览器 localStorage，仅通过 X-API-Token 请求头发送。
      </p>
    </div>
  </div>
</template>

<script setup>
import { onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import axios from 'axios'

const route = useRoute()
const router = useRouter()

const token = ref('')
const showToken = ref(false)
const loading = ref(false)
const errorMsg = ref('')

onMounted(async () => {
  // 后端未启用鉴权时（如显式清空 token 的特殊部署）直接放行
  try {
    const res = await axios.get('/api/auth/check', { timeout: 8000 })
    if (res.data && res.data.required === false) {
      goNext()
    }
  } catch {
    /* 后端离线时仍展示登录页 */
  }
})

function goNext() {
  const target = typeof route.query.redirect === 'string' && route.query.redirect.startsWith('/')
    ? route.query.redirect
    : '/'
  router.replace(target)
}

async function submit() {
  loading.value = true
  errorMsg.value = ''
  const candidate = token.value.trim()
  try {
    const res = await axios.get('/api/auth/check', {
      headers: { 'X-API-Token': candidate },
      timeout: 8000
    })
    if (res.data?.authenticated) {
      localStorage.setItem('ireckon_api_token', candidate)
      goNext()
    } else {
      errorMsg.value = '令牌无效，请检查后重试'
    }
  } catch (e) {
    errorMsg.value = e?.response?.status === 401
      ? '令牌无效，请检查后重试'
      : '无法连接后端服务，请确认服务已启动'
  } finally {
    loading.value = false
  }
}
</script>
