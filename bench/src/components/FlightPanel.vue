<script setup lang="ts">
import { NButton, NCard, NSlider } from 'naive-ui'
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
import type { Limits } from '@shared/sim/generated/scene'
import HelpTip from './HelpTip.vue'

/** 사람이 기체를 직접 날려 보는 칸 (두뇌 없이 몸과 비행 제어를 시험하거나 두뇌를 거들 때) */
const props = withDefaults(
  defineProps<{
    limits: Limits
    /** 기수 방향 rad (밀기 방향을 기체 기준으로 정한다) */
    heading: number
    /** 명령을 보낼 수 없으면 그 까닭 */
    disabledReason: string | null
    destroyed: boolean
    /** 키보드로 조종할지 (이 칸이 보이지 않을 때는 끈다) */
    keyboard?: boolean
  }>(),
  { keyboard: true },
)

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
const KEYBOARD_HELP = '키보드: W·S 앞뒤, A·D 돌기, Q·E 옆으로, R·F 위아래, 스페이스 멈춤, X 쏘기. 빠르기는 다음에 누르는 버튼부터 쓰이고, 옆으로는 앞뒤 빠르기의 절반으로 납니다.'

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
  if (!action || props.disabledReason || !props.keyboard) {
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
  <n-card size="small" class="flight">
    <template #header>
      직접 날려 보기
      <help-tip :text="KEYBOARD_HELP" />
    </template>
    <p v-if="disabledReason" class="notice" role="status">🔒 {{ disabledReason }}</p>
    <p v-else-if="destroyed" class="notice destroyed" role="alert" data-test="destroyed-notice">
      기체가 파괴되었습니다. "시험 장면"의 "처음으로"를 눌러 다시 시작하세요.
    </p>

    <div class="pad" role="group" aria-label="비행 방향">
      <n-button v-for="action in pad" :key="action" size="small" :data-test="`fly-${action}`"
                :type="action === 'stop' ? 'error' : 'default'" :disabled="!!disabledReason" @click="fly(action)">
        {{ FLIGHT_LABELS[action] }}
      </n-button>
    </div>

    <div class="speeds">
      <label for="forward-speed">앞뒤 {{ speeds.forward }} m/s</label>
      <n-slider id="forward-speed" v-model:value="speeds.forward" :min="SPEED_STEP" :max="limits.forward.max" :step="SPEED_STEP" />
      <label for="climb-speed">오르내리기 {{ speeds.climb }} m/s</label>
      <n-slider id="climb-speed" v-model:value="speeds.climb" :min="SPEED_STEP" :max="limits.up.max" :step="SPEED_STEP" />
      <label for="turn-speed">돌기 {{ speeds.turn.toFixed(2) }} rad/s</label>
      <n-slider id="turn-speed" v-model:value="speeds.turn" :min="TURN_STEP" :max="limits.turn.max" :step="TURN_STEP" />
    </div>

    <details class="push">
      <summary>
        시험: 밀어 보기
        <help-tip :text="`몸통을 ${PUSH_DURATION_MS / 1000}초 동안 밀어 맞았을 때처럼 흔듭니다. 비행 제어가 다시 똑바로 세우는지 봅니다.`" />
      </summary>
      <div class="speeds">
        <label for="push-strength">미는 힘 {{ pushKilonewtons }} kN</label>
        <n-slider id="push-strength" v-model:value="pushKilonewtons" :min="PUSH_STEP_KN"
                  :max="limits.pushForce.max / NEWTONS_PER_KILONEWTON" :step="PUSH_STEP_KN" />
      </div>
      <div class="push-buttons">
        <n-button v-for="from in pushes" :key="from" size="small" :data-test="`push-${from}`" :disabled="!!disabledReason"
                  @click="push(from)">
          {{ PUSH_LABELS[from] }}
        </n-button>
      </div>
    </details>
  </n-card>
</template>

<style scoped>
.notice {
  margin: 0 0 6px;
  padding: 4px 8px;
  border-radius: 4px;
  background: #fef3c7;
  color: #92400e;
  font-size: 12px;
}
.notice.destroyed {
  background: #fee2e2;
  color: #b91c1c;
}
.pad {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
}
.speeds {
  display: grid;
  grid-template-columns: 8.5em 1fr;
  align-items: center;
  gap: 0 8px;
  margin-top: 6px;
  font-size: 12px;
}
.push {
  margin-top: 6px;
  font-size: 12px;
}
.push summary {
  cursor: pointer;
  color: #475569;
}
.push-buttons {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(96px, 1fr));
  gap: 4px;
  margin-top: 4px;
}
</style>
