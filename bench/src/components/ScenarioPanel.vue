<script setup lang="ts">
import { NButton, NCard, NSelect } from 'naive-ui'
import { computed, ref, watch } from 'vue'
import type { ScenarioInfo } from '@shared/sim/generated/scene'

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
  <n-card title="시험 장면" size="small">
    <label class="label" for="scenario">장면</label>
    <n-select id="scenario" v-model:value="chosen" :options="options" data-test="scenario" />
    <p class="hint">{{ description }}</p>
    <n-button type="primary" block data-test="reset" :disabled="!!disabledReason" @click="emit('reset', chosen)">
      {{ chosen === current ? '처음으로' : '이 장면으로 처음부터' }}
    </n-button>
    <p class="hint">기체를 시작 자리에 세우고 드론·체력·에너지를 처음으로 돌립니다.</p>
  </n-card>
</template>

<style scoped>
.label {
  display: block;
  font-size: 13px;
  margin-bottom: 4px;
}
.hint {
  margin: 6px 0 10px;
  color: #64748b;
  font-size: 12px;
}
</style>
