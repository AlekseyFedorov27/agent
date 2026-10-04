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
}