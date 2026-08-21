<template>
  <div class="login-root">
    <div class="login-card">
      <div class="login-brand">
        <div class="brand-mark">I</div>
        <div>
          <div class="brand-name">IReckon</div>
          <div class="brand-sub">Multi-Agent AI Factory</div>
        </div>
      </div>

      <h1 class="login-title">访问控制台</h1>
      <p class="login-desc">
        请输入 API 访问令牌。首次启动时令牌由服务端生成并打印在控制台日志中。
      </p>

      <form class="login-form" @submit.prevent="submit">
        <div class="token-row">
          <input
            v-model="token"
            class="input mono"
            :type="showToken ? 'text' : 'password'"
            placeholder="irk_..."
            autocomplete="off"
            autofocus
          />
          <button type="button" class="btn btn-secondary" @click="showToken = !showToken">
            {{ showToken ? '隐藏' : '显示' }}
          </button>
        </div>
        <p v-if="errorMsg" class="login-error">{{ errorMsg }}</p>
        <button type="submit" class="btn btn-primary btn-block" :disabled="loading || !token.trim()">
          {{ loading ? '验证中...' : '解锁控制台' }}
        </button>
      </form>

      <p class="login-hint">
        令牌保存在本浏览器 localStorage，仅通过 X-API-Token 请求头发送。
      </p>
    </div>
  </div>
</template>

<script setup>
import {onMounted, ref} from 'vue'
import {useRoute, useRouter} from 'vue-router'
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

<style scoped>
.login-root {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 20px;
  background: var(--bg);
  background-image:
    linear-gradient(var(--border) 1px, transparent 1px),
    linear-gradient(90deg, var(--border) 1px, transparent 1px);
  background-size: 28px 28px;
}

.login-card {
  width: 100%;
  max-width: 400px;
  background: var(--bg-surface);
  border: 1px solid var(--border-strong);
  border-radius: var(--radius-xl);
  padding: 28px;
  display: flex;
  flex-direction: column;
  gap: 14px;
  box-shadow: var(--shadow-lg);
}

/* 铭牌顶线 */
.login-card::before {
  content: '';
  height: 3px;
  border-radius: 2px;
  background: var(--accent-fill);
  margin-bottom: 4px;
}

.login-brand {
  display: flex;
  align-items: center;
  gap: 10px;
}

.brand-mark {
  width: 38px;
  height: 38px;
  border-radius: var(--radius);
  background: var(--accent-fill);
  color: var(--accent-ink);
  font-weight: 700;
  font-size: 18px;
  font-family: var(--font-display);
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: inset 0 -2px 0 rgba(0, 0, 0, 0.18);
}

.brand-name {
  font-weight: 700;
  font-family: var(--font-display);
  letter-spacing: 0.02em;
  text-transform: uppercase;
}

.brand-sub {
  font-size: 10px;
  color: var(--text-muted);
  font-family: var(--font-mono);
  letter-spacing: 0.08em;
  text-transform: uppercase;
}

.login-title {
  font-size: 18px;
  margin: 4px 0 0;
  font-family: var(--font-display);
  letter-spacing: 0.01em;
}

.login-desc,
.login-hint {
  font-size: 13px;
  color: var(--text-secondary);
  margin: 0;
}

.login-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
}

.token-row {
  display: flex;
  gap: 8px;
}

.token-row .input {
  flex: 1;
}

.login-error {
  margin: 0;
  font-size: 13px;
  color: var(--error);
}
</style>
