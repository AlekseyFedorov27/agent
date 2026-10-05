<script setup lang="ts">
import { computed, reactive, ref, watch } from 'vue'
import type { UserPublic } from '@/api/auth'
import type { AdminUserCreate, AdminUserUpdate } from '@/api/admin'
import { extractApiError } from '@/api/client'

const props = defineProps<{
  open: boolean
  user?: UserPublic | null
  saveFn: (payload: AdminUserCreate | AdminUserUpdate) => Promise<void>
}>()

const emit = defineEmits<{ (e: 'close'): void }>()

const isEdit = computed(() => !!props.user)

const form = reactive({
  email: '',
  password: '',
  name: '',
  position: '',
  system_prompt: '',
  is_active: true,
  is_superuser: false,
})

const error = ref<string | null>(null)
const working = ref(false)

watch(
  () => [props.open, props.user],
  () => {
    if (!props.open) return
    error.value = null
    if (props.user) {
      form.email = props.user.email
      form.password = ''
      form.name = props.user.name
      form.position = props.user.position ?? ''
      form.system_prompt = props.user.system_prompt ?? ''
      form.is_active = props.user.is_active
      form.is_superuser = props.user.is_superuser
    } else {
      form.email = ''
      form.password = ''
      form.name = ''
      form.position = ''
      form.system_prompt = ''
      form.is_active = true
      form.is_superuser = false
    }
  },
  { immediate: true },
)

async function onSubmit() {
  error.value = null
  if (!form.name.trim()) {
    error.value = 'Укажите имя'
    return
  }
  if (!isEdit.value) {
    if (!form.email.trim()) {
      error.value = 'Укажите email'
      return
    }
    if (form.password.length < 8) {
      error.value = 'Пароль должен быть не короче 8 символов'
      return
    }
  } else if (form.password && form.password.length < 8) {
    error.value = 'Пароль должен быть не короче 8 символов'
    return
  }

  const base = {
    name: form.name.trim(),
    position: form.position.trim() || null,
    system_prompt: form.system_prompt.trim() || null,
    is_active: form.is_active,
    is_superuser: form.is_superuser,
  }

  working.value = true
  try {
    if (isEdit.value) {
      const payload: AdminUserUpdate = { ...base }
      if (form.password) payload.password = form.password
      await props.saveFn(payload)
    } else {
      const payload: AdminUserCreate = {
        ...base,
        email: form.email.trim(),
        password: form.password,
      }
      await props.saveFn(payload)
    }
    emit('close')
  } catch (e) {
    error.value = extractApiError(e)
  } finally {
    working.value = false
  }
}
</script>

<template>
  <Teleport to="body">
    <Transition name="modal-fade">
      <div v-if="open" class="modal-backdrop">
        <div class="modal-card modal-card-wide" role="dialog" aria-modal="true">
          <h3 class="modal-title">
            {{ isEdit ? 'Редактировать пользователя' : 'Новый пользователь' }}
          </h3>

          <div class="form-grid">
            <label class="form-field">
              Имя
              <input v-model="form.name" type="text" maxlength="120" required />
            </label>

            <label class="form-field">
              Должность (необязательно)
              <input v-model="form.position" type="text" maxlength="120" />
            </label>
          </div>

          <label class="form-field">
            Email
            <input
              v-model="form.email"
              type="email"
              :disabled="isEdit"
              required
            />
          </label>

          <label class="form-field">
            {{ isEdit ? 'Новый пароль (оставьте пустым, чтобы не менять)' : 'Пароль' }}
            <input
              v-model="form.password"
              type="password"
              :required="!isEdit"
              minlength="8"
              autocomplete="new-password"
            />
          </label>

          <label class="form-field">
            Системный промпт (свой)
            <textarea
              v-model="form.system_prompt"
              rows="5"
              maxlength="8000"
              placeholder="Например: отвечай как опытный аналитик, используй таблицы..."
            ></textarea>
          </label>

          <div class="form-toggles">
            <label class="toggle">
              <input v-model="form.is_active" type="checkbox" />
              Активен
            </label>
            <label class="toggle">
              <input v-model="form.is_superuser" type="checkbox" />
              Администратор
            </label>
          </div>

          <p v-if="error" class="error">{{ error }}</p>

          <div class="modal-actions">
            <button class="ghost-btn" :disabled="working" @click="emit('close')">Отмена</button>
            <button :disabled="working" @click="onSubmit">
              {{ working ? 'Сохраняем…' : 'Сохранить' }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>