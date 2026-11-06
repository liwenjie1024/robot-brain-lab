<script setup lang="ts">
import { NEmpty, NTag } from 'naive-ui'
import type { Decision, DecisionKind } from '@shared/brain/generated/status'
import type { TagType } from '@/utils/labels'

/** 두뇌의 판단 기록: 무엇을 보고 무엇을 정했는지 (새것이 위) */
defineProps<{ decisions: readonly Decision[] }>()

const KIND_LABELS: Record<DecisionKind, { text: string; type: TagType }> = {
  skill: { text: '기술', type: 'info' },
  target: { text: '표적', type: 'default' },
  fire: { text: '사격', type: 'warning' },
  reflex: { text: '반사', type: 'error' },
  result: { text: '결과', type: 'success' },
  command: { text: '거절됨', type: 'error' },
  plan: { text: '계획', type: 'info' },
  trial: { text: '시험', type: 'default' },
}
</script>

<template>
  <n-empty v-if="decisions.length === 0" description="아직 판단 기록이 없습니다" size="small" />
  <ol v-else class="decisions" data-test="decisions">
    <li v-for="decision in decisions" :key="decision.seq">
      <span class="time">{{ decision.simTime === null ? '' : `${decision.simTime.toFixed(1)}초` }}</span>
      <n-tag size="small" :type="KIND_LABELS[decision.kind].type">{{ KIND_LABELS[decision.kind].text }}</n-tag>
      <span>{{ decision.text }}</span>
    </li>
  </ol>
</template>

<style scoped>
.decisions {
  margin: 0;
  padding: 0;
  list-style: none;
  font-size: 12px;
}
.decisions li {
  display: flex;
  align-items: baseline;
  gap: 6px;
  padding: 3px 0;
  border-bottom: 1px solid #e2e8f0;
}
.time {
  min-width: 3.5em;
  color: #64748b;
  font-variant-numeric: tabular-nums;
}
</style>
