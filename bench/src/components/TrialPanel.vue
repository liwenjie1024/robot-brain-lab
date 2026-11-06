<script setup lang="ts">
import { NAlert, NButton, NCard, NCheckbox, NCheckboxGroup, NEmpty, NInput, NInputNumber, NProgress, NSelect, NTag, NTooltip } from 'naive-ui'
import { computed, ref, watch } from 'vue'
import type { Evasion, StartTrials, TrialSetup } from '@shared/brain/generated/control'
import type { BrainStatus, RunResult, TrialSeries } from '@shared/brain/generated/status'
import { EVASION_LABELS, SKILL_LABELS } from '@shared/brain/labels'
import { SCORE_POINTS } from '@shared/brain/trialScore'
import type { ScenarioInfo } from '@shared/sim/generated/scene'
import type { BrainPhase } from '@/brain/brainClient'
import type { TagType } from '@/utils/labels'
import { bestOf, longestMinutes, MAX_TRIAL_SETUPS, toTrialSetups, TRIAL_COLUMNS } from '@/utils/trials'
import HelpTip from './HelpTip.vue'

/**
 * 시험과 점수: 같은 시험을 여러 번 돌려 두뇌의 기술·반응·말로 한 명령을 견준다.
 * 같은 때 맡으면 판마다 결과가 똑같으므로, 판마다 두뇌가 맡는 때를 고르게 늦춰 드론이 조준하는 때와의 어긋남을 고루 보고,
 * 가운데 값과 범위를 보이며 칸마다 가장 좋은 것을 표시한다.
 */
const props = defineProps<{
  phase: BrainPhase
  status: BrainStatus | null
  scenarios: readonly ScenarioInfo[]
  /** 두뇌가 시험 시작·멈추기를 받지 않은 까닭 */
  error: string | null
}>()

const emit = defineEmits<{
  start: [spec: Omit<StartTrials, 'type' | 'id'>]
  stop: []
}>()

/** 규약의 범위 (contracts/brain/control.schema.json의 StartTrials) */
const RUNS = { min: 1, max: 10, initial: 3 }
const TIME_LIMIT_S = { min: 10, max: 120, step: 10, initial: 60 }
/** 드론 하나가 조준을 시작해 쏘고 다시 조준하기까지 약 4초 (경고 1.2초 + 식힘 3초): 그만큼 늦추면 어긋남을 고루 본다 */
const START_SPREAD_S = { min: 0, max: 10, step: 0.5, initial: 4 }
const MAX_ORDER_LENGTH = 200
const EVASION_ORDER: Evasion[] = ['none', 'dodge', 'guard', 'both']

const STATE_LABELS: Record<TrialSeries['state'], { text: string; type: TagType }> = {
  running: { text: '시험 중', type: 'info' },
  done: { text: '다 돌림', type: 'success' },
  stopped: { text: '멈춤', type: 'warning' },
  failed: { text: '실패', type: 'error' },
}
const TRIAL_HELP =
  '같은 시험을 여러 번 돌려 두뇌의 기술·조준 경고 반응·말로 한 명령을 견줍니다. 두뇌가 맡는 때와 드론이 조준하는 때가 엇갈리는 정도에 따라 결과가 달라, 여러 판의 가운데 값을 봅니다.'
const SPREAD_HELP =
  '두뇌가 같은 때 맡으면 판마다 결과가 똑같습니다. 그래서 판마다 두뇌가 맡는 때를 0초부터 이만큼까지 고르게 늦춰, 드론이 조준하는 때와 엇갈리는 여러 경우를 봅니다 (드론 하나가 다시 조준하기까지 약 4초). 0이면 모든 판이 같습니다. 기다리는 동안 맞은 것은 빼고 잽니다.'

const OUTCOME_LABELS: Record<RunResult['outcome'], { text: string; type: TagType }> = {
  cleared: { text: '다 격파', type: 'success' },
  destroyed: { text: '기체 파괴', type: 'error' },
  timeout: { text: '시간 끝', type: 'warning' },
}

