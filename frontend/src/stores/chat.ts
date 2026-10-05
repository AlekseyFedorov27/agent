import { defineStore } from 'pinia'
import { computed, ref } from 'vue'
import {
  agentApi,
  streamAgent,
  type ApprovalOut,
  type MessageOut,
  type RunResponse,
  type StreamEvent,
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
  return (
    globalThis.crypto?.randomUUID?.() ??
    Math.random().toString(36).slice(2) + Date.now().toString(36)
  )
}

export const useChatStore = defineStore('chat', () => {
  const items = ref<ChatItem[]>([])
  const threadId = ref<string | null>(localStorage.getItem(LAST_THREAD_KEY))
  const pendingApproval = ref<ApprovalOut | null>(null)
  const threads = ref<ThreadSummary[]>([])
  const loading = ref(false)
  const loadingThreads = ref(false)
  const error = ref<string | null>(null)

  // какой thread_id сейчас грузится, чтобы не блокировать сами себя
  let loadingThreadId: string | null = null

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
      pendingApproval.value =
        pending.find((a) => a.thread_id === thread) ?? null
    } catch {
      pendingApproval.value = null
    }
  }

  async function _applyResponse(resp: RunResponse) {
    threadId.value = resp.thread_id
    _persistThread(resp.thread_id)
    _ingestMessages(resp.messages)

    if (resp.status === 'interrupted' && resp.pending_approval_id) {
      // подтягиваем настоящий payload, а не выдумываем пустой
      await _refreshPendingFor(resp.thread_id)
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
    if (loadingThreadId === id) return
    loadingThreadId = id
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
      loadingThreadId = null
    }
  }

  // --- Общий helper для send / sendStream --------------------------------
  function _beginSend(
    text: string,
  ): { trimmed: string; humanUid: string } | null {
    const trimmed = text.trim()
    if (!trimmed || loading.value || pendingApproval.value) return null

    error.value = null
    loading.value = true

    const humanUid = uid()
    items.value.push({
      uid: humanUid,
      type: 'human',
      content: trimmed,
      tool_calls: null,
    })

    return { trimmed, humanUid }
  }

  function _rollbackSend(humanUid: string, extraUids: string[] = []) {
    const drop = new Set([humanUid, ...extraUids])
    items.value = items.value.filter((m) => !drop.has(m.uid))
  }

  // --- Отправка (не-стрим) ----------------------------------------------
  async function send(text: string) {
    const started = _beginSend(text)
    if (!started) return
    const { humanUid } = started

    try {
      const resp = await agentApi.run(
        started.trimmed,
        threadId.value ?? undefined,
      )
      await _applyResponse(resp)
      await loadThreads() // обновляем список в сайдбаре
    } catch (e) {
      error.value = extractApiError(e)
      _rollbackSend(humanUid)
    } finally {
      loading.value = false
    }
  }

  // --- Стрим -------------------------------------------------------------
  async function sendStream(text: string) {
    const started = _beginSend(text)
    if (!started) return
    const { humanUid } = started

    const aiUid = uid()
    // ВАЖНО: держим ссылку именно на Proxy-элемент из items.value,
    // а не на сырой объект — иначе мутации .content не триггерят
    // реактивность, и текст «прилипает» к первому токену.
    let streamingItem: ChatItem | null = null

    try {
      await streamAgent(
        started.trimmed,
        threadId.value ?? null,
        (evt: StreamEvent) => {
          switch (evt.type) {
            case 'run_started': {
              threadId.value = evt.data.thread_id
              _persistThread(evt.data.thread_id)
              break
            }

            case 'token': {
              if (!streamingItem) {
                items.value.push({
                  uid: aiUid,
                  type: 'ai',
                  content: '',
                  tool_calls: null,
                })
                // берём из массива — теперь это Proxy, и мутации
                // .content триггерят ререндер Vue.
                streamingItem = items.value[items.value.length - 1]
              }
              streamingItem.content += evt.data.content
              break
            }

            case 'error': {
              error.value = evt.data.detail
              break
            }

            // interrupt / interrupted / completed обработаем
            // после закрытия стрима — перечитаем состояние с бэка.
          }
        },
      )

      // После закрытия стрима — актуализируем состояние с бэка.
      if (threadId.value) {
        const status = await agentApi.getThreadStatus(threadId.value)
        _ingestMessages(status.messages)
        await _refreshPendingFor(threadId.value)
      }
      await loadThreads()
    } catch (e) {
      error.value = extractApiError(e)
      _rollbackSend(humanUid, [aiUid])
    } finally {
      loading.value = false
    }
  }

  // --- Approvals ---------------------------------------------------------
  async function decide(approved: boolean, comment?: string) {
    const pending = pendingApproval.value
    if (!pending || loading.value) return

    error.value = null
    loading.value = true
    try {
      const resp = await agentApi.decide(pending.id, approved, comment)
      await _applyResponse(resp)
      await loadThreads()
    } catch (e) {
      error.value = extractApiError(e)
    } finally {
      loading.value = false
    }
  }

  // --- Удаление треда ----------------------------------------------------
  async function deleteThread(id: string) {
    if (loading.value) return
    loading.value = true
    error.value = null
    try {
      await agentApi.deleteThread(id)
      threads.value = threads.value.filter((t) => t.thread_id !== id)

      // если у удалённого треда висел approval — сбрасываем
      if (pendingApproval.value?.thread_id === id) {
        pendingApproval.value = null
      }

      // Если удалили активный тред — переключаемся на другой или чистим
      if (threadId.value === id) {
        if (threads.value.length > 0) {
          // снимаем флаг, чтобы loadThread не заблокировал сам себя
          loading.value = false
          await loadThread(threads.value[0].thread_id)
        } else {
          newChat()
        }
      }
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
    items,
    threadId,
    pendingApproval,
    threads,
    loading,
    loadingThreads,
    error,
    // getters
    canSend,
    lastAssistantMessage,
    // actions
    send,
    decide,
    loadThreads,
    loadThread,
    newChat,
    reset,
    deleteThread,
    sendStream,
  }
})