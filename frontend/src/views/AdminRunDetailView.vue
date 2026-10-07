<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import { useAdminStore } from '@/stores/admin'
import { adminApi, type AdminEventOut } from '@/api/admin'
import ConfirmModal from '@/components/ConfirmModal.vue'
import { renderMarkdown } from '@/utils/markdown'

const auth = useAuthStore()
const admin = useAdminStore()
const route = useRoute()
const router = useRouter()

const { runDetail, runDetailLoading, runDetailError } = storeToRefs(admin)

const runId = computed(() => String(route.params.runId || ''))

// ---------------------------------------------------------------------------
// События
// ---------------------------------------------------------------------------
const expanded = ref<Record<string, boolean>>({})

function toggle(id: string) {
  expanded.value[id] = !expanded.value[id]
}

function fmtTime(iso: string): string {
  return new Date(iso).toLocaleTimeString('ru-RU', {
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function fmtFull(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU')
}

function durationStr(): string {
  const r = runDetail.value
  if (!r || !r.completed_at) return '—'
  const ms = new Date(r.completed_at).getTime() - new Date(r.created_at).getTime()
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(2)}s`
}

function eventClass(type: string): string {
  switch (type) {
    case 'llm_end': return 'ev-llm'
    case 'tool_end': return 'ev-tool'
    case 'interrupt': return 'ev-interrupt'
    case 'resume': return 'ev-resume'
    case 'end': return 'ev-end'
    case 'error': return 'ev-error'
    default: return 'ev-node'
  }
}

function payloadSummary(ev: AdminEventOut): string {
  const p = ev.payload || {}
  if (ev.type === 'llm_end' && (p as any).messages) {
    const m = (p as any).messages
    return `${m.length} message(s)`
  }
  if (ev.type === 'tool_end' && (p as any).messages) {
    const m = (p as any).messages
    return m.map((x: any) => x.tool_calls?.[0]?.name || 'tool').join(', ')
  }
  if (ev.type === 'error') {
    return String((p as any).error || 'error').slice(0, 80)
  }
  if (ev.type === 'interrupt') return 'waiting for approval'
  if (ev.type === 'resume') return (p as any).approved ? 'approved' : 'rejected'
  return JSON.stringify(p).slice(0, 80)
}

function prettyJson(v: unknown): string {
  try {
    return JSON.stringify(v, null, 2)
  } catch {
    return String(v)
  }
}

// ---------------------------------------------------------------------------
// Сообщения треда (readonly-просмотр для админа)
// ---------------------------------------------------------------------------
type ThreadMessage = {
  type: string
  content: string
  tool_calls: Array<Record<string, unknown>> | null
}

const threadMessages = ref<ThreadMessage[] | null>(null)
const threadLoading = ref(false)
const threadError = ref<string | null>(null)

async function toggleThread() {
  if (threadMessages.value) {
    threadMessages.value = null
    return
  }
  if (!runDetail.value) return

  threadLoading.value = true
  threadError.value = null
  try {
    threadMessages.value = await adminApi.getThreadMessages(
      runDetail.value.thread_id,
    )
  } catch (e) {
    threadError.value = e instanceof Error ? e.message : String(e)
  } finally {
    threadLoading.value = false
  }
}

function roleLabel(t: string): string {
  const map: Record<string, string> = {
    human: 'Вы',
    ai: 'Агент',
    tool: 'Инструмент',
    system: 'Система',
  }
  return map[t] ?? t
}

function renderContent(m: ThreadMessage): string {
  return renderMarkdown(m.content)
}

// ---------------------------------------------------------------------------
// Удаление треда
// ---------------------------------------------------------------------------
const confirmDelete = ref(false)
const deleting = ref(false)
const deleteError = ref<string | null>(null)

async function doDeleteThread() {
  if (!runDetail.value || deleting.value) return
  deleting.value = true
  deleteError.value = null
  try {
    await adminApi.deleteThread(runDetail.value.thread_id)
    confirmDelete.value = false
    router.push('/admin/runs')
  } catch (e) {
    deleteError.value = e instanceof Error ? e.message : String(e)
    confirmDelete.value = false
  } finally {
    deleting.value = false
  }
}

// ---------------------------------------------------------------------------
onMounted(() => {
  if (runId.value) admin.loadRun(runId.value)
})
</script>

<template>
  <div class="admin-shell">
    <header class="admin-header">
      <div class="brand">
        <span class="logo">🔍</span>
        <div>
          <div class="title">Run {{ runId.slice(0, 8) }}</div>
          <div class="sub muted">Детали прогона</div>
        </div>
      </div>
      <div class="actions">
        <button class="ghost-btn" @click="router.push('/admin/runs')">
          ← К списку
        </button>
        <button
          class="ghost-btn"
          @click="auth.logout(); router.push('/login')"
        >
          Выйти
        </button>
      </div>
    </header>

    <main class="admin-content">
      <p v-if="runDetailError" class="error">{{ runDetailError }}</p>
      <p v-if="deleteError" class="error">{{ deleteError }}</p>

      <div
        v-if="runDetailLoading"
        class="muted"
        style="padding: 20px; text-align: center"
      >
        Загрузка…
      </div>

      <template v-else-if="runDetail">
        <!-- Мета run -->
        <section class="run-meta">
          <div class="meta-row">
            <span class="muted">Пользователь:</span>
            <strong>{{ runDetail.user_name }}</strong>
            <span class="muted">{{ runDetail.user_email }}</span>
          </div>
          <div class="meta-row">
            <span class="muted">Thread:</span>
            <code>{{ runDetail.thread_id }}</code>
          </div>
          <div class="meta-row">
            <span class="muted">Статус:</span>
            <span class="badge">{{ runDetail.status }}</span>
          </div>
          <div class="meta-row">
            <span class="muted">Создан:</span>
            <span>{{ fmtFull(runDetail.created_at) }}</span>
          </div>
          <div class="meta-row">
            <span class="muted">Завершён:</span>
            <span>
              {{ runDetail.completed_at ? fmtFull(runDetail.completed_at) : '—' }}
            </span>
            <span class="muted">({{ durationStr() }})</span>
          </div>
          <div class="meta-row">
            <span class="muted">Запрос:</span>
            <code>{{ JSON.stringify(runDetail.input) }}</code>
          </div>
        </section>

        <!-- Действия по треду -->
        <div class="thread-actions">
          <button class="ghost-btn" @click="toggleThread">
            {{ threadMessages ? 'Скрыть сообщения' : 'Показать сообщения треда' }}
          </button>
          <button
            class="ghost-btn danger"
            :disabled="deleting"
            @click="confirmDelete = true"
          >
            Удалить thread
          </button>
        </div>

        <p v-if="threadError" class="error">{{ threadError }}</p>

        <div
          v-if="threadLoading"
          class="muted"
          style="padding: 12px"
        >
          Загрузка сообщений…
        </div>

        <!-- Сообщения треда -->
        <div v-if="threadMessages" class="thread-messages">
          <div v-if="!threadMessages.length" class="muted" style="padding: 8px">
            В треде нет сообщений
          </div>
          <div
            v-for="(m, i) in threadMessages"
            :key="i"
            class="thread-msg"
            :class="`is-${m.type}`"
          >
            <div class="thread-msg-role">{{ roleLabel(m.type) }}</div>
            <div
              v-if="m.content"
              class="md thread-msg-body"
              v-html="renderContent(m)"
            ></div>
            <div v-if="m.tool_calls?.length" class="tool-calls">
              <div
                v-for="(tc, j) in m.tool_calls"
                :key="j"
                class="tool-call"
              >
                <span class="tc-name">⚙ {{ (tc as any).name }}</span>
                <code class="tc-args">
                  {{ JSON.stringify((tc as any).args) }}
                </code>
              </div>
            </div>
          </div>
        </div>

        <!-- События -->
        <h3 class="section-title">
          События ({{ runDetail.events.length }})
        </h3>

        <div class="events">
          <div
            v-for="ev in runDetail.events"
            :key="ev.id"
            class="event"
            :class="eventClass(ev.type)"
          >
            <div class="event-head" @click="toggle(ev.id)">
              <span class="ev-time">{{ fmtTime(ev.created_at) }}</span>
              <span class="ev-type">{{ ev.type }}</span>
              <span class="ev-summary muted">{{ payloadSummary(ev) }}</span>
              <span class="ev-toggle">{{ expanded[ev.id] ? '▾' : '▸' }}</span>
            </div>
            <pre
              v-if="expanded[ev.id]"
              class="event-payload"
            >{{ prettyJson(ev.payload) }}</pre>
          </div>
        </div>
      </template>
    </main>

    <ConfirmModal
      :open="confirmDelete"
      title="Удалить thread?"
      :message="`Thread ${runDetail?.thread_id.slice(0, 8) ?? ''} и все его runs, события и approvals будут удалены. Действие необратимо.`"
      confirm-text="Удалить"
      cancel-text="Отмена"
      danger
      @confirm="doDeleteThread"
      @cancel="confirmDelete = false"
    />
  </div>
</template>

<style scoped>
/* ---------- Мета run ---------- */
.run-meta {
  background: var(--bg-elev);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 18px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 20px;
}
.meta-row {
  display: flex;
  gap: 10px;
  align-items: baseline;
  font-size: 14px;
  flex-wrap: wrap;
}
.meta-row code {
  font-size: 12.5px;
  background: rgba(255, 255, 255, 0.06);
  padding: 2px 6px;
  border-radius: 4px;
}

/* ---------- Действия по треду ---------- */
.thread-actions {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.ghost-btn.danger {
  color: var(--danger);
  border-color: rgba(239, 68, 68, 0.4);
}
.ghost-btn.danger:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.1);
}

/* ---------- Сообщения треда ---------- */
.thread-messages {
  display: flex;
  flex-direction: column;
  gap: 10px;
  margin-bottom: 20px;
  padding: 12px;
  background: var(--bg-elev);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  max-height: 600px;
  overflow-y: auto;
}
.thread-messages::-webkit-scrollbar {
  width: 8px;
}
.thread-messages::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 4px;
}
.thread-msg {
  background: var(--bg-elev-2);
  border-radius: 8px;
  padding: 10px 12px;
}
.thread-msg.is-human {
  background: rgba(99, 102, 241, 0.1);
}
.thread-msg.is-tool {
  background: #131820;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 13px;
}
.thread-msg-role {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--muted);
  margin-bottom: 6px;
  font-weight: 600;
}
.thread-msg-body {
  word-wrap: break-word;
}

/* ---------- События ---------- */
.section-title {
  margin: 8px 0 12px;
  font-size: 15px;
}
.events {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.event {
  background: var(--bg-elev);
  border: 1px solid var(--border);
  border-left-width: 3px;
  border-radius: 8px;
  overflow: hidden;
}
.event-head {
  display: grid;
  grid-template-columns: 90px 110px 1fr 24px;
  gap: 10px;
  align-items: center;
  padding: 8px 12px;
  cursor: pointer;
  font-size: 13.5px;
}
.event-head:hover {
  background: rgba(255, 255, 255, 0.02);
}
.ev-time {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: var(--muted);
  font-size: 12.5px;
}
.ev-type {
  font-weight: 600;
}
.ev-summary {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12.5px;
}
.ev-toggle {
  text-align: right;
  color: var(--muted);
}
.event-payload {
  margin: 0;
  padding: 12px 14px;
  background: #0d1117;
  border-top: 1px solid var(--border);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  line-height: 1.5;
  overflow-x: auto;
  max-height: 400px;
  overflow-y: auto;
  color: #c9d1d9;
}
.ev-llm       { border-left-color: #6366f1; }
.ev-tool      { border-left-color: #22c55e; }
.ev-interrupt { border-left-color: #eab308; }
.ev-resume    { border-left-color: #3b82f6; }
.ev-end       { border-left-color: #10b981; }
.ev-error     { border-left-color: #ef4444; }
.ev-node      { border-left-color: var(--border-hover); }

/* ---------- Tool calls внутри сообщений ---------- */
.tool-calls {
  margin-top: 8px;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.tool-call {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-items: baseline;
  background: rgba(0, 0, 0, 0.25);
  padding: 6px 10px;
  border-radius: 6px;
  font-size: 13px;
}
.tc-name {
  font-weight: 600;
  color: var(--accent-hover);
}
.tc-args {
  color: var(--muted);
  font-size: 12.5px;
}
</style>