const scoredScenarios = computed(() => props.scenarios.filter((scenario) => scenario.drones > 0))
const scenario = ref(defaultScenario())
const evasions = ref<Evasion[]>([...EVASION_ORDER])
const orders = ref<string[]>([])
const orderText = ref('')
const runs = ref(RUNS.initial)
const timeLimitS = ref(TIME_LIMIT_S.initial)
const startSpreadS = ref(START_SPREAD_S.initial)
const confirming = ref(false)

watch(scoredScenarios, () => {
  if (!scoredScenarios.value.some((item) => item.name === scenario.value)) {
    scenario.value = defaultScenario()
  }
})

const connected = computed(() => props.phase === 'open')
const series = computed(() => props.status?.trials ?? null)
const running = computed(() => series.value?.state === 'running')
const scenarioOptions = computed(() => scoredScenarios.value.map((item) => ({ label: describeScenario(item), value: item.name })))
const evasionOptions = EVASION_ORDER.map((value) => ({ value, label: `${SKILL_LABELS.engage} · ${EVASION_LABELS[value]}` }))
const setups = computed<TrialSetup[]>(() => [
  ...EVASION_ORDER.filter((value) => evasions.value.includes(value)).map((evasion) => ({ kind: 'skill' as const, skill: 'engage' as const, evasion })),
  ...orders.value.map((text) => ({ kind: 'order' as const, text })),
])
const setupProblem = computed(() => {
  if (setups.value.length === 0) {
    return '비교할 것을 하나 넘게 고르세요'
  }
  return setups.value.length > MAX_TRIAL_SETUPS ? `비교할 것은 ${MAX_TRIAL_SETUPS}가지까지입니다 (지금 ${setups.value.length}가지)` : null
})
const totalRuns = computed(() => setups.value.length * (runs.value ?? RUNS.initial))
const minutes = computed(() =>
  longestMinutes(setups.value.length, runs.value ?? RUNS.initial, (timeLimitS.value ?? TIME_LIMIT_S.initial) + (startSpreadS.value ?? 0)),
)

const finishedRuns = computed(() => series.value?.setups.reduce((sum, entry) => sum + entry.results.length, 0) ?? 0)
const plannedRuns = computed(() => (series.value ? series.value.setups.length * series.value.runs : 0))
const progressText = computed(() => {
  const current = series.value?.current
  if (!series.value || !current) {
    return ''
  }
  const label = series.value.setups[current.setup]?.label ?? ''
  const what = {
    resetting: '장면을 처음으로 되돌리는 중',
    waiting: `두뇌가 맡기를 기다리는 중 (${current.startDelayS}초 늦춤)`,
    running: `${current.elapsedS.toFixed(1)}초 지남`,
  }[current.phase]
  return `${plannedRuns.value}판 가운데 ${finishedRuns.value + 1}판째 · ${label} (${current.run}판째) · ${what}`
})
const rows = computed(() => series.value?.setups.filter((entry) => entry.summary) ?? [])
const best = computed(
  () => new Map(TRIAL_COLUMNS.map((column) => [column.key, bestOf(rows.value.map((entry) => column.value(entry.summary!)), column.better)])),
)

function defaultScenario(): string {
  const armed = scoredScenarios.value.find((item) => item.armedDrones > 0)
  return (armed ?? scoredScenarios.value[0])?.name ?? ''
}

function describeScenario(item: ScenarioInfo): string {
  return item.armedDrones > 0 ? `${item.label} (드론 ${item.drones}대, 모두 반격)` : `${item.label} (드론 ${item.drones}대, 반격 없음)`
}

function addOrder() {
  const text = orderText.value.trim()
  if (text && !orders.value.includes(text)) {
    orders.value = [...orders.value, text]
  }
  orderText.value = ''
}

