import { http } from './client'
import type { UserPublic } from './auth'

export interface AdminUserCreate {
  email: string
  password: string
  name: string
  position?: string | null
  system_prompt?: string | null
  is_active: boolean
  is_superuser: boolean
}

export interface AdminUserUpdate {
  name?: string
  position?: string | null
  system_prompt?: string | null
  is_active?: boolean
  is_superuser?: boolean
  password?: string
}

export interface AdminRunOut {
  id: string
  user_id: string
  user_email: string
  user_name: string
  thread_id: string
  status: string
  input: Record<string, unknown>
  created_at: string
  completed_at: string | null
}

export interface AdminEventOut {
  id: string
  run_id: string
  type: string
  payload: Record<string, unknown>
  created_at: string
}

export interface AdminRunListOut {
  items: AdminRunOut[]
  total: number
}

export interface AdminRunDetailOut extends AdminRunOut {
  events: AdminEventOut[]
}

export interface AdminRunFilters {
  user_id?: string
  status?: string
  limit?: number
  offset?: number
}

export const adminApi = {
  async listUsers(): Promise<UserPublic[]> {
    const { data } = await http.get<UserPublic[]>('/admin/users')
    return data
  },
  async createUser(payload: AdminUserCreate): Promise<UserPublic> {
    const { data } = await http.post<UserPublic>('/admin/users', payload)
    return data
  },
  async updateUser(id: string, payload: AdminUserUpdate): Promise<UserPublic> {
    const { data } = await http.patch<UserPublic>(`/admin/users/${id}`, payload)
    return data
  },
  async deleteUser(id: string): Promise<void> {
    await http.delete(`/admin/users/${id}`)
  },
  async listRuns(filters: AdminRunFilters = {}): Promise<AdminRunListOut> {
    const { data } = await http.get<AdminRunListOut>('/admin/runs', {
      params: filters,
    })
    return data
  },
  async getRun(id: string): Promise<AdminRunDetailOut> {
    const { data } = await http.get<AdminRunDetailOut>(`/admin/runs/${id}`)
    return data
  },

  async getThreadMessages(threadId: string): Promise<Array<{
    type: string
    content: string
    tool_calls: Array<Record<string, unknown>> | null
  }>> {
    const { data } = await http.get(
      `/admin/runs/threads/${encodeURIComponent(threadId)}/messages`,
    )
    return data
  },
  async deleteThread(threadId: string): Promise<void> {
    await http.delete(`/admin/runs/threads/${encodeURIComponent(threadId)}`)
  },
}