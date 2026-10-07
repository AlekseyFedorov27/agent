<script setup lang="ts">
import { computed, onBeforeUnmount, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { storeToRefs } from 'pinia'
import { useAuthStore } from '@/stores/auth'
import { useAdminStore } from '@/stores/admin'
import { adminApi, type AdminEventOut } from '@/api/admin'
import ConfirmModal from '@/components/ConfirmModal.vue'
import { renderMarkdown } from '@/utils/markdown'
import RunTimeline from '@/components/RunTimeline.vue'
import { usePolling } from '@/composables/usePolling'

const auth = useAuthStore()
const admin = useAdminStore()
const route = useRoute()
const router = useRouter()

const { runDetail, runDetailLoading, runDetailError } = storeToRefs(admin)

const runId = computed(() => String(route.params.runId || ''))

// ---------------------------------------------------------------------------
// События (аккордеон)
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
  await loadThreadMessages(false)
}

async function loadThreadMessages(silent: boolean) {
  if (!runDetail.value) return
  if (!silent) threadLoading.value = true
  threadError.value = null
  try {
    threadMessages.value = await adminApi.getThreadMessages(
      runDetail.value.thread_id,
    )
  } catch (e) {
    threadError.value = e instanceof Error ? e.message : String(e)
  } finally {
    if (!silent) threadLoading.value = false
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
// Polling
// ---------------------------------------------------------------------------
// true, пока выполняем явную загрузку из onMounted/watch.
// Глушим тики, чтобы не наслаивались.
const loading = ref(false)

async function refreshRun(silent: boolean) {
  if (!runId.value) return
  if (loading.value) return
  loading.value = true
  try {
    await admin.loadRun(runId.value, { silent })
    // если открыт просмотр сообщений — тихо подтягиваем и его
    if (threadMessages.value) {
      await loadThreadMessages(true)
    }
  } finally {
    loading.value = false
  }
}

const { isPolling, start: startPolling, stop: stopPolling, tick } = usePolling(
  async () => {
    // stopped/finished runs можно не переpoll-ить так часто,
    // но пока просто проверяем: если runDetail не завершён —
    // обновляем. Готовые тоже обновляем, но реже (см. логику ниже).
    const r = runDetail.value
    if (r && r.completed_at) {
      // завершённый run — обновляем раз в 15 сек вместо 3
      // (простая эвристика через время последнего обновления)
      const now = Date.now()
      if (now - lastFinishedTick.value < 15000) return
      lastFinishedTick.value = now
    }
    await refreshRun(true)
  },
  3000,
  { name: 'admin-run-detail', immediate: false, pauseWhenHidden: true },
)

const lastFinishedTick = ref(0)

// ---------------------------------------------------------------------------
// Trace / workflow visualization
// ---------------------------------------------------------------------------
type TraceStep = { id: string; kind: 'user'|'llm'|'tool'|'approval'|'resume'|'end'|'error'; title: string; subtitle?: string; durationMs?: number; status?: 'done'|'waiting'|'approved'|'rejected'|'error'; eventId?: string }

function formatDuration(ms?: number): string { if (ms == null) return '—'; return ms < 1000 ? `${ms}ms` : `${(ms / 1000).toFixed(2)}s` }
function stepDuration(events: AdminEventOut[], i: number): number | undefined { const next=events[i+1]; if (!next) return undefined; const d=new Date(next.created_at).getTime()-new Date(events[i].created_at).getTime(); return d>=0 ? d : undefined }
function eventToolNames(ev: AdminEventOut): string[] { const messages=(ev.payload as any)?.messages; if (!Array.isArray(messages)) return []; const names:string[]=[]; for (const m of messages) for (const tc of (Array.isArray(m?.tool_calls)?m.tool_calls:[])) if (tc?.name) names.push(String(tc.name)); return [...new Set(names)] }

const traceSteps = computed<TraceStep[]>(() => {
  const r=runDetail.value; if (!r) return []
  const events=[...(r.events||[])].sort((a,b)=>new Date(a.created_at).getTime()-new Date(b.created_at).getTime())
  const steps:TraceStep[]=[]
  if (r.input) steps.push({id:`user-${r.id}`,kind:'user',title:'Пользователь',subtitle:typeof r.input==='string'?r.input:JSON.stringify(r.input),status:'done'})
  for (let i=0;i<events.length;i++) {
    const ev=events[i], durationMs=stepDuration(events,i)
    if (ev.type==='llm_end') {
      const tools=eventToolNames(ev)
      steps.push({id:`llm-${ev.id}`,kind:'llm',title:'LLM',subtitle:tools.length?`Вызов: ${tools.join(', ')}`:'Ответ модели',durationMs,status:'done',eventId:ev.id})
      for (const tool of tools) steps.push({id:`tool-${ev.id}-${tool}`,kind:'tool',title:tool,subtitle:'Инструмент',status:'done',eventId:ev.id})
    } else if (ev.type==='tool_end') {
      const tools=eventToolNames(ev); steps.push({id:`tool-end-${ev.id}`,kind:'tool',title:tools.join(', ')||'Инструмент',subtitle:'Выполнение завершено',durationMs,status:'done',eventId:ev.id})
    } else if (ev.type==='interrupt') steps.push({id:`approval-${ev.id}`,kind:'approval',title:'Ожидание подтверждения',subtitle:'waiting for approval',durationMs,status:'waiting',eventId:ev.id})
    else if (ev.type==='resume') { const approved=Boolean((ev.payload as any)?.approved); steps.push({id:`resume-${ev.id}`,kind:'resume',title:approved?'Подтверждено':'Отклонено',subtitle:approved?'Пользователь подтвердил действие':'Пользователь отклонил действие',durationMs,status:approved?'approved':'rejected',eventId:ev.id}) }
    else if (ev.type==='error') steps.push({id:`error-${ev.id}`,kind:'error',title:'Ошибка',subtitle:payloadSummary(ev),durationMs,status:'error',eventId:ev.id})
    else if (ev.type==='end') steps.push({id:`end-${ev.id}`,kind:'end',title:'END',subtitle:'Run завершён',status:'done',eventId:ev.id})
  }
  if (r.completed_at && !steps.some(s=>s.kind==='end')) steps.push({id:`end-${r.id}`,kind:'end',title:'END',subtitle:r.status,status:'done'})
  return steps
})

const currentTraceStep = computed(() => { const s=traceSteps.value; if (!s.length) return null; if (runDetail.value?.completed_at) return s[s.length-1]; return [...s].reverse().find(x=>x.kind!=='user')??s[0] })
const runStatusLabel = computed(() => { const r=runDetail.value; if (!r) return ''; if (r.completed_at) return r.status==='error'?'ERROR':'COMPLETED'; if (currentTraceStep.value?.kind==='approval') return 'WAITING FOR APPROVAL'; return 'RUNNING' })
function traceIcon(kind:TraceStep['kind']):string { return ({user:'👤',llm:'🧠',tool:'🔧',approval:'⏸',resume:'✓',error:'!',end:'✓'} as Record<string,string>)[kind] }
function scrollToEvent(eventId?:string) { if (!eventId) return; expanded.value[eventId]=true; requestAnimationFrame(()=>document.getElementById(`event-${eventId}`)?.scrollIntoView({behavior:'smooth',block:'center'})) }

// Lifecycle
// ---------------------------------------------------------------------------

// при смене :runId в URL — грузим заново и сбрасываем аккордеон
watch(runId, async (id) => {
  if (!id) return
  expanded.value = {}
  threadMessages.value = null
  threadError.value = null
  await refreshRun(false)
}, { immediate: false })

onMounted(async () => {
  if (!runId.value) return
  await refreshRun(false)
  startPolling()
})

onBeforeUnmount(() => {
  stopPolling()
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
        <div class="live-indicator" :class="{ active: isPolling }">
          <span class="dot"></span>
          <span class="live-text">{{ isPolling ? 'LIVE' : 'пауза' }}</span>
          <button
            class="ghost-btn small-btn"
            :title="isPolling ? 'Остановить автообновление' : 'Включить автообновление'"
            @click="isPolling ? stopPolling() : startPolling()"
          >
            {{ isPolling ? 'Пауза' : 'Включить' }}
          </button>
        </div>

        <button class="ghost-btn" @click="tick()" title="Обновить сейчас">
          Обновить
        </button>
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
        v-if="runDetailLoading && !runDetail"
        class="muted"
        style="padding: 20px; text-align: center"
      >
        Загрузка…
      </div>

      <template v-else-if="runDetail">
        <!-- Мета run -->
        <section class="run-meta">
          <RunTimeline :run="runDetail" />
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

        <div v-if="threadLoading" class="muted" style="padding: 12px">
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

        <!-- Trace / workflow -->
        <section class="trace-section">
          <div class="section-title-row">
            <h3 class="section-title">Trace</h3>
            <span class="run-status" :class="`status-${runStatusLabel.toLowerCase().replaceAll(' ', '-')}`">
              <span class="status-dot"></span>{{ runStatusLabel }}
            </span>
          </div>
          <div class="trace-card">
            <div class="trace-header">
              <strong>Workflow run <span class="muted">{{ runId.slice(0, 8) }}</span></strong>
              <span v-if="currentTraceStep && !runDetail.completed_at" class="trace-current">Сейчас: <strong>{{ currentTraceStep.title }}</strong></span>
            </div>
            <div class="trace-flow">
              <template v-for="(step, index) in traceSteps" :key="step.id">
                <button class="trace-step" :class="[`trace-${step.kind}`, { 'is-current': currentTraceStep?.id === step.id }]" @click="scrollToEvent(step.eventId)">
                  <div class="trace-icon">{{ traceIcon(step.kind) }}</div>
                  <div class="trace-step-main">
                    <div class="trace-step-title"><span>{{ step.title }}</span><span v-if="step.durationMs != null" class="trace-duration">{{ formatDuration(step.durationMs) }}</span></div>
                    <div v-if="step.subtitle" class="trace-step-subtitle">{{ step.subtitle }}</div>
                    <div v-if="step.status === 'approved'" class="trace-result approved">APPROVED</div>
                    <div v-else-if="step.status === 'rejected'" class="trace-result rejected">REJECTED</div>
                    <div v-else-if="step.status === 'waiting'" class="trace-result waiting">WAITING FOR APPROVAL</div>
                  </div>
                </button>
                <div v-if="index < traceSteps.length - 1" class="trace-connector">↓</div>
              </template>
              <div v-if="!traceSteps.length" class="muted trace-empty">Недостаточно событий для построения Trace.</div>
            </div>
          </div>
        </section>

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
            :id="`event-${ev.id}`"
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
.live-indicator .live-text { min-width: 40px; }
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
.thread-messages::-webkit-scrollbar { width: 8px; }
.thread-messages::-webkit-scrollbar-thumb {
  background: var(--border);
  border-radius: 4px;
}
.thread-msg {
  background: var(--bg-elev-2);
  border-radius: 8px;
  padding: 10px 12px;
}
.thread-msg.is-human { background: rgba(99, 102, 241, 0.1); }
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
.thread-msg-body { word-wrap: break-word; }

  /* ---------- Trace / workflow ---------- */
  .section-title-row { display:flex; align-items:center; justify-content:space-between; gap:12px; margin:8px 0 12px; }
  .section-title-row .section-title { margin:0; }
  .run-status { display:inline-flex; align-items:center; gap:7px; padding:4px 9px; border:1px solid var(--border); border-radius:999px; font-size:10.5px; font-weight:700; letter-spacing:.05em; }
  .status-dot { width:7px; height:7px; border-radius:50%; background:var(--muted); }
  .status-running .status-dot { background:#22c55e; box-shadow:0 0 0 3px rgba(34,197,94,.14); animation:live-pulse 1.5s infinite; }
  .status-waiting-for-approval .status-dot { background:#eab308; box-shadow:0 0 0 3px rgba(234,179,8,.14); }
  .status-completed .status-dot { background:#10b981; }
  .status-error .status-dot { background:#ef4444; }
  .trace-card { background:var(--bg-elev); border:1px solid var(--border); border-radius:var(--radius); padding:16px; margin-bottom:20px; }
  .trace-header { display:flex; align-items:center; justify-content:space-between; gap:16px; padding-bottom:14px; border-bottom:1px solid var(--border); font-size:13px; }
  .trace-current { color:var(--muted); font-size:12px; }
  .trace-current strong { color:var(--text); }
  .trace-flow { display:flex; flex-direction:column; align-items:center; padding:18px 0 4px; }
  .trace-step { width:min(720px,100%); display:flex; align-items:flex-start; gap:13px; text-align:left; padding:12px 14px; background:var(--bg-elev-2); border:1px solid var(--border); border-radius:10px; color:inherit; cursor:pointer; transition:border-color .15s ease,transform .15s ease,background .15s ease; }
  .trace-step:hover { border-color:var(--border-hover); background:rgba(255,255,255,.025); transform:translateY(-1px); }
  .trace-step.is-current { box-shadow:0 0 0 1px rgba(99,102,241,.35); }
  .trace-icon { width:32px; height:32px; flex:0 0 32px; display:grid; place-items:center; border-radius:8px; background:rgba(255,255,255,.05); font-size:15px; }
  .trace-step-main { min-width:0; flex:1; }
  .trace-step-title { display:flex; align-items:center; justify-content:space-between; gap:12px; font-size:13.5px; font-weight:650; }
  .trace-duration { flex:0 0 auto; color:var(--muted); font-family:ui-monospace,SFMono-Regular,Menlo,monospace; font-size:11.5px; font-weight:500; }
  .trace-step-subtitle { margin-top:4px; color:var(--muted); font-size:12px; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
  .trace-result { display:inline-block; margin-top:7px; font-size:10px; font-weight:800; letter-spacing:.05em; }
  .trace-result.approved { color:#22c55e; } .trace-result.rejected { color:#ef4444; } .trace-result.waiting { color:#eab308; }
  .trace-llm { border-left:3px solid #6366f1; } .trace-tool { border-left:3px solid #22c55e; } .trace-approval { border-left:3px solid #eab308; } .trace-resume { border-left:3px solid #3b82f6; } .trace-end { border-left:3px solid #10b981; } .trace-error { border-left:3px solid #ef4444; } .trace-user { border-left:3px solid #8b5cf6; }
  .trace-connector { height:30px; display:grid; place-items:center; color:var(--muted); font-size:15px; }
  .trace-empty { width:100%; padding:20px; text-align:center; }

/* ---------- События ---------- */
.section-title { margin: 8px 0 12px; font-size: 15px; }
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
.event-head:hover { background: rgba(255, 255, 255, 0.02); }
.ev-time {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  color: var(--muted);
  font-size: 12.5px;
}
.ev-type { font-weight: 600; }
.ev-summary {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  font-size: 12.5px;
}
.ev-toggle { text-align: right; color: var(--muted); }
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
.tc-name { font-weight: 600; color: var(--accent-hover); }
.tc-args { color: var(--muted); font-size: 12.5px; }
</style>