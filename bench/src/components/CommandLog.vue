<script setup lang="ts">
import { NEmpty, NTag } from 'naive-ui'
import type { CommandLogEntry } from '@/sim/useSim'

/** 보낸 명령과 몸의 답 (받음·거절과 걸린 시간). 두뇌를 시험할 때 몸이 명령을 받는 시간도 여기서 본다. */
defineProps<{ entries: readonly CommandLogEntry[] }>()

const timeFormat = new Intl.DateTimeFormat('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
</script>

<template>
  <n-empty v-if="entries.length === 0" description="아직 보낸 명령이 없습니다" size="small" />
  <ol v-else class="log" data-test="command-log">
    <li v-for="entry in entries" :key="entry.result.id">
      <span class="time">{{ timeFormat.format(entry.at) }}</span>
      <span class="label">{{ entry.label }}</span>
      <n-tag v-if="entry.result.accepted" type="success" size="small">받음 · {{ Math.round(entry.result.roundTripMs) }}ms</n-tag>
      <n-tag v-else type="error" size="small">거절</n-tag>
      <p v-if="!entry.result.accepted" class="reason">{{ entry.result.reason }}</p>
    </li>
  </ol>
</template>

<style scoped>
.log {
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: 12px;
}
.log li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 8px;
  padding: 4px 0;
  border-bottom: 1px solid #e2e8f0;
}
.time {
  color: #64748b;
  font-variant-numeric: tabular-nums;
}
.label {
  flex: 1;
}
.reason {
  flex-basis: 100%;
  margin: 0;
  color: #b91c1c;
  font-size: 12px;
}
</style>
