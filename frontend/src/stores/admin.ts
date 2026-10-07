import { defineStore } from 'pinia'
import { ref } from 'vue'
import {
  adminApi,
  type AdminRunDetailOut,
  type AdminRunFilters,
  type AdminRunListOut,
  type AdminUserCreate,
  type AdminUserUpdate,
} from '@/api/admin'
import type { UserPublic } from '@/api/auth'
import { extractApiError } from '@/api/client'

export const useAdminStore = defineStore('admin', () => {
  // --- Users --------------------------------------------------------------
  const users = ref<UserPublic[]>([])
  const loading = ref(false)
  const error = ref<string | null>(null)

  async function load() {
    loading.value = true
    error.value = null
    try {
      users.value = await adminApi.listUsers()
    } catch (e) {
      error.value = extractApiError(e)
    } finally {
      loading.value = false
    }
  }

  async function create(payload: AdminUserCreate) {
    error.value = null
    const created = await adminApi.createUser(payload)
    users.value = [created, ...users.value]
    return created
  }

  async function update(id: string, payload: AdminUserUpdate) {
    error.value = null
    const updated = await adminApi.updateUser(id, payload)
    const i = users.value.findIndex((u) => u.id === id)
    if (i !== -1) users.value[i] = updated
    return updated
  }

  async function remove(id: string) {
    error.value = null
    await adminApi.deleteUser(id)
    users.value = users.value.filter((u) => u.id !== id)
  }

  // --- Runs ---------------------------------------------------------------
  const runs = ref<AdminRunListOut | null>(null)
  const runsLoading = ref(false)
  const runsError = ref<string | null>(null)

  async function loadRuns(filters: AdminRunFilters = {}) {
    runsLoading.value = true
    runsError.value = null
    try {
      runs.value = await adminApi.listRuns(filters)
    } catch (e) {
      runsError.value = extractApiError(e)
    } finally {
      runsLoading.value = false
    }
  }

  const runDetail = ref<AdminRunDetailOut | null>(null)
  const runDetailLoading = ref(false)
  const runDetailError = ref<string | null>(null)

  async function loadRun(id: string) {
    runDetailLoading.value = true
    runDetailError.value = null
    runDetail.value = null
    try {
      runDetail.value = await adminApi.getRun(id)
    } catch (e) {
      runDetailError.value = extractApiError(e)
    } finally {
      runDetailLoading.value = false
    }
  }

  return {
    users, loading, error,
    load, create, update, remove,
    runs, runsLoading, runsError,
    loadRuns,
    runDetail, runDetailLoading, runDetailError,
    loadRun,
  }
})