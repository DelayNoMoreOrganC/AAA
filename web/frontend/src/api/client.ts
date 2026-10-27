import axios from 'axios'
import { useAuthStore } from '../stores/auth'
import { createSessionRecovery } from '../domain/sessionRecovery.js'

const client = axios.create({
  baseURL: '/api',
  timeout: 120000,
})

client.interceptors.request.use((config) => {
  const auth = useAuthStore()
  if (auth.token) {
    config.headers.Authorization = 'Bearer ' + auth.token
  }
  return config
})

const recover = createSessionRecovery({
  getSession: () => ({ token: useAuthStore().token, refreshToken: useAuthStore().refreshToken }),
  // Bare axios avoids interceptor recursion. A network error preserves the session.
  refresh: async (refreshToken: string) => (await axios.post('/api/auth/refresh', { refresh_token: refreshToken }, { timeout: 15000 })).data,
  save: (tokens: any) => useAuthStore().saveTokens(tokens),
  expire: () => { useAuthStore().logout(); window.location.href = '/login' },
  retry: (config: any) => client.request(config),
})
client.interceptors.response.use((resp) => resp, recover)

export default client
