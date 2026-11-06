<script setup lang="ts">
import { NAlert, NButton, NCard, NDropdown, NInput, NSpin, NTag, NTooltip } from 'naive-ui'
import { computed, ref } from 'vue'
import type { BrainStatus, PlanStatus, PlanStepView } from '@shared/brain/generated/status'
import { describeStep, EVASION_LABELS, percent } from '@shared/brain/labels'
import type { BrainPhase } from '@/brain/brainClient'
import type { TagType } from '@/utils/labels'
import HelpTip from './HelpTip.vue'

/**
 * 말로 명령하는 칸: 느린 뇌(System 2)가 명령을 계획(기술 단계)으로 바꾸고 빠른 뇌가 따른다.
 * 계획을 짜는 중·따르는 중·마침·실패를 단계별로 보여 주고, 계획에 걸린 시간을 알린다.
 */
const props = defineProps<{
  phase: BrainPhase
  status: BrainStatus | null
  /** 두뇌가 명령·그만두기를 받지 않은 까닭 */
  error: string | null
  names: ReadonlyMap<string, string>
}>()

const emit = defineEmits<{
  order: [text: string]
  cancelPlan: []
}>()

/** 규약의 명령 길이 (contracts/brain/control.schema.json의 Order.text) */
const MAX_ORDER_LENGTH = 200
const MS_PER_SECOND = 1000
/** 두뇌가 언어 모델 없이 바로 알아듣는 말 */
const QUICK_ORDERS = ['공격', '물러나', '멈춰', '자리 지켜']
const EXAMPLES = ['드론 2부터 잡고 나머지도 정리해. 위험하면 물러나', '방패로 막으면서 전부 격파해', '10초 동안 자리 지키다가 공격해']
const EXAMPLE_OPTIONS = EXAMPLES.map((example) => ({ label: example, key: example }))
const ORDER_HELP = '느린 뇌(System 2)가 말로 한 명령을 계획으로 바꿉니다. 명령하면 두뇌가 조종을 맡습니다. "바로 하기"의 짧은 명령은 바로, 그 밖의 명령은 언어 모델이 계획을 짜는 데 보통 1~3초 걸립니다. 그동안에도 빠른 뇌는 조준 경고를 피하고 막습니다.'
const CANCEL_HELP = '그만두면 기체는 지금 하는 기술을 그대로 합니다.'

const STATE_LABELS: Record<PlanStatus['state'], { text: string; type: TagType }> = {
  thinking: { text: '짜는 중', type: 'info' },
  running: { text: '따르는 중', type: 'success' },
  done: { text: '마침', type: 'default' },
  failed: { text: '실패', type: 'error' },
  cancelled: { text: '그만둠', type: 'default' },
  retreating: { text: '물러나는 중', type: 'warning' },
}
const SOURCE_LABELS: Record<PlanStatus['source'], { text: string; help: string }> = {
  quick: { text: '짧은 명령', help: '정해 둔 짧은 말이라 언어 모델에 묻지 않고 바로 따릅니다.' },
  cache: { text: '기억한 계획', help: '같은 상황에서 같은 명령을 전에 받아, 그때 짠 계획을 다시 씁니다.' },
  llm: { text: '언어 모델', help: '언어 모델이 명령과 지금 장면을 보고 계획을 짰습니다.' },
}
const STEP_LABELS: Record<PlanStepView['state'], string> = {
  done: '✓ 끝남',
  running: '▶ 하는 중',
  waiting: '· 기다림',
}

const text = ref('')
const connected = computed(() => props.phase === 'open')
const plan = computed(() => props.status?.plan ?? null)
const planner = computed(() => props.status?.planner ?? null)
const active = computed(() => plan.value?.state === 'thinking' || plan.value?.state === 'running')
const timingText = computed(() => describeTiming(plan.value))

const nameOf = (id: string) => props.names.get(id) ?? id

function send(order: string) {
  const trimmed = order.trim()
  if (trimmed) {
    emit('order', trimmed)
  }
}

function submit() {
  send(text.value)
  text.value = ''
}

function describeTiming(current: PlanStatus | null): string {
  if (!current) {
    return ''
  }
  if (current.source !== 'llm') {
    return '언어 모델에 묻지 않고 바로 따릅니다'
  }
  const { firstTokenMs, firstStepMs, totalMs } = current.timing
  const parts = [
    firstTokenMs === null ? null : `첫 글자 ${seconds(firstTokenMs)}`,
    firstStepMs === null ? null : `첫 단계 시작 ${seconds(firstStepMs)}`,
    totalMs === null ? (current.state === 'thinking' || current.state === 'running' ? '계획을 받는 중' : null) : `계획 전체 ${seconds(totalMs)}`,
    `언어 모델에 ${current.attempts}번 물음`,
  ]
  return parts.filter((part) => part !== null).join(' · ')
}

function seconds(ms: number): string {
  return `${(ms / MS_PER_SECOND).toFixed(1)}초`
}
</script>