function removeOrder(text: string) {
  orders.value = orders.value.filter((item) => item !== text)
}

function confirmStart() {
  confirming.value = false
  const checked = toTrialSetups(setups.value)
  if (checked) {
    emit('start', {
      scenario: scenario.value,
      setups: checked,
      runs: runs.value ?? RUNS.initial,
      timeLimitS: timeLimitS.value ?? TIME_LIMIT_S.initial,
      startSpreadS: startSpreadS.value ?? 0,
    })
  }
}

function retry(failed: TrialSeries) {
  const checked = toTrialSetups(failed.setups.map((entry) => entry.setup))
  if (checked) {
    emit('start', { scenario: failed.scenario, setups: checked, runs: failed.runs, timeLimitS: failed.timeLimitS, startSpreadS: failed.startSpreadS })
  }
}

function runText(result: RunResult): string {
  const time = result.clearTimeS === null ? `${result.kills}/${result.drones} 격파` : `${result.clearTimeS}초`
  const delay = result.startDelayS > 0 ? ` (${result.startDelayS}초 늦춤)` : ''
  return `${result.run}판${delay}: ${time} · 피해 ${result.damageTaken} · ${result.score}점`
}
</script>

<template>
  <n-card size="small" class="trial" content-class="trial-content">
    <template #header>
      시험과 점수
      <help-tip :text="TRIAL_HELP" />
    </template>
    <template v-if="series" #header-extra>
      <n-tag :type="STATE_LABELS[series.state].type" round size="small" data-test="trial-state">{{ STATE_LABELS[series.state].text }}</n-tag>
    </template>
    <p v-if="!connected" class="hint" data-test="trial-offline">두뇌가 연결되면 시험할 수 있습니다. 두뇌를 띄우는 방법은 두뇌 칸에 있습니다.</p>

    <div v-else class="trial-grid">
      <div class="trial-left">
        <section v-if="!running" class="form" aria-label="시험 고르기" data-test="trial-form">
          <div class="field">
            <label class="label" for="trial-scenario">장면</label>
            <n-select id="trial-scenario" v-model:value="scenario" :options="scenarioOptions" size="small" data-test="trial-scenario" />
          </div>
          <div class="field">
            <span class="label">견줄 것 (두뇌가 교전하며 조준 경고에 이렇게 반응)</span>
            <n-checkbox-group v-model:value="evasions">
              <n-checkbox v-for="option in evasionOptions" :key="option.value" :value="option.value" :label="option.label"
                          :data-test="`trial-evasion-${option.value}`" />
            </n-checkbox-group>
          </div>
          <div class="field">
            <label class="label" for="trial-order">말로 한 명령도 견주기 (판마다 언어 모델이 새로 계획을 짭니다)</label>
            <form class="inline" @submit.prevent="addOrder">
              <n-input id="trial-order" v-model:value="orderText" class="grow" :maxlength="MAX_ORDER_LENGTH" size="small"
                       placeholder="예: 드론 2부터 잡고 나머지도 정리해" data-test="trial-order-input" />
              <n-button attr-type="submit" size="small" :disabled="!orderText.trim()" data-test="trial-order-add">넣기</n-button>
            </form>
            <div class="orders">
              <n-tag v-for="text in orders" :key="text" closable size="small" @close="removeOrder(text)">“{{ text }}”</n-tag>
            </div>
          </div>
          <div class="numbers">
            <label class="label" for="trial-runs">판 수 (견줄 것마다)</label>
            <n-input-number id="trial-runs" v-model:value="runs" :min="RUNS.min" :max="RUNS.max" size="small" data-test="trial-runs" />
            <label class="label" for="trial-limit">한 판 제한 시간 (초)</label>
            <n-input-number id="trial-limit" v-model:value="timeLimitS" :min="TIME_LIMIT_S.min" :max="TIME_LIMIT_S.max"
                            :step="TIME_LIMIT_S.step" size="small" data-test="trial-limit" />
            <label class="label" for="trial-spread">맡는 때 늦추기 (초) <help-tip :text="SPREAD_HELP" /></label>
            <n-input-number id="trial-spread" v-model:value="startSpreadS" :min="START_SPREAD_S.min" :max="START_SPREAD_S.max"
                            :step="START_SPREAD_S.step" size="small" data-test="trial-spread" />
          </div>
          <p class="hint" data-test="trial-estimate">모두 {{ totalRuns }}판, 길어야 약 {{ minutes }}분 걸립니다.</p>
          <n-alert v-if="setupProblem" type="warning" :show-icon="false" class="notice" data-test="trial-problem">{{ setupProblem }}</n-alert>

          <n-alert v-if="confirming" type="warning" title="시험을 시작할까요?" class="notice" data-test="trial-confirm">
            <p class="confirm-text">
              장면을 {{ totalRuns }}번 처음으로 되돌리고, 판마다 두뇌가 조종합니다. 그동안 직접 조종·두뇌 칸·말로 명령하기는 쓸 수 없고
              "시험 멈추기"만 됩니다. 길어야 약 {{ minutes }}분 걸립니다. 지금 장면의 진행은 사라집니다.
            </p>
            <div class="inline">
              <n-button type="primary" size="small" data-test="trial-confirm-start" @click="confirmStart">시작</n-button>
              <n-button size="small" data-test="trial-confirm-cancel" @click="confirming = false">그만두기</n-button>
            </div>
          </n-alert>
          <n-button v-else type="primary" size="small" :disabled="!!setupProblem || !scenario" data-test="trial-start" @click="confirming = true">
            시험 시작
          </n-button>
        </section>

        <section v-else class="progress" aria-label="시험 진행" data-test="trial-progress">
          <n-progress type="line" :percentage="Math.round((finishedRuns / Math.max(plannedRuns, 1)) * 100)" :show-indicator="false" />
          <p class="progress-text">{{ progressText }}</p>
          <n-button size="small" data-test="trial-stop" @click="emit('stop')">시험 멈추기</n-button>
          <span class="hint">멈춰도 끝난 판의 결과는 남습니다.</span>
        </section>

        <n-alert v-if="error" type="error" :show-icon="false" class="notice" data-test="trial-error">{{ error }}</n-alert>
        <n-alert v-if="series?.state === 'failed'" type="error" :show-icon="false" class="notice" data-test="trial-failed">
          <p class="confirm-text">시험을 더 돌릴 수 없었습니다: {{ series.error }}</p>
          <n-button size="small" data-test="trial-retry" @click="retry(series)">같은 시험 다시 시작</n-button>
        </n-alert>
      </div>

      <div class="trial-right">
        <n-empty v-if="!series" description="아직 시험 결과가 없습니다" size="small" data-test="trial-empty" />
        <n-empty v-else-if="rows.length === 0" description="아직 끝난 판이 없습니다" size="small" />
        <section v-else aria-label="시험 결과" data-test="trial-results">
          <p class="legend"><span class="best-mark" aria-hidden="true">★</span> 칸마다 가장 좋은 값 (초록 바탕). 칸 이름에 마우스를 올리면 설명이 나옵니다.</p>
          <div class="table-wrap">
            <table class="results">
              <thead>
                <tr>
                  <th scope="col">견준 것</th>
                  <th v-for="column in TRIAL_COLUMNS" :key="column.key" scope="col">
                    <n-tooltip>
                      <template #trigger><span class="column-title">{{ column.title }}</span></template>
                      {{ column.help }} ({{ column.better === 'high' ? '높을수록' : '낮을수록' }} 좋음)
                    </n-tooltip>
                  </th>
                </tr>
              </thead>
              <tbody>
                <tr v-for="(entry, index) in rows" :key="entry.label">
                  <th scope="row">{{ entry.label }}</th>
                  <td v-for="column in TRIAL_COLUMNS" :key="column.key" :class="{ best: best.get(column.key)?.has(index) }">
                    {{ column.format(entry.summary!) }}
                    <span v-if="best.get(column.key)?.has(index)" class="best-mark">★<span class="sr-only"> 가장 좋음</span></span>
                  </td>
                </tr>
              </tbody>
            </table>
          </div>
          <ul class="runs" data-test="trial-runs-list">
            <li v-for="entry in rows" :key="entry.label">
              <span class="run-label">{{ entry.label }}</span>
              <n-tag v-for="result in entry.results" :key="result.run" :type="OUTCOME_LABELS[result.outcome].type" size="small" :bordered="false">
                {{ OUTCOME_LABELS[result.outcome].text }} · {{ runText(result) }}
              </n-tag>
            </li>
          </ul>
          <p class="hint">
            점수(100점) = 격파 {{ SCORE_POINTS.kills }} × 격파한 드론 비율 + 빠르기 {{ SCORE_POINTS.speed }} × 남은 제한 시간 비율(다 격파했을 때만)
            + 버티기 {{ SCORE_POINTS.survival }} × 남은 체력 비율. 같은 제한 시간끼리만 견줄 수 있습니다.
          </p>
          <p v-if="series.savedTo" class="hint" data-test="trial-saved">결과 파일: <code>{{ series.savedTo }}</code></p>
        </section>
      </div>
    </div>
  </n-card>
