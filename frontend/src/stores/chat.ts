import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  agentApi,
  type ApprovalOut,
  type MessageOut,
  type RunResponse,
} from '@/api/agent'
import { extractApiError } from '@/api/client'

export interface ChatItem extends MessageOut {
  uid: string
}

export interface ThreadSummary {
  thread_id: string
  title: string
  status: string
  updated_at: string
}

const LAST_THREAD_KEY = 'agent.last_thread_id'

function uid(): string {
  return crypto.randomUUID()
}

export const useChatStore = defineStore('chat', () => {
  const items = ref<ChatItem[]>([])
  const threadId = ref<string | null>(localStorage.getItem(LAST_THREAD_KEY))
  const pendingApproval = ref<ApprovalOut | null>(null)
  const threads = ref<ThreadSummary[]>([])
  const loading = ref(false)
  const loadingThreads = ref(false)
  const error = ref<string | null>(null)

  const canSend = computed(() => !loading.value && !pendingApproval.value)
  const lastAssistantMessage = computed<ChatItem | null>(() => {
    for (let i = items.value.length - 1; i >= 0; i--) {
      const m = items.value[i]
      if (m.type === 'ai' && m.content?.trim()) return m
    }
    return null
  })

  function _persistThread(id: string | null) {
    if (id) localStorage.setItem(LAST_THREAD_KEY, id)
    else localStorage.removeItem(LAST_THREAD_KEY)
  }

  function _ingestMessages(messages: MessageOut[]) {
    items.value = messages.map((m) => ({ ...m, uid: uid() }))
  }

  async function _refreshPendingFor(thread: string) {
    try {
      const pending = await agentApi.listPendingApprovals()
      pendingApproval.value = pending.find((a) => a.thread_id === thread) ?? null
    } catch {
      pendingApproval.value = null
    }
  }

  function _applyResponse(resp: RunResponse) {
    threadId.value = resp.thread_id
    _persistThread(resp.thread_id)
    _ingestMessages(resp.messages)
    if (resp.status === 'interrupted' && resp.pending_approval_id) {
      pendingApproval.value = {
        id: resp.pending_approval_id,
        thread_id: resp.thread_id,
        status: 'pending',
        payload: {},
        comment: null,
        created_at: new Date().toISOString(),
        decided_at: null,
      }
    } else {
      pendingApproval.value = null
    }
  }

  // --- Список тредов -----------------------------------------------------
  async function loadThreads() {
    loadingThreads.value = true
    try {
      const runs = await agentApi.listRuns()
      // runs отсортированы по created_at DESC — первый встреченный
      // run для thread_id самый свежий
      const map = new Map<string, ThreadSummary>()
      for (const r of runs) {
        if (map.has(r.thread_id)) continue
        const title =
          r.input?.message?.trim().slice(0, 60) ||
          `Тред ${r.thread_id.slice(0, 8)}`
        map.set(r.thread_id, {
          thread_id: r.thread_id,
          title,
          status: r.status,
          updated_at: r.created_at,
        })
      }
      threads.value = [...map.values()]
    } catch (e) {
      error.value = extractApiError(e)
    } finally {
      loadingThreads.value = false
    }
  }

  // --- Загрузка конкретного треда ---------------------------------------
  async function loadThread(id: string) {
    if (loading.value) return
    loading.value = true
    error.value = null
    try {
      const status = await agentApi.getThreadStatus(id)
      threadId.value = id
      _persistThread(id)
      _ingestMessages(status.messages)
      await _refreshPendingFor(id)
    } catch (e) {
      error.value = extractApiError(e)
    } finally {
      loading.value = false
    }
  }

  // --- Отправка ----------------------------------------------------------
  async function send(text: string) {
    const trimmed = text.trim()
    if (!trimmed || loading.value || pendingApproval.value) return

    error.value = null
    loading.value = true
    items.value.push({ uid: uid(), type: 'human', content: trimmed, tool_calls: null })

    try {
      const resp = await agentApi.run(trimmed, threadId.value ?? undefined)
      _applyResponse(resp)
      await loadThreads() // обновляем список в сайдбаре
    } catch (e) {
      error.value = extractApiError(e)
      items.value = items.value.filter(
        (m) => !(m.type === 'human' && m.content === trimmed),
      )
    } finally {
      loading.value = false
    }
  }

  async function decide(approved: boolean, comment?: string) {
    const pending = pendingApproval.value
    if (!pending || loading.value) return
    error.value = null
    loading.value = true
    try {
      const resp = await agentApi.decide(pending.id, approved, comment)
      _applyResponse(resp)
      await loadThreads()
    } catch (e) {
      error.value = extractApiError(e)
    } finally {
      loading.value = false
    }
  }

  // --- Новый чат / сброс -------------------------------------------------
  function newChat() {
    items.value = []
    threadId.value = null
    pendingApproval.value = null
    error.value = null
    _persistThread(null)
  }

  // Оставлен для совместимости с текущим ChatView
  function reset() {
    newChat()
  }

  return {
    // state
    items, threadId, pendingApproval, threads,
    loading, loadingThreads, error,
    // getters
    canSend, lastAssistantMessage,
    // actions
    send, decide, loadThreads, loadThread, newChat, reset,
  }
})