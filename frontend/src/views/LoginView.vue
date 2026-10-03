<script setup lang="ts">
import { ref } from 'vue'
import { useRouter, useRoute } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { extractApiError } from '@/api/client'

const auth = useAuthStore()
const router = useRouter()
const route = useRoute()

const email = ref('')
const password = ref('')
const loading = ref(false)
const error = ref<string | null>(null)

async function onSubmit() {
  error.value = null
  loading.value = true
  try {
    await auth.login(email.value.trim(), password.value)
    const redirect = (route.query.redirect as string) || '/chat'
    router.push(redirect)
  } catch (e) {
    error.value = extractApiError(e)
  } finally {
    loading.value = false
  }
}
</script>

<template>
  <div class="auth-shell">
    <form class="auth-card" @submit.prevent="onSubmit">
      <h1 class="auth-shell-title">Вход</h1>
      <p class="auth-shell-subtitle muted">Agent Chat</p>

      <label>
        Email
        <input v-model="email" type="email" required autocomplete="email" />
      </label>

      <label>
        Пароль
        <input v-model="password" type="password" required autocomplete="current-password" />
      </label>

      <p v-if="error" class="error">{{ error }}</p>

      <button :disabled="loading" type="submit">
        {{ loading ? 'Входим…' : 'Войти' }}
      </button>

      <p class="switch">
        Нет аккаунта?
        <RouterLink to="/register">Зарегистрироваться</RouterLink>
      </p>
    </form>
  </div>
</template>