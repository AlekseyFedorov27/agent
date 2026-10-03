import { http } from './client'

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