<script setup lang="ts">
import { computed, ref } from 'vue'
import { useChatStore } from '@/stores/chat'

const chat = useChatStore()
const comment = ref('')
const working = ref(false)

const pending = computed(() => chat.pendingApproval)
const toolCalls = computed(() => {
  // берём tool_calls из последнего ai-сообщения
  const msgs = chat.items
  for (let i = msgs.length - 1; i >= 0; i--) {
    if (msgs[i].type === 'ai' && msgs[i].tool_calls?.length) {
      return msgs[i].tool_calls!
    }
  }
  return pending.value?.payload?.tool_calls ?? []
})

async function decide(approved: boolean) {
  if (working.value) return
  working.value = true
  try {
    await chat.decide(approved, comment.value.trim() || undefined)
    comment.value = ''
  } finally {
    working.value = false
  }
}
</script>

<template>
  <div v-if="pending" class="approval">
    <div class="approval-head">
      <strong>Требуется подтверждение</strong>
      <span class="muted">Агент хочет вызвать инструмент</span>
    </div>

    <ul class="approval-list">
      <li v-for="(tc, i) in toolCalls" :key="i">
        <span class="tc-name">⚙ {{ tc.name }}</span>
        <code>{{ JSON.stringify(tc.args) }}</code>
      </li>
    </ul>

    <textarea
      v-model="comment"
      rows="2"
      placeholder="Комментарий (необязательно)"
      class="approval-comment"
    ></textarea>

    <div class="approval-actions">
      <button class="reject" :disabled="working" @click="decide(false)">
        Отклонить
      </button>
      <button class="approve" :disabled="working" @click="decide(true)">
        Разрешить
      </button>
    </div>
  </div>
</template>