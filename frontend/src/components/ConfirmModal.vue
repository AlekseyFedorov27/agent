<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref } from 'vue'

const props = withDefaults(defineProps<{
  open: boolean
  title?: string
  message?: string
  confirmText?: string
  cancelText?: string
  danger?: boolean
}>(), {
  title: 'Подтверждение',
  message: 'Вы уверены?',
  confirmText: 'ОК',
  cancelText: 'Отмена',
  danger: false,
})

const emit = defineEmits<{
  (e: 'confirm'): void
  (e: 'cancel'): void
}>()

const root = ref<HTMLElement | null>(null)
const working = ref(false)

async function onConfirm() {
  if (working.value) return
  working.value = true
  try {
    emit('confirm')
  } finally {
    // небольшая защита от двойного клика
    setTimeout(() => (working.value = false), 300)
  }
}

function onCancel() {
  if (working.value) return
  emit('cancel')
}

function onKeydown(e: KeyboardEvent) {
  if (!props.open) return
  if (e.key === 'Escape') onCancel()
  if (e.key === 'Enter') onConfirm()
}

onMounted(() => window.addEventListener('keydown', onKeydown))
onBeforeUnmount(() => window.removeEventListener('keydown', onKeydown))
</script>

<template>
  <Teleport to="body">
    <Transition name="modal-fade">
      <div
        v-if="open"
        class="modal-backdrop"
        @click.self="onCancel"
      >
        <div
          ref="root"
          class="modal-card"
          role="dialog"
          aria-modal="true"
        >
          <h3 class="modal-title">{{ title }}</h3>
          <p class="modal-message">{{ message }}</p>

          <div class="modal-actions">
            <button class="ghost-btn" :disabled="working" @click="onCancel">
              {{ cancelText }}
            </button>
            <button
              :class="danger ? 'btn-danger' : ''"
              :disabled="working"
              @click="onConfirm"
            >
              {{ confirmText }}
            </button>
          </div>
        </div>
      </div>
    </Transition>
  </Teleport>
</template>