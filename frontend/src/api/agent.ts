import { ACCESS_KEY, forceLogout, http, refreshTokens } from './client'

export interface ToolCall {
  id?: string
  name: string
  args: Record<string, any>
  type?: string
}

export interface MessageOut {
  type: 'human' | 'ai' | 'tool' | 'system' | string
  content: string
  tool_calls: ToolCall[] | null
}

export interface RunResponse {
  run_id: string | null
  thread_id: string
  status: 'completed' | 'interrupted'
  messages: MessageOut[]
  pending_approval_id: string | null
}

export interface ThreadStatusResponse {
  thread_id: string
  next_nodes: string[]
  messages: MessageOut[]
}

export interface ApprovalOut {
  id: string
  thread_id: string
  status: string
  payload: {
    type?: string
    tool_calls?: Array<{ id: string; name: string; args: Record<string, any> }>
  }
  comment: string | null
  created_at: string
  decided_at: string | null
}

export interface RunOut {
  id: string
  thread_id: string
  status: string
  input: { [key: string]: any }
  created_at: string
  completed_at: string | null
}

export type StreamEvent =
  | { type: 'run_started'; data: { run_id: string; thread_id: string } }
  | { type: 'token'; data: { content: string } }
  | { type: 'node'; data: { node: string; messages: MessageOut[] } }
  | { type: 'interrupt'; data: Record<string, any> }
  | { type: 'interrupted'; data: { thread_id: string; pending_approval_id: string | null } }
  | { type: 'completed'; data: { thread_id: string; messages: MessageOut[] } }
  | { type: 'error'; data: { detail: string; type: string } }

const BASE_URL = import.meta.env.VITE_API_BASE || '/api'

export async function streamAgent(
  message: string,
  threadId: string | null,
  onEvent: (evt: StreamEvent) => void,
  signal?: AbortSignal,
): Promise<void> {
  const doFetch = (token: string | null) =>
    fetch(`${BASE_URL}/agent/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({ message, thread_id: threadId }),
      signal,
    })

  let res = await doFetch(localStorage.getItem(ACCESS_KEY))

  // access-токен истёк — обновляем и повторяем запрос один раз
  if (res.status === 401) {
    const fresh = await refreshTokens()
    if (!fresh) {
      forceLogout()
      throw new Error('Сессия истекла')
    }
    res = await doFetch(fresh)
  }

  if (!res.ok || !res.body) {
    const text = await res.text().catch(() => '')
    throw new Error(`HTTP ${res.status}: ${text || res.statusText}`)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })

    let sep: number
    while ((sep = buffer.indexOf('\n\n')) !== -1) {
      const raw = buffer.slice(0, sep)
      buffer = buffer.slice(sep + 2)

      let event = 'message'
      let data = ''
      for (const line of raw.split('\n')) {
        if (line.startsWith('event: ')) event = line.slice(7)
        else if (line.startsWith('data: ')) data = line.slice(6)
      }
      if (!data) continue
      try {
        onEvent({ type: event, data: JSON.parse(data) } as StreamEvent)
      } catch (e) {
        console.error('SSE parse error', event, data, e)
      }
    }
  }
}

export const agentApi = {
  async run(message: string, threadId?: string): Promise<RunResponse> {
    const { data } = await http.post<RunResponse>('/agent/run', {
      message,
      thread_id: threadId ?? null,
    })
    return data
  },

  async listRuns(): Promise<RunOut[]> {
    const { data } = await http.get<RunOut[]>('/runs')
    return data
  },

  async getThreadStatus(threadId: string): Promise<ThreadStatusResponse> {
    const { data } = await http.get<ThreadStatusResponse>(
      `/agent/status/${threadId}`,
    )
    return data
  },

  async decide(
    approvalId: string,
    approved: boolean,
    comment?: string,
  ): Promise<RunResponse> {
    const { data } = await http.post<RunResponse>(
      `/approvals/${approvalId}/decide`,
      { approved, comment: comment ?? null },
    )
    return data
  },

  async listPendingApprovals(): Promise<ApprovalOut[]> {
    const { data } = await http.get<ApprovalOut[]>('/approvals')
    return data
  },

  async getApproval(id: string): Promise<ApprovalOut> {
    const { data } = await http.get<ApprovalOut>(`/approvals/${id}`)
    return data
  },

  async deleteThread(threadId: string): Promise<void> {
    await http.delete(`/runs/threads/${encodeURIComponent(threadId)}`)
  },
}