<script setup lang="ts">
import { computed, ref } from 'vue'
import type { ChatItem } from '@/stores/chat'
import { renderMarkdown } from '@/utils/markdown'
import { buildPdfFilename, exportElementToPdf } from '@/utils/pdf'

const props = defineProps<{ item: ChatItem }>()

const root = ref<HTMLElement | null>(null)
const exporting = ref(false)
const copied = ref(false)

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

// --- Clipboard ---------------------------------------------------------
async function copyToClipboard(text: string): Promise<boolean> {
  // Современный API (требует secure context: https или localhost)
  if (navigator.clipboard && window.isSecureContext) {
    try {
      await navigator.clipboard.writeText(text)
      return true
    } catch {
      // падаем в фоллбэк ниже
    }
  }

  // Фоллбэк для http / старых браузеров
  try {
    const ta = document.createElement('textarea')
    ta.value = text
    ta.setAttribute('readonly', '')
    ta.style.position = 'fixed'
    ta.style.top = '-1000px'
    ta.style.opacity = '0'
    document.body.appendChild(ta)
    ta.select()
    const ok = document.execCommand('copy')
    document.body.removeChild(ta)
    return ok
  } catch {
    return false
  }
}

async function copyMessage() {
  if (!props.item.content) return
  const ok = await copyToClipboard(props.item.content)
  if (ok) {
    copied.value = true
    setTimeout(() => (copied.value = false), 1500)
  }
}

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

      <div v-if="canExport" class="msg-tools">
        <button
          class="icon-btn"
          :class="{ 'is-ok': copied }"
          :title="copied ? 'Скопировано' : 'Скопировать в буфер'"
          :aria-label="copied ? 'Скопировано' : 'Скопировать в буфер'"
          @click="copyMessage"
        >
          <!-- check -->
          <svg
            v-if="copied"
            width="15" height="15" viewBox="0 0 24 24"
            fill="none" stroke="currentColor"
            stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"
          >
            <polyline points="20 6 9 17 4 12" />
          </svg>
          <!-- copy -->
          <svg
            v-else
            width="15" height="15" viewBox="0 0 24 24"
            fill="none" stroke="currentColor"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
          >
            <rect x="9" y="9" width="13" height="13" rx="2" ry="2" />
            <path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1" />
          </svg>
        </button>

        <button
          class="icon-btn"
          :disabled="exporting"
          title="Сохранить как PDF"
          aria-label="Сохранить как PDF"
          @click="exportPdf"
        >
          <!-- download -->
          <svg
            v-if="!exporting"
            width="15" height="15" viewBox="0 0 24 24"
            fill="none" stroke="currentColor"
            stroke-width="2" stroke-linecap="round" stroke-linejoin="round"
          >
            <path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4" />
            <polyline points="7 10 12 15 17 10" />
            <line x1="12" y1="15" x2="12" y2="3" />
          </svg>
          <!-- spinner -->
          <svg
            v-else
            class="spin"
            width="15" height="15" viewBox="0 0 24 24"
            fill="none" stroke="currentColor"
            stroke-width="2" stroke-linecap="round"
          >
            <path d="M21 12a9 9 0 1 1-6.219-8.56" />
          </svg>
        </button>
      </div>
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