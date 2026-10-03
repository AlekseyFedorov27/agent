import axios, { AxiosError, type AxiosInstance, type InternalAxiosRequestConfig } from 'axios'

const BASE_URL = import.meta.env.VITE_API_BASE || '/api'

export const ACCESS_KEY = 'agent.access_token'
export const REFRESH_KEY = 'agent.refresh_token'

export const http: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
})

// --- Request: подставляем access-токен -------------------------------------
http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem(ACCESS_KEY)
  if (token && !config.headers.Authorization) {
    config.headers.Authorization = `Bearer ${token}`
  }
  return config
})

// --- Response: на 401 пытаемся обновить токен ------------------------------
let refreshing: Promise<string | null> | null = null

async function refreshAccessToken(): Promise<string | null> {
  const refresh = localStorage.getItem(REFRESH_KEY)
  if (!refresh) return null
  try {
    const { data } = await axios.post(`${BASE_URL}/auth/refresh`, {
      refresh_token: refresh,
    })
    localStorage.setItem(ACCESS_KEY, data.access_token)
    localStorage.setItem(REFRESH_KEY, data.refresh_token)
    return data.access_token
  } catch {
    return null
  }
}

http.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as InternalAxiosRequestConfig & { _retry?: boolean }
    const status = error.response?.status
    const url = original?.url || ''

    // не пытаемся рефрешить на самом refresh/login
    if (
      status === 401 &&
      original &&
      !original._retry &&
      !url.includes('/auth/refresh') &&
      !url.includes('/auth/login')
    ) {
      original._retry = true
      refreshing ??= refreshAccessToken().finally(() => (refreshing = null))
      const newToken = await refreshing
      if (newToken) {
        original.headers.Authorization = `Bearer ${newToken}`
        return http(original)
      }
      // refresh не помог — разлогиниваем
      localStorage.removeItem(ACCESS_KEY)
      localStorage.removeItem(REFRESH_KEY)
      if (location.pathname !== '/login') {
        location.href = '/login'
      }
    }
    return Promise.reject(error)
  },
)

export function extractApiError(e: unknown): string {
  if (axios.isAxiosError(e)) {
    const detail = (e.response?.data as any)?.detail
    if (typeof detail === 'string') return detail
    if (Array.isArray(detail)) return detail.map((d: any) => d.msg).join('; ')
    return e.message
  }
  return String(e)
}