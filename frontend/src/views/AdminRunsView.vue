<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import { useAdminStore } from '@/stores/admin'
import { usePolling } from '@/composables/usePolling'
import type { AdminRunOut } from '@/api/admin'

const auth = useAuthStore()
const admin = useAdminStore()
const router = useRouter()

const { runs, runsLoading, runsError, users } = storeToRefs(admin)

const PAGE_SIZE = 50

// ---------------------------------------------------------------------------
// Фильтры и пагинация
// ---------------------------------------------------------------------------
const filterUserId = ref<string>('')
const filterStatus = ref<string>('')
const page = ref(0)

const total = computed(() => runs.value?.total ?? 0)
const items = computed<AdminRunOut[]>(() => runs.value?.items ?? [])
const canPrev = computed(() => page.value > 0)
const canNext = computed(() => (page.value + 1) * PAGE_SIZE < total.value)

async function refresh() {
  const filters: {
    user_id?: string
    status?: string
    limit: number
    offset: number
  } = {
    limit: PAGE_SIZE,
    offset: page.value * PAGE_SIZE,
  }
  if (filterUserId.value) filters.user_id = filterUserId.value
  if (filterStatus.value) filters.status = filterStatus.value

  await admin.loadRuns(filters)
}

function applyFilters() {
  page.value = 0
  refresh()
}

function resetFilters() {
  filterUserId.value = ''
  filterStatus.value = ''
  page.value = 0
  refresh()
}

function prevPage() {
  if (!canPrev.value) return
  page.value -= 1
  refresh()
}

function nextPage() {
  if (!canNext.value) return
  page.value += 1
  refresh()
}

function openRun(id: string) {
  router.push(`/admin/runs/${id}`)
}

// ---------------------------------------------------------------------------
// Live polling
// ---------------------------------------------------------------------------
// Если открыта модалка/дропдаун или вкладка в фоне — polling ставим на паузу.
// Простое правило: не мигаем списком, когда пользователь не смотрит.
const paused = ref(false)

const { isPolling, start: startPolling, stop: stopPolling } = usePolling(
  async () => {
    if (paused.value) {
      console.debug('[admin-runs] paused, skip')
      return
    }
    await refresh()
  },
  1000,
  { name: 'admin-runs', immediate: false, pauseWhenHidden: true },
)

function togglePolling() {
  if (isPolling.value) {
    stopPolling()
  } else {
    startPolling()
  }
}

function onVisibilityChange() {
  // Список обновится сам, когда вкладка вернётся в фокус
  if (!document.hidden && isPolling.value) {
    void refresh()
  }
}

// ---------------------------------------------------------------------------
// Форматирование
// ---------------------------------------------------------------------------
function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit',
    month: '2-digit',
    year: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
}

