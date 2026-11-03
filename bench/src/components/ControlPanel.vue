<script setup lang="ts">
import { NAlert, NButton, NCard, NSlider, NSpace } from 'naive-ui'
import { onBeforeUnmount, onMounted, reactive, ref } from 'vue'
import {
  DEFAULT_SPEEDS,
  DRIVE_LABELS,
  type DriveAction,
  keyboardAction,
  PUSH_DURATION_MS,
  PUSH_LABELS,
  type PushFrom,
  pushForce,
  type Velocity,
  velocityFor,
} from '@/control/drive'
import type { Limits } from '@/sim/generated/scene'

/** 사람이 몸을 직접 움직여 보는 칸 (두뇌 없이 몸과 운동 제어만 시험할 때) */
const props = defineProps<{
  limits: Limits
  /** 로봇이 바라보는 방향 rad (밀기 방향을 로봇 기준으로 정한다) */
  yaw: number
  /** 명령을 보낼 수 없으면 그 까닭 */
  disabledReason: string | null
  fallen: boolean
}>()

const emit = defineEmits<{
  drive: [label: string, velocity: Velocity]
  push: [label: string, force: [number, number, number], durationMs: number]
  reset: []
}>()

const DEFAULT_PUSH_N = 150
const PUSH_STEP_N = 10
const SPEED_STEP = 0.05

const speeds = reactive({ ...DEFAULT_SPEEDS })
const pushStrength = ref(DEFAULT_PUSH_N)

const pad: (DriveAction | null)[] = ['turnLeft', 'forward', 'turnRight', 'stepLeft', 'stop', 'stepRight', null, 'backward', null]
const pushes: PushFrom[] = ['front', 'back', 'left', 'right']

function drive(action: DriveAction) {
  if (props.disabledReason) {
    return
  }
  emit('drive', DRIVE_LABELS[action], velocityFor(action, speeds, props.limits))
}

function push(from: PushFrom) {
  emit('push', `${PUSH_LABELS[from]} ${pushStrength.value}N`, pushForce(from, props.yaw, pushStrength.value), PUSH_DURATION_MS)
}

function onKey(event: KeyboardEvent) {
  const action = keyboardAction(event)
  if (action) {
    event.preventDefault()
    drive(action)
  }
}

onMounted(() => window.addEventListener('keydown', onKey))
onBeforeUnmount(() => window.removeEventListener('keydown', onKey))
</script>

<template>
  <n-card title="직접 움직여 보기" size="small">
    <n-alert v-if="disabledReason" type="warning" :show-icon="false" class="notice">{{ disabledReason }}</n-alert>
    <n-alert v-else-if="fallen" type="error" :show-icon="false" class="notice" data-test="fallen-notice">
      넘어졌습니다. 아래의 "처음 자세로"를 눌러 다시 세우세요.
    </n-alert>

    <div class="pad" role="group" aria-label="걷기 방향">
      <template v-for="(action, index) in pad" :key="index">
        <n-button v-if="action" :data-test="`drive-${action}`" :type="action === 'stop' ? 'error' : 'default'"
                  :disabled="!!disabledReason" @click="drive(action)">
          {{ DRIVE_LABELS[action] }}
        </n-button>
        <span v-else />
      </template>
    </div>
    <p class="hint">키보드: W·S 앞뒤, A·D 돌기, Q·E 옆걸음, 스페이스 멈춤</p>

    <label class="slider-label" for="walk-speed">걷기 빠르기 {{ speeds.walk.toFixed(2) }} m/s</label>
    <n-slider id="walk-speed" v-model:value="speeds.walk" :min="SPEED_STEP" :max="limits.forward.max" :step="SPEED_STEP" />
    <label class="slider-label" for="turn-speed">도는 빠르기 {{ speeds.turn.toFixed(2) }} rad/s</label>
    <n-slider id="turn-speed" v-model:value="speeds.turn" :min="SPEED_STEP" :max="limits.turn.max" :step="SPEED_STEP" />
    <p class="hint">빠르기는 다음에 누르는 버튼부터 쓰입니다.</p>

    <h3>시험: 밀어 보기</h3>
    <p class="hint">
      몸통을 {{ PUSH_DURATION_MS / 1000 }}초 동안 밀어 운동 제어가 버티는지 봅니다.
      300N 넘게 세게 밀면 넘어질 수 있습니다.
    </p>
    <label class="slider-label" for="push-strength">미는 힘 {{ pushStrength }} N</label>
    <n-slider id="push-strength" v-model:value="pushStrength" :min="PUSH_STEP_N" :max="limits.pushForce.max" :step="PUSH_STEP_N" />
    <n-space class="pushes">
      <n-button v-for="from in pushes" :key="from" :data-test="`push-${from}`" :disabled="!!disabledReason"
                @click="push(from)">
        {{ PUSH_LABELS[from] }}
      </n-button>
    </n-space>

    <n-button class="reset" data-test="reset" :disabled="!!disabledReason" @click="emit('reset')">처음 자세로</n-button>
    <p class="hint">로봇을 시작 자리에 다시 세우고, 걷기 명령을 멈춤으로 돌립니다.</p>
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
.pushes {
  margin-bottom: 16px;
}
.reset {
  width: 100%;
}
</style>
