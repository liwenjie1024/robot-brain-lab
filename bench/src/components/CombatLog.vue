<script setup lang="ts">
import { NCard, NEmpty, NTag } from 'naive-ui'
import type { CombatLogEntry } from '@/sim/useSim'
import { describeCombatEvent } from '@/utils/combatLog'

/** 전투 기록: 누가 쏘아 무엇을 맞혔는지, 막았는지, 무엇이 파괴되었는지 */
defineProps<{ entries: readonly CombatLogEntry[]; names: ReadonlyMap<string, string> }>()

const timeFormat = new Intl.DateTimeFormat('ko-KR', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
</script>

<template>
  <n-card title="전투 기록" size="small">
    <n-empty v-if="entries.length === 0" description="아직 사격이 없습니다" />
    <ol v-else class="log" data-test="combat-log">
      <li v-for="entry in entries" :key="entry.key">
        <span class="time">{{ timeFormat.format(entry.at) }}</span>
        <n-tag :type="describeCombatEvent(entry.event, names).type" size="small">
          {{ describeCombatEvent(entry.event, names).text }}
        </n-tag>
      </li>
    </ol>
  </n-card>
</template>

<style scoped>
.log {
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: 13px;
}
.log li {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
}
.time {
  color: #64748b;
  font-variant-numeric: tabular-nums;
}
</style>
