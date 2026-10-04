import { http } from './client'

export interface TokenPair {
  access_token: string
  refresh_token: string
  token_type: string
}

export interface UserPublic {
  id: string
  email: string
  name: string
  position: string | null
  system_prompt: string | null
  is_active: boolean
  is_superuser: boolean
  created_at: string
}

export const authApi = {
  async register(payload: {
    email: string
    password: string
    name: string
    position?: string | null
  }): Promise<UserPublic> {
    const { data } = await http.post<UserPublic>('/auth/register', payload)
    return data
  },
  async login(email: string, password: string): Promise<TokenPair> {
    const { data } = await http.post<TokenPair>('/auth/login', { email, password })
    return data
  },
  async me(): Promise<UserPublic> {
    const { data } = await http.get<UserPublic>('/auth/me')
    return data
  },
}