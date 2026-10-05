<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import { extractApiError } from '@/api/client'

const auth = useAuthStore()
const router = useRouter()

const email = ref('')
const password = ref('')
const password2 = ref('')
const name = ref('')
const position = ref('')
const loading = ref(false)
const error = ref<string | null>(null)

async function onSubmit() {
  error.value = null
  if (!name.value.trim()) {
    error.value = 'Укажите имя'
    return
  }
  if (password.value !== password2.value) {
    error.value = 'Пароли не совпадают'
    return
  }
  if (password.value.length < 8) {
    error.value = 'Пароль должен быть не короче 8 символов'
    return
  }
  loading.value = true
  try {
    await auth.register({
      email: email.value.trim(),
      password: password.value,
      name: name.value.trim(),
      position: position.value.trim() || null,
    })
    router.push('/chat')
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
      <h1>Регистрация</h1>
      <p class="muted auth-card-subtitle">Agent Chat</p>

      <label>
        Имя
        <input v-model="name" type="text" required maxlength="120" />
      </label>

      <label>
        Должность (необязательно)
        <input v-model="position" type="text" maxlength="120" />
      </label>

      <label>
        Email
        <input v-model="email" type="email" required autocomplete="email" />
      </label>

      <label>
        Пароль
        <input v-model="password" type="password" required minlength="8" autocomplete="new-password" />
      </label>

      <label>
        Повторите пароль
        <input v-model="password2" type="password" required minlength="8" autocomplete="new-password" />
      </label>

      <p v-if="error" class="error">{{ error }}</p>

      <button :disabled="loading" type="submit">
        {{ loading ? 'Создаём…' : 'Создать аккаунт' }}
      </button>

      <p class="switch">
        Уже есть аккаунт?
        <RouterLink to="/login">Войти</RouterLink>
      </p>
    </form>
  </div>
</template>