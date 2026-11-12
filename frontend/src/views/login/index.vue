<template>
  <section class="login-page">
    <div class="login-card">
      <h2>身份验证</h2>
      <p class="page-desc">认证在本应用内闭环完成：稳定身份标识 + 口令换取访问令牌，越权调用由服务端拦截。</p>
      <form class="login-form" @submit.prevent="submit">
        <label class="filter-item">
          <span>稳定身份标识</span>
          <input v-model="identityId" placeholder="如 u_maint_a" autocomplete="username" />
        </label>
        <label class="filter-item">
          <span>口令</span>
          <input v-model="password" type="password" placeholder="演示口令见下方账号" autocomplete="current-password" />
        </label>
        <button class="btn primary" type="submit" :disabled="loading">
          {{ loading ? '验证中…' : '登录并获取令牌' }}
        </button>
      </form>
      <p v-if="errorMessage" class="error-text">{{ errorMessage }}</p>

      <div class="demo-box">
        <strong>演示账号（点击可自动填充）</strong>
        <button
          v-for="item in demoAccounts"
          :key="item.identity_id"
          class="demo-account"
          type="button"
          @click="fill(item)"
        >
          <span>{{ item.name }} · {{ item.roleLabel }}</span>
          <code>{{ item.identity_id }} / {{ item.password }}</code>
        </button>
      </div>
    </div>
  </section>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'

import { useSessionStore } from '@/stores/session'

const session = useSessionStore()
const router = useRouter()
const route = useRoute()

const identityId = ref('')
const password = ref('')
const loading = ref(false)
const errorMessage = ref('')

const demoAccounts = [
  { identity_id: 'u_admin', password: 'admin-pass-2026', name: '平台管理员', roleLabel: 'admin' },
  { identity_id: 'u_maint_a', password: 'maint-pass-2026', name: '资产维护人·林澈', roleLabel: 'maintainer' },
  { identity_id: 'u_maint_b', password: 'maint-pass-2026', name: '营销维护人·周岚', roleLabel: 'maintainer' },
  { identity_id: 'u_analyst', password: 'analyst-pass-2026', name: '分析员·陈默', roleLabel: 'analyst' },
  { identity_id: 'u_guest', password: 'guest-pass-2026', name: '访客·见习账号', roleLabel: 'guest' },
]

function fill(item: { identity_id: string; password: string }) {
  identityId.value = item.identity_id
  password.value = item.password
  errorMessage.value = ''
}

async function submit() {
  if (!identityId.value || !password.value) {
    errorMessage.value = '请填写身份标识与口令'
    return
  }
  loading.value = true
  errorMessage.value = ''
  try {
    await session.login(identityId.value.trim(), password.value)
    const redirect = typeof route.query.redirect === 'string' ? route.query.redirect : '/'
    await router.replace(redirect)
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : '身份验证失败'
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: #f6f8fb;
}
.login-card {
  width: 460px;
  background: #fff;
  border: 1px solid var(--border);
  border-radius: 10px;
  padding: 24px;
}
.login-form {
  display: flex;
  flex-direction: column;
  gap: 12px;
  margin: 16px 0;
}
.login-form input {
  width: 100%;
  padding: 8px 10px;
  border: 1px solid var(--border);
  border-radius: 6px;
}
.demo-box {
  margin-top: 16px;
  border-top: 1px dashed var(--border);
  padding-top: 12px;
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.demo-box strong {
  font-size: 13px;
}
.demo-account {
  display: flex;
  justify-content: space-between;
  align-items: center;
  border: 1px solid var(--border);
  background: #f8fafc;
  border-radius: 6px;
  padding: 8px 10px;
  cursor: pointer;
  font-size: 12px;
}
.demo-account:hover {
  border-color: var(--brand);
}
</style>
