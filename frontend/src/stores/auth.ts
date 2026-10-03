import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import { ACCESS_KEY, REFRESH_KEY } from '@/api/client'
import { authApi, type UserPublic } from '@/api/auth'

export const useAuthStore = defineStore('auth', () => {
  const accessToken = ref<string | null>(localStorage.getItem(ACCESS_KEY))
  const refreshToken = ref<string | null>(localStorage.getItem(REFRESH_KEY))
  const user = ref<UserPublic | null>(null)
  const ready = ref(false)

  const isAuthenticated = computed(() => !!accessToken.value)

  function _persistTokens(access: string, refresh: string) {
    accessToken.value = access
    refreshToken.value = refresh
    localStorage.setItem(ACCESS_KEY, access)
    localStorage.setItem(REFRESH_KEY, refresh)
  }

  async function login(email: string, password: string) {
    const tokens = await authApi.login(email, password)
    _persistTokens(tokens.access_token, tokens.refresh_token)
    user.value = await authApi.me()
  }

  async function register(email: string, password: string) {
    await authApi.register(email, password)
    await login(email, password)
  }

  async function fetchMe() {
    try {
      user.value = await authApi.me()
    } catch {
      logout()
    }
  }

  async function bootstrap() {
    if (!accessToken.value) {
      ready.value = true
      return
    }
    await fetchMe()
    ready.value = true
  }

  function logout() {
    accessToken.value = null
    refreshToken.value = null
    user.value = null
    localStorage.removeItem(ACCESS_KEY)
    localStorage.removeItem(REFRESH_KEY)
  }

  return {
    accessToken, refreshToken, user, ready,
    isAuthenticated,
    login, register, fetchMe, bootstrap, logout,
  }
})