function duration(run: AdminRunOut): string {
  if (!run.completed_at) {
    // Running или interrupted без завершения — считаем от текущего момента
    const ms = Date.now() - new Date(run.created_at).getTime()
    return ms < 60000 ? `${(ms / 1000).toFixed(1)}s…` : '—'
  }
  const ms =
    new Date(run.completed_at).getTime() - new Date(run.created_at).getTime()
  return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(2)}s`
}

function statusClass(s: string): string {
  switch (s) {
    case 'completed':
      return 'badge-ok'
    case 'interrupted':
      return 'badge-warn'
    case 'failed':
      return 'badge-off'
    case 'running':
      return 'badge-info'
    default:
      return ''
  }
}

function inputPreview(run: AdminRunOut): string {
  const msg = (run.input as { message?: string })?.message
  if (!msg) return '—'
  return msg.length > 60 ? `${msg.slice(0, 60)}…` : msg
}

function shortThread(tid: string): string {
  return tid.slice(0, 8)
}



// ---------------------------------------------------------------------------
// Lifecycle
// ---------------------------------------------------------------------------
onMounted(async () => {
  await Promise.all([admin.load(), refresh()])
})

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<template>
  <div class="admin-shell">
    <header class="admin-header">
      <div class="brand">
        <span class="logo">📜</span>
        <div>
          <div class="title">Runs</div>
          <div class="sub muted">Все прогоны агента</div>
        </div>
      </div>

      <div class="actions">
        <div class="live-indicator" :class="{ active: isPolling }">
          <span class="dot"></span>
          <span class="live-text">{{ isPolling ? 'LIVE' : 'пауза' }}</span>
          <button
            class="ghost-btn small-btn"
            :title="isPolling ? 'Остановить автообновление' : 'Включить автообновление'"
            @click="togglePolling"
          >
            {{ isPolling ? 'Пауза' : 'Включить' }}
          </button>
        </div>

        <button class="ghost-btn" @click="router.push('/admin')">
          Пользователи
        </button>
        <button class="ghost-btn" @click="router.push('/chat')">
          К чату
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
      <!-- Фильтры -->
      <div class="runs-filters">
        <label class="filter-field">
          Пользователь
          <select v-model="filterUserId" @change="applyFilters">
            <option value="">Все</option>
            <option v-for="u in users" :key="u.id" :value="u.id">
              {{ u.name }} ({{ u.email }})
            </option>
          </select>
        </label>

        <label class="filter-field">
          Статус
          <select v-model="filterStatus" @change="applyFilters">
            <option value="">Любой</option>
            <option value="running">running</option>
            <option value="interrupted">interrupted</option>
            <option value="completed">completed</option>
            <option value="failed">failed</option>
          </select>
        </label>

        <button class="ghost-btn" @click="resetFilters">Сбросить</button>

        <span class="muted runs-total">Всего: {{ total }}</span>
      </div>

      <p v-if="runsError" class="error">{{ runsError }}</p>

      <!-- Таблица -->
      <table class="users-table">
        <thead>
          <tr>
            <th>Время</th>
            <th>Пользователь</th>
            <th>Thread</th>
            <th>Статус</th>
            <th>Запрос</th>
            <th>Длительность</th>
            <th></th>
          </tr>
        </thead>
        <tbody>
          <tr
            v-for="r in items"
            :key="r.id"
            class="run-row"
            @click="openRun(r.id)"
          >
            <td class="muted small">{{ fmtDate(r.created_at) }}</td>
            <td>
              <div class="cell-name">
                <span class="user-name">{{ r.user_name }}</span>
                <span class="muted small">{{ r.user_email }}</span>
              </div>
            </td>
            <td>
              <code class="thread-id" :title="r.thread_id">
                {{ shortThread(r.thread_id) }}
              </code>
            </td>
            <td>
              <span :class="['badge', statusClass(r.status)]">
                {{ r.status }}
              </span>
            </td>
            <td class="run-input" :title="(r.input as any)?.message || ''">
              {{ inputPreview(r) }}
            </td>
            <td class="muted small">{{ duration(r) }}</td>
            <td class="muted small run-chevron">›</td>
          </tr>
        </tbody>
      </table>

      <div
        v-if="runsLoading && !items.length"
        class="muted"
        style="padding: 20px; text-align: center"
      >
        Загрузка…
      </div>
      <div
        v-else-if="!items.length"
        class="muted"
        style="padding: 20px; text-align: center"
      >
        Runs не найдены
      </div>

      <!-- Пагинация -->
      <div v-if="total > PAGE_SIZE" class="runs-pagination">
        <button class="ghost-btn" :disabled="!canPrev" @click="prevPage">
          ← Prev
        </button>
        <span class="muted">Стр. {{ page + 1 }}</span>
        <button class="ghost-btn" :disabled="!canNext" @click="nextPage">
          Next →
        </button>
      </div>
    </main>
  </div>
</template>

<style scoped>
/* ---------- Фильтры ---------- */
.runs-filters {
  display: flex;
  gap: 14px;
  align-items: flex-end;
  margin-bottom: 16px;
  flex-wrap: wrap;
}
.filter-field {
  display: flex;
  flex-direction: column;
  gap: 4px;
  font-size: 12px;
  color: var(--muted);
}
.filter-field select {
  min-width: 220px;
  padding: 6px 10px;
  background: var(--bg-elev);
  color: var(--text);
  border-radius: 6px;
}
.filter-field select option {
  font-family: inherit;
}
.runs-total {
  margin-left: auto;
  font-size: 13px;
}

/* ---------- Live indicator ---------- */
.live-indicator {
  display: inline-flex;
  gap: 8px;
  align-items: center;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: 999px;
  font-size: 11.5px;
  color: var(--muted);
  letter-spacing: 0.04em;
  text-transform: uppercase;
  font-weight: 600;
}
.live-indicator .dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--border-hover);
  transition: background 0.15s ease, box-shadow 0.15s ease;
}
.live-indicator.active .dot {
  background: #22c55e;
  box-shadow: 0 0 0 3px rgba(34, 197, 94, 0.18);
  animation: live-pulse 1.5s infinite;
}
.live-indicator .live-text {
  min-width: 40px;
}
.live-indicator .small-btn {
  padding: 2px 8px;
  font-size: 11px;
  text-transform: none;
  letter-spacing: 0;
}
@keyframes live-pulse {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.45; }
}

/* ---------- Таблица ---------- */
.run-row {
  cursor: pointer;
}
.run-row:hover td {
  background: rgba(255, 255, 255, 0.03);
}
.user-name {
  font-weight: 600;
}
.run-input {
  max-width: 280px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.thread-id {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12.5px;
  color: var(--muted);
}
.run-chevron {
  text-align: right;
  font-size: 16px;
}

/* ---------- Пагинация ---------- */
.runs-pagination {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: center;
  margin-top: 18px;
}

/* ---------- Бейджи статуса ---------- */
.badge-info {
  background: rgba(99, 102, 241, 0.18);
  color: #a5a8ff;
}
.badge-warn {
  background: rgba(234, 179, 8, 0.18);
  color: #fbbf24;
}
</style>