</template>

<style scoped>
.trial {
  height: 100%;
  min-height: 0;
}
.trial :deep(.trial-content) {
  min-height: 0;
  display: flex;
  flex-direction: column;
}
.trial-grid {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: minmax(320px, 380px) minmax(0, 1fr);
  gap: 16px;
}
.trial-left,
.trial-right {
  min-height: 0;
  overflow-y: auto;
}
@media (max-width: 1099px) {
  .trial-grid {
    grid-template-columns: 1fr;
  }
}
.hint {
  margin: 4px 0 8px;
  color: #64748b;
  font-size: 12px;
}
.notice {
  margin: 8px 0;
}
.form {
  display: grid;
  gap: 8px;
  margin-bottom: 16px;
}
.label {
  display: block;
  font-size: 13px;
  margin-bottom: 4px;
}
.inline {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.grow {
  flex: 1 1 16em;
  width: auto;
}
.orders {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 6px;
}
.numbers {
  display: grid;
  grid-template-columns: 1fr 130px;
  align-items: center;
  gap: 6px 10px;
}
.numbers .label {
  margin: 0;
}
.confirm-text {
  margin: 0 0 8px;
  font-size: 13px;
}
.progress-text {
  margin: 6px 0;
  font-size: 13px;
  font-variant-numeric: tabular-nums;
}
.table-wrap {
  overflow-x: auto;
}
.results {
  width: 100%;
  border-collapse: collapse;
  font-size: 12px;
  font-variant-numeric: tabular-nums;
}
.results th,
.results td {
  padding: 6px 8px;
  border-bottom: 1px solid #e2e8f0;
  text-align: left;
  vertical-align: top;
}
.results thead th {
  color: #475569;
  font-weight: 600;
  white-space: nowrap;
}
.column-title {
  text-decoration: underline dotted;
  cursor: help;
}
.results td.best {
  background: #ecfdf5;
  font-weight: 600;
}
.best-mark {
  color: #047857;
}
.legend {
  margin: 0 0 4px;
  color: #475569;
  font-size: 12px;
}
.sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  overflow: hidden;
  clip: rect(0 0 0 0);
}
.runs {
  margin: 10px 0 0;
  padding: 0;
  list-style: none;
  display: grid;
  gap: 6px;
}
.runs li {
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 6px;
}
.run-label {
  min-width: 9em;
  font-size: 12px;
  font-weight: 600;
}
</style>
