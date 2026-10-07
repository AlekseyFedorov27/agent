<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import { useAdminStore } from '@/stores/admin'
import { useChatStore } from '@/stores/chat'

const auth = useAuthStore()
const admin = useAdminStore()
const chatStore = useChatStore()
const router = useRouter()

const { runs, runsLoading, runsError, users } = storeToRefs(admin)

const PAGE_SIZE = 50

const filterUserId = ref<string>('')
const filterStatus = ref<string>('')
const page = ref(0)

const total = computed(() => runs.value?.total ?? 0)
const items = computed(() => runs.value?.items ?? [])
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

function fmtDate(iso: string): string {
  return new Date(iso).toLocaleString('ru-RU', {
    day: '2-digit', month: '2-digit', year: '2-digit',
    hour: '2-digit', minute: '2-digit', second: '2-digit',
  })
}

function duration(run: { created_at: string; completed_at: string | null }): string {
  if (!run.completed_at) return '—'
  const ms = new Date(run.completed_at).getTime() - new Date(run.created_at).getTime()
  if (ms < 1000) return `${ms}ms`
  return `${(ms / 1000).toFixed(2)}s`
}

function statusClass(s: string): string {
  switch (s) {
    case 'completed': return 'badge-ok'
    case 'interrupted': return 'badge-warn'
    case 'failed': return 'badge-off'
    case 'running': return 'badge-info'
    default: return ''
  }
}

onMounted(async () => {
  await Promise.all([admin.load(), refresh()])
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
        <button class="ghost-btn" @click="router.push('/admin')">Пользователи</button>
        <button class="ghost-btn" @click="router.push('/chat')">К чату</button>
        <button class="ghost-btn" @click="auth.logout(); router.push('/login')">Выйти</button>
      </div>
    </header>

    <main class="admin-content">
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
        <span class="muted" style="margin-left: auto">
          Всего: {{ total }}
        </span>
      </div>

      <p v-if="runsError" class="error">{{ runsError }}</p>

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
          <tr v-for="r in items" :key="r.id" class="run-row" @click="openRun(r.id)">
            <td class="muted small">{{ fmtDate(r.created_at) }}</td>
            <td>
              <div class="cell-name">
                {{ r.user_name }}
                <span class="muted small">{{ r.user_email }}</span>
              </div>
            </td>
            <td>
              <code class="thread-id">{{ r.thread_id.slice(0, 8) }}</code>
            </td>
            <td>
              <span :class="['badge', statusClass(r.status)]">{{ r.status }}</span>
            </td>
            <td class="run-input">
              {{ (r.input as any)?.message?.slice(0, 60) || '—' }}
            </td>
            <td class="muted small">{{ duration(r) }}</td>
            <td class="muted small">›</td>
          </tr>
        </tbody>
      </table>

      <div v-if="runsLoading" class="muted" style="padding: 20px; text-align: center;">
        Загрузка…
      </div>
      <div v-else-if="!items.length" class="muted" style="padding: 20px; text-align: center;">
        Runs не найдены
      </div>

      <div class="runs-pagination">
        <button class="ghost-btn" :disabled="!canPrev" @click="prevPage">← Prev</button>
        <span class="muted">Стр. {{ page + 1 }}</span>
        <button class="ghost-btn" :disabled="!canNext" @click="nextPage">Next →</button>
      </div>
    </main>
  </div>
</template>

<style scoped>
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
  gap: 3px;
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

.run-row { cursor: pointer; }
.run-row:hover td { background: rgba(255, 255, 255, 0.03); }
.run-input {
  max-width: 260px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.thread-id {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12.5px;
  color: var(--muted);
}
.runs-pagination {
  display: flex;
  gap: 12px;
  align-items: center;
  justify-content: center;
  margin-top: 18px;
}
.badge-info { background: rgba(99, 102, 241, 0.18); color: #a5a8ff; }
.badge-warn { background: rgba(234, 179, 8, 0.18); color: #fbbf24; }
</style>