import { defineStore } from 'pinia'

import { clearToken, request, setToken } from '@/api/client'

export interface Identity {
  identity_id: string
  name: string
  role: string
}

interface SessionState {
  token: string
  identity: Identity | null
}

export const useSessionStore = defineStore('session', {
  state: (): SessionState => ({
    token: localStorage.getItem('insight_access_token') ?? '',
    identity: null,
  }),
  getters: {
    isAuthenticated: (state) => state.token.length > 0,
    displayName: (state) => state.identity?.name ?? '未登录',
    roleLabel: (state) => {
      const map: Record<string, string> = {
        admin: '平台管理员',
        maintainer: '维护者',
        analyst: '分析员',
        guest: '访客',
      }
      return state.identity ? (map[state.identity.role] ?? state.identity.role) : ''
    },
  },
  actions: {
    async login(identityId: string, password: string) {
      const response = await request('/api/access/auth/login', {
        method: 'POST',
        body: JSON.stringify({ identity_id: identityId, password }),
      })
      if (!response.ok) {
        const payload = (await response.json().catch(() => null)) as { detail?: string } | null
        throw new Error(payload?.detail ?? '身份验证失败')
      }
      const data = (await response.json()) as { token: string; identity: Identity }
      this.token = data.token
      this.identity = data.identity
      setToken(data.token)
    },
    async restore() {
      if (!this.token) {
        return
      }
      try {
        const response = await request('/api/access/auth/me')
        if (response.status === 401) {
          this.logoutLocal()
          return
        }
        const data = (await response.json()) as { identity: Identity }
        this.identity = data.identity
      } catch {
        this.logoutLocal()
      }
    },
    async logout() {
      try {
        await request('/api/access/auth/logout', { method: 'POST' })
      } finally {
        this.logoutLocal()
      }
    },
    logoutLocal() {
      this.token = ''
      this.identity = null
      clearToken()
    },
  },
})
