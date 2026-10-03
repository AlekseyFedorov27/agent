<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ChatItem } from '@/stores/chat'
import { renderMarkdown } from '@/utils/markdown'
import { buildPdfFilename, exportElementToPdf } from '@/utils/pdf'

const props = defineProps<{ item: ChatItem }>()

const root = ref<HTMLElement | null>(null)
const exporting = ref(false)

const htmlContent = computed(() => renderMarkdown(props.item.content))

const roleClass = computed(() => {
  switch (props.item.type) {
    case 'human': return 'is-human'
    case 'ai': return 'is-ai'
    case 'tool': return 'is-tool'
    case 'system': return 'is-system'
    default: return 'is-other'
  }
})

const roleLabel = computed(() => {
  switch (props.item.type) {
    case 'human': return 'Вы'
    case 'ai': return 'Агент'
    case 'tool': return 'Инструмент'
    case 'system': return 'Система'
    default: return props.item.type
  }
})

const hasToolCalls = computed(() => !!props.item.tool_calls?.length)
const hasContent = computed(() => (props.item.content || '').trim().length > 0)
const canExport = computed(
  () => props.item.type === 'ai' && hasContent.value,
)

async function exportPdf() {
  if (!root.value || exporting.value) return
  exporting.value = true
  try {
    await exportElementToPdf(root.value, buildPdfFilename('agent-message'))
  } catch (e) {
    console.error('PDF export failed', e)
    alert('Не удалось сохранить PDF: ' + (e as Error).message)
  } finally {
    exporting.value = false
  }
}
</script>

<template>
  <div class="msg" :class="roleClass">
    <div class="msg-head">
      <span class="role">{{ roleLabel }}</span>

      <button
        v-if="canExport"
        class="ghost-btn pdf-btn"
        :disabled="exporting"
        @click="exportPdf"
        title="Сохранить как PDF"
      >
        {{ exporting ? '…' : 'PDF' }}
      </button>
    </div>

    <div ref="root" class="msg-body pdf-target">
      <div v-if="hasContent" class="md" v-html="htmlContent"></div>
      <div v-else-if="hasToolCalls" class="muted">(запрос инструмента)</div>
      <div v-else class="muted">(пустое сообщение)</div>

      <div v-if="hasToolCalls" class="tool-calls">
        <div v-for="(tc, i) in item.tool_calls" :key="i" class="tool-call">
          <span class="tc-name">⚙ {{ tc.name }}</span>
          <code class="tc-args">{{ JSON.stringify(tc.args) }}</code>
        </div>
      </div>
    </div>
  </div>
</template>