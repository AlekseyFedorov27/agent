import axios, {
  type AxiosError,
  type AxiosInstance,
  type InternalAxiosRequestConfig,
} from 'axios'

const RAW_BASE_URL = import.meta.env.VITE_API_BASE || '/api'
const BASE_URL = RAW_BASE_URL.replace(/\/+$/, '')

export const ACCESS_KEY = 'agent.access_token'
export const REFRESH_KEY = 'agent.refresh_token'

export const http: AxiosInstance = axios.create({
  baseURL: BASE_URL,
  headers: { 'Content-Type': 'application/json' },
})

let refreshing: Promise<string | null> | null = null

export function forceLogout() {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
  if (location.pathname !== '/login') location.href = '/login'
}

async function refreshAccessToken(): Promise<string | null> {
  const refresh = localStorage.getItem(REFRESH_KEY)
  if (!refresh) return null

  try {
    const { data } = await axios.post(`${BASE_URL}/auth/refresh`, {
      refresh_token: refresh,
    })

    if (!data?.access_token) return null

    localStorage.setItem(ACCESS_KEY, data.access_token)

    // не затираем refresh_token, если сервер его не прислал
    if (data.refresh_token) {
      localStorage.setItem(REFRESH_KEY, data.refresh_token)
    }

    return data.access_token
  } catch {
    return null
  }
}

export function refreshTokens(): Promise<string | null> {
  refreshing ??= refreshAccessToken().finally(() => {
    refreshing = null
  })
  return refreshing
}

// --- Request: подставляем access-токен -------------------------------------
http.interceptors.request.use((config: InternalAxiosRequestConfig) => {
  const token = localStorage.getItem(ACCESS_KEY)

  if (token && !config.headers.has('Authorization')) {
    config.headers.set('Authorization', `Bearer ${token}`)
  }

  return config
})

// --- Response: на 401 пытаемся обновить токен ------------------------------
http.interceptors.response.use(
  (r) => r,
  async (error: AxiosError) => {
    const original = error.config as
      | (InternalAxiosRequestConfig & { _retry?: boolean })
      | undefined

    const status = error.response?.status
    const url = original?.url || ''

    if (
      status === 401 &&
      original &&
      !original._retry &&
      !url.includes('/auth/refresh') &&
      !url.includes('/auth/login')
    ) {
      original._retry = true

      const newToken = await refreshTokens()

      if (newToken) {
        original.headers.set('Authorization', `Bearer ${newToken}`)
        return http(original)
      }

      forceLogout()
    }

    return Promise.reject(error)
  },
)

export function extractApiError(e: unknown): string {
  if (axios.isAxiosError(e)) {
    const data = e.response?.data as any
    const detail = data?.detail

    if (typeof detail === 'string') return detail

    if (Array.isArray(detail)) {
      return detail
        .map((d: any) => d?.msg ?? JSON.stringify(d))
        .join('; ')
    }

    if (data?.message) return String(data.message)

    return e.message
  }

  return e instanceof Error ? e.message : String(e)
}