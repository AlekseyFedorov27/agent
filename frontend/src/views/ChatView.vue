<script setup lang="ts">
import { nextTick, onMounted, ref, watch } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import { useChatStore } from '@/stores/chat'
import MessageItem from '@/components/MessageItem.vue'
import ApprovalCard from '@/components/ApprovalCard.vue'
import ConfirmModal from '@/components/ConfirmModal.vue'

const auth = useAuthStore()
const chat = useChatStore()
const router = useRouter()

const {
  items, loading, loadingThreads, error, pendingApproval, canSend, threads, threadId,
} = storeToRefs(chat)

const draft = ref('')
const listEl = ref<HTMLElement | null>(null)

// --- confirm delete -----------------------------------------------------
const deleteTarget = ref<{ id: string; title: string } | null>(null)

function askDelete(t: { thread_id: string; title: string }) {
  deleteTarget.value = { id: t.thread_id, title: t.title }
}

function cancelDelete() {
  deleteTarget.value = null
}

async function confirmDelete() {
  const target = deleteTarget.value
  deleteTarget.value = null
  if (target) await chat.deleteThread(target.id)
}

// --- scroll / lifecycle -------------------------------------------------
function scrollToBottom() {
  nextTick(() => {
    if (listEl.value) listEl.value.scrollTop = listEl.value.scrollHeight
  })
}

watch(items, scrollToBottom, { deep: true })
watch(pendingApproval, scrollToBottom)

onMounted(async () => {
  await chat.loadThreads()
  if (threadId.value && threads.value.some((t) => t.thread_id === threadId.value)) {
    await chat.loadThread(threadId.value)
  } else if (threads.value.length) {
    await chat.loadThread(threads.value[0].thread_id)
  }
  scrollToBottom()
})

// --- send / misc --------------------------------------------------------
async function send() {
  const text = draft.value
  if (!text.trim() || !canSend.value) return
  draft.value = ''
  await chat.sendStream(text)
}

function onKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
    e.preventDefault()
    send()
  }
}

function logout() {
  auth.logout()
  chat.newChat()
  router.push('/login')
}

function selectThread(id: string) {
  if (id === threadId.value || loading.value) return
  chat.loadThread(id)
}

function fmtDate(iso: string): string {
  const d = new Date(iso)
  const today = new Date()
  const sameDay =
    d.getFullYear() === today.getFullYear() &&
    d.getMonth() === today.getMonth() &&
    d.getDate() === today.getDate()
  const time = d.toLocaleTimeString('ru-RU', { hour: '2-digit', minute: '2-digit' })
  return sameDay ? time : d.toLocaleDateString('ru-RU', { day: '2-digit', month: '2-digit' })
}

const suggestions = [
  'Посчитай (123 + 456) * 7',
  'Посчитай 2**10 + 5',
  'Сколько будет (100 / 4) + 42 * 3?',
]
</script>

<template>
  <div class="app-shell">
    <!-- Sidebar -->
    <aside class="sidebar">
      <div class="sidebar-head">
        <button class="new-chat-btn" @click="chat.newChat()">+ Новый чат</button>
      </div>

      <div class="threads">
        <div v-if="loadingThreads && !threads.length" class="threads-empty muted">
          Загрузка…
        </div>
        <div v-else-if="!threads.length" class="threads-empty muted">
          Пока нет диалогов
        </div>

        <div
          v-for="t in threads"
          :key="t.thread_id"
          class="thread-item"
          :class="{ active: t.thread_id === threadId }"
          @click="selectThread(t.thread_id)"
        >
          <div class="thread-title">{{ t.title }}</div>

          <div class="thread-meta">
            <span class="thread-time">{{ fmtDate(t.updated_at) }}</span>
            <span v-if="t.status === 'interrupted'" class="thread-badge">⏸</span>
            <span v-else-if="t.status === 'failed'" class="thread-badge err">!</span>
          </div>

          <button
            class="thread-delete"
            title="Удалить тред"
            @click.stop="askDelete(t)"
          >×</button>
        </div>
      </div>

      <div class="sidebar-foot">
        <div class="user muted">{{ auth.user?.name || auth.user?.email }}</div>
        <div class="foot-actions">
          <RouterLink v-if="auth.isAdmin" to="/admin" class="ghost-btn">
            Админка
          </RouterLink>
          <button class="ghost-btn" @click="logout">Выйти</button>
        </div>
      </div>
    </aside>

    <!-- Main -->
    <div class="chat-shell">
      <header class="chat-header">
        <div class="brand">
          <span class="logo">🤖</span>
          <div>
            <div class="title">Agent Chat</div>
            <div class="sub muted">
              {{ threadId ? `Тред ${threadId.slice(0, 8)}` : 'Новый диалог' }}
            </div>
          </div>
        </div>
        <div class="sub muted">
          {{ auth.user?.name }}
          <span v-if="auth.user?.position"> · {{ auth.user.position }}</span>
        </div>
      </header>

      <main ref="listEl" class="chat-list">
        <div v-if="!items.length && !loading" class="empty">
          <h2>Начните диалог</h2>
          <p class="muted">
            Агент умеет считать и спрашивает разрешение перед вызовом инструмента.
          </p>
          <div class="suggestions">
            <button
              v-for="s in suggestions"
              :key="s"
              class="suggestion"
              @click="draft = s; send()"
            >
              {{ s }}
            </button>
          </div>
        </div>

        <MessageItem v-for="m in items" :key="m.uid" :item="m" />

        <div v-if="loading" class="typing">
          <span></span><span></span><span></span>
        </div>

        <ApprovalCard v-if="pendingApproval" />
      </main>

      <footer class="chat-footer">
        <div v-if="error" class="error">{{ error }}</div>

        <form class="composer" @submit.prevent="send">
          <textarea
            v-model="draft"
            :disabled="!canSend"
            rows="1"
            :placeholder="pendingApproval
              ? 'Сначала решите по вызову инструмента…'
              : 'Напишите сообщение… (Enter — отправить, Shift+Enter — новая строка)'"
            @keydown="onKeydown"
          ></textarea>

          <button type="submit" :disabled="!canSend || !draft.trim()">
            Отправить
          </button>
        </form>
      </footer>
    </div>

    <!-- Confirm dialog -->
    <ConfirmModal
      :open="!!deleteTarget"
      title="Удалить диалог?"
      :message="deleteTarget
        ? `«${deleteTarget.title}» будет удалён вместе со всей историей сообщений. Это действие нельзя отменить.`
        : ''"
      confirm-text="Удалить"
      cancel-text="Отмена"
      danger
      @confirm="confirmDelete"
      @cancel="cancelDelete"
    />
  </div>
</template>