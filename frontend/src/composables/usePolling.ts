import { onBeforeUnmount, onMounted, ref } from 'vue'

interface UsePollingOptions {
  /** Сразу сделать первый тик, не ждать intervalMs */
  immediate?: boolean
  /** Пропускать тики, когда вкладка скрыта */
  pauseWhenHidden?: boolean
  /** Префикс для логов */
  name?: string
}

export function usePolling(
  fn: () => void | Promise<void>,
  intervalMs = 2000,
  options: UsePollingOptions = {},
) {
  const {
    immediate = true,
    pauseWhenHidden = true,
    name = 'polling',
  } = options

  const isPolling = ref(false)
  let intervalId: number | null = null
  let running = false

  async function tick() {
    if (running) {
      console.debug(`[${name}] skip: previous tick still running`)
      return
    }
    if (pauseWhenHidden && document.hidden) {
      console.debug(`[${name}] skip: document.hidden = true`)
      return
    }
    running = true
    try {
      await fn()
    } catch (e) {
      console.error(`[${name}] tick failed:`, e)
    } finally {
      running = false
    }
  }

  function start() {
    if (intervalId !== null) return
    isPolling.value = true
    console.debug(`[${name}] start, interval=${intervalMs}ms`)
    if (immediate) void tick()
    intervalId = window.setInterval(tick, intervalMs)
  }

  function stop() {
    if (intervalId !== null) {
      clearInterval(intervalId)
      intervalId = null
    }
    isPolling.value = false
    console.debug(`[${name}] stop`)
  }

  function onVisibility() {
    if (!isPolling.value) return
    if (!document.hidden) {
      console.debug(`[${name}] tab visible → force tick`)
      void tick()
    }
  }

  onMounted(() => {
    start()
    document.addEventListener('visibilitychange', onVisibility)
  })

  onBeforeUnmount(() => {
    stop()
    document.removeEventListener('visibilitychange', onVisibility)
  })

  return { isPolling, start, stop, tick }
}