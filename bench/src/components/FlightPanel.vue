<script setup lang="ts">
import { NAlert, NButton, NCard, NSlider, NSpace } from 'naive-ui'
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import {
  DEFAULT_SPEEDS,
  FLIGHT_LABELS,
  type FlightAction,
  type FlightVelocity,
  keyboardAction,
  NEWTONS_PER_KILONEWTON,
  PUSH_DURATION_MS,
  PUSH_LABELS,
  type PushFrom,
  pushForce,
  velocityFor,
} from '@/control/drive'
import type { Limits } from '@/sim/generated/scene'

/** 사람이 기체를 직접 날려 보는 칸 (두뇌 없이 몸과 비행 제어를 시험하거나 두뇌를 거들 때) */
const props = defineProps<{
  limits: Limits
  /** 기수 방향 rad (밀기 방향을 기체 기준으로 정한다) */
  heading: number
  /** 명령을 보낼 수 없으면 그 까닭 */
  disabledReason: string | null
  destroyed: boolean
}>()

const emit = defineEmits<{
  fly: [label: string, velocity: FlightVelocity]
  push: [label: string, force: [number, number, number], durationMs: number]
  fire: []
}>()

const DEFAULT_PUSH_KN = 1000
const PUSH_STEP_KN = 100
const SPEED_STEP = 1
const TURN_STEP = 0.05
/** 옆으로 나는 빠르기 = 앞뒤 빠르기 × 이 값 (막대를 하나 줄여 칸을 단순하게) */
const SIDE_SPEED_RATIO = 0.5

const speeds = reactive({ ...DEFAULT_SPEEDS })
const pushKilonewtons = ref(DEFAULT_PUSH_KN)

const pad: FlightAction[] = [
  'turnLeft', 'forward', 'turnRight',
  'strafeLeft', 'stop', 'strafeRight',
  'climb', 'backward', 'descend',
]
const pushes: PushFrom[] = ['front', 'back', 'left', 'right']

function fly(action: FlightAction) {
  if (props.disabledReason) {
    return
  }
  const withSide = { ...speeds, side: speeds.forward * SIDE_SPEED_RATIO }
  emit('fly', FLIGHT_LABELS[action], velocityFor(action, withSide, props.limits))
}

function push(from: PushFrom) {
  const newtons = pushKilonewtons.value * NEWTONS_PER_KILONEWTON
  emit('push', `${PUSH_LABELS[from]} ${pushKilonewtons.value}kN`, pushForce(from, props.heading, newtons), PUSH_DURATION_MS)
}

function onKey(event: KeyboardEvent) {
  const action = keyboardAction(event)
  if (!action || props.disabledReason) {
    return
  }
  event.preventDefault()
  if (action === 'fire') {
    emit('fire')
  } else {
    fly(action)
  }
}

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <n-card title="직접 날려 보기" size="small">
    <n-alert v-if="disabledReason" type="warning" :show-icon="false" class="notice">{{ disabledReason }}</n-alert>
    <n-alert v-else-if="destroyed" type="error" :show-icon="false" class="notice" data-test="destroyed-notice">
      기체가 파괴되었습니다. 위의 "처음으로"를 눌러 다시 시작하세요.
    </n-alert>

    <div class="pad" role="group" aria-label="비행 방향">
      <n-button v-for="action in pad" :key="action" :data-test="`fly-${action}`"
                :type="action === 'stop' ? 'error' : 'default'" :disabled="!!disabledReason" @click="fly(action)">
        {{ FLIGHT_LABELS[action] }}
      </n-button>
    </div>
    <p class="hint">키보드: W·S 앞뒤, A·D 돌기, Q·E 옆으로, R·F 위아래, 스페이스 멈춤, X 쏘기</p>

    <label class="slider-label" for="forward-speed">앞뒤 빠르기 {{ speeds.forward }} m/s</label>
    <n-slider id="forward-speed" v-model:value="speeds.forward" :min="SPEED_STEP" :max="limits.forward.max" :step="SPEED_STEP" />
    <label class="slider-label" for="climb-speed">오르내리는 빠르기 {{ speeds.climb }} m/s</label>
    <n-slider id="climb-speed" v-model:value="speeds.climb" :min="SPEED_STEP" :max="limits.up.max" :step="SPEED_STEP" />
    <label class="slider-label" for="turn-speed">도는 빠르기 {{ speeds.turn.toFixed(2) }} rad/s</label>
    <n-slider id="turn-speed" v-model:value="speeds.turn" :min="TURN_STEP" :max="limits.turn.max" :step="TURN_STEP" />
    <p class="hint">빠르기는 다음에 누르는 버튼부터 쓰입니다. 옆으로는 앞뒤 빠르기의 절반으로 납니다.</p>

    <h3>시험: 밀어 보기</h3>
    <p class="hint">
      몸통을 {{ PUSH_DURATION_MS / 1000 }}초 동안 밀어 맞았을 때처럼 흔듭니다. 비행 제어가 다시 똑바로 세우는지 봅니다.
    </p>
    <label class="slider-label" for="push-strength">미는 힘 {{ pushKilonewtons }} kN</label>
    <n-slider id="push-strength" v-model:value="pushKilonewtons" :min="PUSH_STEP_KN"
              :max="limits.pushForce.max / NEWTONS_PER_KILONEWTON" :step="PUSH_STEP_KN" />
    <n-space>
      <n-button v-for="from in pushes" :key="from" :data-test="`push-${from}`" :disabled="!!disabledReason"
                @click="push(from)">
        {{ PUSH_LABELS[from] }}
      </n-button>
    </n-space>
  </n-card>
</template>

<style scoped>
.notice {
  margin-bottom: 12px;
}
.pad {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 6px;
}
.hint {
  margin: 6px 0 12px;
  color: #64748b;
  font-size: 12px;
}
.slider-label {
  display: block;
  font-size: 13px;
  margin-top: 4px;
}
h3 {
  margin: 16px 0 0;
  font-size: 14px;
}
</style>