<template>
  <n-card size="small" class="order">
    <template #header>
      말로 명령하기 (느린 뇌)
      <help-tip :text="ORDER_HELP" />
    </template>
    <template v-if="planner && connected" #header-extra>
      <n-tooltip>
        <template #trigger>
          <n-tag :type="planner.available ? 'success' : 'warning'" round size="small" data-test="planner">
            {{ planner.available ? '언어 모델 켜짐' : '짧은 명령만' }}
          </n-tag>
        </template>
        언어 모델 {{ planner.model }}{{ planner.available ? '이 긴 명령을 계획으로 바꿉니다.' : '을 쓸 수 없습니다.' }}
      </n-tooltip>
    </template>

    <p v-if="!connected" class="hint" data-test="order-offline">
      두뇌가 연결되면 말로 명령할 수 있습니다. 두뇌를 띄우는 방법은 두뇌 칸에 있습니다.
    </p>

    <template v-else-if="status">
      <n-alert v-if="planner && !planner.available" type="warning" :show-icon="false" class="notice" data-test="planner-off">
        언어 모델({{ planner.model }})을 쓸 수 없어 "바로 하기"의 짧은 명령만 알아듣습니다. Ollama를 띄우면 15초 안에 다시 붙습니다.
      </n-alert>

      <form class="line" @submit.prevent="submit">
        <n-input v-model:value="text" class="grow" :maxlength="MAX_ORDER_LENGTH" clearable size="small"
                 placeholder="예: 드론 2부터 잡고 나머지도 정리해" aria-label="명령 (200자까지)" data-test="order-input" />
        <n-dropdown :options="EXAMPLE_OPTIONS" trigger="click" @select="(example: string) => (text = example)">
          <n-button size="small" quaternary data-test="order-examples">예 ▾</n-button>
        </n-dropdown>
        <n-button attr-type="submit" type="primary" size="small" :disabled="!text.trim()" data-test="order-send">명령하기</n-button>
      </form>
      <div class="line quick">
        <span class="label">바로 하기</span>
        <n-button v-for="word in QUICK_ORDERS" :key="word" size="tiny" secondary :data-test="`quick-${word}`" @click="send(word)">
          {{ word }}
        </n-button>
      </div>

      <n-alert v-if="error" type="error" :show-icon="false" class="notice" data-test="order-error">{{ error }}</n-alert>

      <p v-if="!plan" class="empty" data-test="plan-empty">아직 명령이 없습니다. 위에 말로 명령하거나 "바로 하기"를 누르세요.</p>
      <section v-else class="plan" aria-label="지금 계획" data-test="plan">
        <div class="plan-head">
          <n-tag :type="STATE_LABELS[plan.state].type" size="small" data-test="plan-state">{{ STATE_LABELS[plan.state].text }}</n-tag>
          <n-tooltip>
            <template #trigger>
              <n-tag size="small" :bordered="false" data-test="plan-source">{{ SOURCE_LABELS[plan.source].text }}</n-tag>
            </template>
            {{ SOURCE_LABELS[plan.source].help }}
          </n-tooltip>
          <span class="order-text">“{{ plan.order }}”</span>
          <n-tooltip v-if="active">
            <template #trigger>
              <n-button size="tiny" class="cancel" data-test="plan-cancel" @click="emit('cancelPlan')">계획 그만두기</n-button>
            </template>
            {{ CANCEL_HELP }}
          </n-tooltip>
        </div>
        <p class="say" data-test="plan-say">
          <n-spin v-if="plan.state === 'thinking'" :size="12" />
          {{ plan.say }}
        </p>
        <ol v-if="plan.steps.length" class="steps" data-test="plan-steps">
          <li v-for="(step, index) in plan.steps" :key="index" :class="step.state">
            <span class="mark">{{ STEP_LABELS[step.state] }}</span>
            <span>{{ index + 1 }}. {{ describeStep(step, nameOf) }} <span class="muted">· 경고에 {{ EVASION_LABELS[step.evasion] }}</span></span>
          </li>
        </ol>
        <p v-if="plan.retreatBelowHp > 0" class="muted" data-test="plan-retreat">
          체력이 {{ percent(plan.retreatBelowHp) }}% 아래로 떨어지면 계획을 멈추고 물러납니다.
        </p>
        <p class="muted" data-test="plan-timing">{{ timingText }}</p>
        <n-alert v-if="plan.state === 'failed'" type="error" :show-icon="false" class="notice" data-test="plan-error">
          <p class="error-text">{{ plan.error }}</p>
          <n-button size="tiny" data-test="plan-retry" @click="send(plan.order)">같은 명령 다시 하기</n-button>
        </n-alert>
      </section>
    </template>

    <p v-else class="hint">두뇌의 상태를 기다리는 중입니다…</p>
  </n-card>
</template>

<style scoped>
.hint {
  margin: 0;
  color: #64748b;
  font-size: 12px;
}
.notice {
  margin: 4px 0;
  font-size: 12px;
}
.line {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}
.grow {
  flex: 1 1 12em;
  width: auto;
}
.quick {
  margin-top: 4px;
}
.label {
  font-size: 12px;
  color: #475569;
}
.empty {
  margin: 6px 0 0;
  color: #94a3b8;
  font-size: 12px;
}
.plan {
  margin-top: 6px;
  padding: 6px 8px;
  border-radius: 6px;
  background: #f8fafc;
  border: 1px solid #e2e8f0;
}
.plan-head {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}
.order-text {
  font-size: 12px;
  font-weight: 600;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
  flex: 1;
}
.say {
  display: flex;
  align-items: center;
  gap: 6px;
  margin: 4px 0;
  font-size: 12px;
}
.steps {
  margin: 0 0 4px;
  padding: 0;
  list-style: none;
  font-size: 12px;
}
.steps li {
  display: flex;
  gap: 6px;
  padding: 1px 0;
}
.steps li.running {
  font-weight: 600;
}
.steps li.done {
  color: #64748b;
}
.mark {
  min-width: 4.8em;
  flex: none;
}
.muted {
  margin: 2px 0;
  color: #64748b;
  font-size: 11px;
}
.error-text {
  margin: 0 0 4px;
}
</style>
