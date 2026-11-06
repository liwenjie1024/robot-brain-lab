<script setup lang="ts">
import { NButton, NCard, NSelect } from 'naive-ui'
import { computed, ref, watch } from 'vue'
import type { ScenarioInfo } from '@shared/sim/generated/scene'
import HelpTip from './HelpTip.vue'

/** 시험 장면 고르기와 처음으로 되돌리기 */
const props = defineProps<{
  scenarios: ScenarioInfo[]
  /** 지금 돌고 있는 장면 (상태 메시지) */
  current: string | null
  disabledReason: string | null
}>()

const emit = defineEmits<{ reset: [scenario: string] }>()

const chosen = ref(props.current ?? props.scenarios[0]?.name ?? '')
watch(
  () => props.current,
  (value) => {
    if (value) {
      chosen.value = value
    }
  },
)

const options = computed(() => props.scenarios.map((scenario) => ({ label: scenario.label, value: scenario.name })))
const description = computed(() => props.scenarios.find((scenario) => scenario.name === chosen.value)?.description)
</script>

<template>
  <n-card size="small" class="scenario">
    <template #header>
      시험 장면
      <help-tip text="처음으로를 누르면 기체를 시작 자리에 세우고 드론·체력·에너지를 처음으로 돌립니다." />
    </template>
    <div class="row">
      <label class="sr-only" for="scenario">장면</label>
      <n-select id="scenario" v-model:value="chosen" :options="options" size="small" data-test="scenario" />
      <n-button type="primary" size="small" data-test="reset" :disabled="!!disabledReason" @click="emit('reset', chosen)">
        {{ chosen === current ? '처음으로' : '이 장면으로 처음부터' }}
      </n-button>
    </div>
    <p class="hint">{{ description }}</p>
    <p v-if="disabledReason" class="reason">{{ disabledReason }}</p>
  </n-card>
</template>

<style scoped>
.row {
  display: flex;
  gap: 6px;
}
.hint {
  margin: 4px 0 0;
  color: #64748b;
  font-size: 12px;
}
.reason {
  margin: 4px 0 0;
  color: #b45309;
  font-size: 12px;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}
</style>
