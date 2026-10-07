<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import { useAdminStore } from '@/stores/admin'
import UserModal from '@/components/UserModal.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'
import type { UserPublic } from '@/api/auth'
import type { AdminUserCreate, AdminUserUpdate } from '@/api/admin'

const auth = useAuthStore()
const admin = useAdminStore()
const router = useRouter()

const { users, loading, error } = storeToRefs(admin)

const editing = ref<UserPublic | null>(null)
const modalOpen = ref(false)
const deleteTarget = ref<UserPublic | null>(null)
const actionError = ref<string | null>(null)

onMounted(() => admin.load())

function openCreate() {
  editing.value = null
  modalOpen.value = true
}

function openEdit(u: UserPublic) {
  editing.value = u
  modalOpen.value = true
}

async function onSave(payload: AdminUserCreate | AdminUserUpdate) {
  actionError.value = null
  if (editing.value) {
    await admin.update(editing.value.id, payload as AdminUserUpdate)
  } else {
    await admin.create(payload as AdminUserCreate)
  }
}

async function confirmDelete() {
  const target = deleteTarget.value
  deleteTarget.value = null
  if (!target) return
  try {
    await admin.remove(target.id)
  } catch (e) {
    actionError.value = String(e)
  }
}

function fmtDate(iso: string): string {
  const d = new Date(iso)
  return d.toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit',
  })
}

const isSelf = (u: UserPublic) => u.id === auth.user?.id
</script>

<template>
  <div class="admin-shell">
    <header class="admin-header">
      <div class="brand">
        <span class="logo">🛠</span>
        <div>
          <div class="title">Администрирование</div>
          <div class="sub muted">Управление пользователями</div>
        </div>
      </div>

      <div class="actions">
        <button class="ghost-btn" @click="router.push('/admin')">Пользователи</button>
        <button class="ghost-btn" @click="router.push('/admin/runs')">Runs</button>
        <button class="ghost-btn" @click="router.push('/chat')">К чату</button>
        <button class="ghost-btn" @click="auth.logout(); router.push('/login')">Выйти</button>
      </div>
    </header>

    <main class="admin-content">
      <div class="admin-toolbar">
        <div class="muted">Всего: {{ users.length }}</div>
        <button @click="openCreate">+ Добавить пользователя</button>
      </div>

      <p v-if="error" class="error">{{ error }}</p>
      <p v-if="actionError" class="error">{{ actionError }}</p>

      <table class="users-table">
        <thead>
          <tr>
            <th>Имя</th>
            <th>Email</th>
            <th>Должность</th>
            <th>Промпт</th>
            <th>Статус</th>
            <th>Создан</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr v-for="u in users" :key="u.id">
            <td>
              <div class="cell-name">
                {{ u.name }}
                <span v-if="u.is_superuser" class="badge badge-admin">admin</span>
              </div>
            </td>
            <td class="muted">{{ u.email }}</td>
            <td>{{ u.position || '—' }}</td>
            <td>
              <span v-if="u.system_prompt" class="prompt-preview" :title="u.system_prompt">
                {{ u.system_prompt.slice(0, 40) }}{{ u.system_prompt.length > 40 ? '…' : '' }}
              </span>
              <span v-else class="muted">—</span>
            </td>
            <td>
              <span :class="['badge', u.is_active ? 'badge-ok' : 'badge-off']">
                {{ u.is_active ? 'активен' : 'выключен' }}
              </span>
            </td>
            <td class="muted small">{{ fmtDate(u.created_at) }}</td>
            <td class="row-actions">
              <button class="ghost-btn small-btn" @click="openEdit(u)">Изменить</button>
              <button
                class="ghost-btn small-btn danger"
                :disabled="isSelf(u)"
                :title="isSelf(u) ? 'Нельзя удалить себя' : 'Удалить'"
                @click="deleteTarget = u"
              >Удалить</button>
            </td>
          </tr>
        </tbody>
      </table>

      <div v-if="loading" class="muted" style="padding: 20px; text-align: center;">Загрузка…</div>
      <div v-else-if="!users.length" class="muted" style="padding: 20px; text-align: center;">
        Нет пользователей
      </div>
    </main>

    <UserModal
      :open="modalOpen"
      :user="editing"
      :save-fn="onSave"
      @close="modalOpen = false"
    />

    <ConfirmModal
      :open="!!deleteTarget"
      title="Удалить пользователя?"
      :message="deleteTarget
        ? `«${deleteTarget.name}» (${deleteTarget.email}) будет удалён со всеми его тредами, ранами и одобрениями. Это действие нельзя отменить.`
        : ''"
      confirm-text="Удалить"
      cancel-text="Отмена"
      danger
      @confirm="confirmDelete"
      @cancel="deleteTarget = null"
    />
  </div>
</template>