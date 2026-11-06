<script setup lang="ts">
import { NCard, NTabPane, NTabs } from 'naive-ui'
import type { Decision } from '@shared/brain/generated/status'
import type { CombatLogEntry, CommandLogEntry } from '@/sim/useSim'
import CombatLog from './CombatLog.vue'
import CommandLog from './CommandLog.vue'
import DecisionLog from './DecisionLog.vue'

/** 기록 칸: 두뇌의 판단, 전투, 보낸 명령을 탭으로 나눠 칸 안에서만 넘겨 본다 (화면 전체는 넘기지 않게) */
defineProps<{
  decisions: readonly Decision[]
  combat: readonly CombatLogEntry[]
  commands: readonly CommandLogEntry[]
  names: ReadonlyMap<string, string>
}>()
</script>

<template>
  <n-card size="small" class="logs" content-class="logs-content">
    <n-tabs type="line" size="small" default-value="decisions" class="tabs">
      <n-tab-pane name="decisions" :tab="`판단 기록 ${decisions.length}`" display-directive="show">
        <decision-log :decisions="decisions" />
      </n-tab-pane>
      <n-tab-pane name="combat" :tab="`전투 기록 ${combat.length}`" display-directive="show">
        <combat-log :entries="combat" :names="names" />
      </n-tab-pane>
      <n-tab-pane name="commands" :tab="`보낸 명령 ${commands.length}`" display-directive="show">
        <command-log :entries="commands" />
      </n-tab-pane>
    </n-tabs>
  </n-card>
</template>

<style scoped>
.logs {
  height: 100%;
  min-height: 0;
}
.logs :deep(.logs-content) {
  display: flex;
  flex-direction: column;
  min-height: 0;
  padding-top: 4px;
}
.tabs {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.tabs :deep(.n-tabs-pane-wrapper) {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}
</style>
