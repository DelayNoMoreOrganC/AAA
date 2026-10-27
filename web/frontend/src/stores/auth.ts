import { defineStore } from 'pinia'
import client from '../api/client'

interface UserInfo {
  id: string
  username: string
  display_name: string
  role: string
  org_id: string
  is_active: boolean
}

// One-time migration preserves an existing signed-in tab on upgrade. New
// sessions stay tab-local, so switching a name cannot relabel another tab.
const migrateLegacySession = !sessionStorage.getItem('v5_token') && !!localStorage.getItem('v5_token')
for (const key of ['v5_token', 'v5_refresh', 'v5_user']) {
  if (migrateLegacySession) {
    const value = localStorage.getItem(key)
    if (value) sessionStorage.setItem(key, value)
    else sessionStorage.removeItem(key)
  }
  localStorage.removeItem(key)
}

export const useAuthStore = defineStore('auth', {
  state: () => ({
    sessionEpoch: 0,
    token: sessionStorage.getItem('v5_token') || '',
    refreshToken: sessionStorage.getItem('v5_refresh') || '',
    user: JSON.parse(sessionStorage.getItem('v5_user') || 'null') as UserInfo | null,
  }),
  getters: {
    isAdmin: (state) => state.user?.role === 'admin',
  },
  actions: {
    saveTokens(data: { access_token: string; refresh_token: string }) {
      this.token = data.access_token
      this.refreshToken = data.refresh_token
      sessionStorage.setItem('v5_token', this.token)
      sessionStorage.setItem('v5_refresh', this.refreshToken)
    },
    async register(payload: { username: string; password: string; display_name: string; org_name: string }) {
      const { data } = await client.post('/auth/register', payload)
      this.sessionEpoch++
      this.saveTokens(data)
      await this.fetchMe()
    },
    async login(username: string, password: string) {
      const { data } = await client.post('/auth/login', { username, password })
      this.sessionEpoch++
      this.saveTokens(data)
      await this.fetchMe()
    },
    async loginByName(name: string) {
      const { data } = await client.post('/auth/name-login', { name })
      this.sessionEpoch++
      this.saveTokens(data)
      try { await this.fetchMe() } catch (error) { this.logout(); throw error }
    },
    async fetchMe() {
      const expectedEpoch = this.sessionEpoch
      const { data } = await client.get('/auth/me')
      if (this.sessionEpoch !== expectedEpoch) return
      this.user = data
      sessionStorage.setItem('v5_user', JSON.stringify(data))
    },
    logout() {
      this.sessionEpoch++
      this.token = ''
      this.refreshToken = ''
      this.user = null
      localStorage.removeItem('v5_token')
      localStorage.removeItem('v5_refresh')
      localStorage.removeItem('v5_user')
      sessionStorage.removeItem('v5_token')
      sessionStorage.removeItem('v5_refresh')
      sessionStorage.removeItem('v5_user')
    },
  },
})
