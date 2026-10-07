<script setup lang="ts">
import { computed } from 'vue'
import type { AdminEventOut, AdminRunDetailOut } from '@/api/admin'

const props = defineProps<{
  run: AdminRunDetailOut
}>()

interface Segment {
  type: string
  label: string
  startMs: number
  endMs: number
  offsetPct: number
  widthPct: number
  eventId?: string
}

const totalMs = computed(() => {
  const start = new Date(props.run.created_at).getTime()
  const end = props.run.completed_at
    ? new Date(props.run.completed_at).getTime()
    : Date.now()
  return Math.max(end - start, 1)
})

const segments = computed<Segment[]>(() => {
  const start = new Date(props.run.created_at).getTime()
  const events = [...props.run.events].sort(
    (a, b) =>
      new Date(a.created_at).getTime() - new Date(b.created_at).getTime(),
  )

  // Точки, между которыми считаем длительность
  const points: { type: string; ms: number; eventId?: string }[] = [
    { type: 'start', ms: 0 },
  ]
  for (const ev of events) {
    points.push({
      type: ev.type,
      ms: new Date(ev.created_at).getTime() - start,
      eventId: ev.id,
    })
  }
  // Закрываем последним
  points.push({
    type: 'end',
    ms: props.run.completed_at
      ? new Date(props.run.completed_at).getTime() - start
      : Date.now() - start,
  })

  const segs: Segment[] = []
  for (let i = 0; i < points.length - 1; i++) {
    const p = points[i]
    const next = points[i + 1]
    const dur = next.ms - p.ms
    segs.push({
      type: p.type,
      label: labelFor(p.type),
      startMs: p.ms,
      endMs: next.ms,
      offsetPct: (p.ms / totalMs.value) * 100,
      widthPct: Math.max((dur / totalMs.value) * 100, 0.3),
      eventId: p.eventId,
    })
  }
  return segs
})

function labelFor(type: string): string {
  const map: Record<string, string> = {
    start: 'старт',
    llm_end: 'LLM',
    tool_end: 'инструмент',
    interrupt: 'ожидание HITL',
    resume: 'ответ пользователя',
    end: 'конец',
    error: 'ошибка',
    node_update: 'узел',
  }
  return map[type] ?? type
}

function colorFor(type: string): string {
  const map: Record<string, string> = {
    start: '#6b7280',
    llm_end: '#6366f1',
    tool_end: '#22c55e',
    interrupt: '#eab308',
    resume: '#3b82f6',
    end: '#10b981',
    error: '#ef4444',
    node_update: '#8b5cf6',
  }
  return map[type] ?? '#8b93a7'
}

function fmtMs(ms: number): string {
  if (ms < 1000) return `${Math.round(ms)}ms`
  return `${(ms / 1000).toFixed(2)}s`
}
</script>

<template>
  <div class="timeline">
    <div class="timeline-head">
      <span class="muted">Таймлайн ({{ fmtMs(totalMs) }})</span>
    </div>

    <div class="timeline-bar">
      <div
        v-for="(seg, i) in segments"
        :key="i"
        class="segment"
        :style="{
          left: `${seg.offsetPct}%`,
          width: `${seg.widthPct}%`,
          background: colorFor(seg.type),
        }"
        :title="`${seg.label}: ${fmtMs(seg.endMs - seg.startMs)}`"
      ></div>
    </div>

    <div class="timeline-legend">
      <div v-for="(seg, i) in segments" :key="i" class="legend-item">
        <span class="legend-dot" :style="{ background: colorFor(seg.type) }"></span>
        <span class="legend-label">{{ seg.label }}</span>
        <span class="muted legend-time">{{ fmtMs(seg.endMs - seg.startMs) }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.timeline {
  background: var(--bg-elev);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 14px 18px;
  margin-bottom: 20px;
}
.timeline-head {
  font-size: 13px;
  margin-bottom: 10px;
}
.timeline-bar {
  position: relative;
  height: 28px;
  background: rgba(255, 255, 255, 0.03);
  border-radius: 6px;
  overflow: hidden;
  margin-bottom: 12px;
}
.segment {
  position: absolute;
  top: 0;
  bottom: 0;
  transition: filter 0.15s ease;
  cursor: pointer;
}
.segment:hover {
  filter: brightness(1.2);
}
.timeline-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 14px;
  font-size: 12.5px;
}
.legend-item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
}
.legend-dot {
  width: 10px;
  height: 10px;
  border-radius: 2px;
}
.legend-time {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 11.5px;
}
</style>