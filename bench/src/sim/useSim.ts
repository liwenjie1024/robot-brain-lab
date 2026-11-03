import { computed, onBeforeUnmount, onMounted, readonly, ref, shallowRef } from 'vue'
import type { StateMessage } from '@shared/sim/generated/message'
import type { SceneDescription } from '@shared/sim/generated/scene'
import type { CombatEvent, CommandResult, ConnectionPhase, OutgoingCommand, SimClient } from '@shared/sim/simClient'

export interface CommandLogEntry {
  label: string
  at: Date
  result: CommandResult
}

export interface CombatLogEntry {
  /** 같은 시각에 사격과 격파가 함께 올 수 있어 받은 순서로 번호를 매긴다 */
  key: number
  at: Date
  event: CombatEvent
}

/** 상태는 50Hz로 오지만 글자 표시는 이 간격으로만 바꾼다 (3D는 따로 매번 그린다). */
const DISPLAY_INTERVAL_MS = 100
const LOG_SIZE = 12
const COMBAT_LOG_SIZE = 15

/** 기체 모드나 위협이 바뀌면 표시 간격을 기다리지 않는다 (경고가 늦게 보이면 안 되므로). */
function changedUrgently(previous: StateMessage | null, next: StateMessage): boolean {
  if (!previous) {
    return true
  }
  const threatsOf = (state: StateMessage) => state.threats.map((threat) => threat.from).join(',')
  return previous.mecha.mode !== next.mecha.mode || threatsOf(previous) !== threatsOf(next)
}

export function useSim(client: SimClient) {
  const phase = ref<ConnectionPhase>('loading-scene')
  const phaseDetail = ref<string | undefined>()
  const scene = shallowRef<SceneDescription | null>(null)
  const state = shallowRef<StateMessage | null>(null)
  const invalidMessages = ref(0)
  const log = ref<CommandLogEntry[]>([])
  const combatLog = ref<CombatLogEntry[]>([])
  let lastDisplayed = 0
  let combatKey = 0

  const unsubscribe = [
    client.on('phase', (value, detail) => {
      phase.value = value
      phaseDetail.value = detail
    }),
    client.on('scene', (value) => {
      scene.value = value
    }),
    client.on('state', (value) => {
      const now = Date.now()
      if (now - lastDisplayed >= DISPLAY_INTERVAL_MS || changedUrgently(state.value, value)) {
        lastDisplayed = now
        state.value = value
      }
    }),
    client.on('combat', (event) => {
      combatLog.value = [{ key: combatKey++, at: new Date(), event }, ...combatLog.value].slice(0, COMBAT_LOG_SIZE)
    }),
    client.on('invalidMessage', () => {
      invalidMessages.value++
    }),
  ]

  async function send(label: string, command: OutgoingCommand): Promise<CommandResult> {
    const result = await client.send(command)
    log.value = [{ label, at: new Date(), result }, ...log.value].slice(0, LOG_SIZE)
    return result
  }

  onMounted(() => {
    void client.connect()
  })
  onBeforeUnmount(() => {
    unsubscribe.forEach((stop) => stop())
    client.close()
  })

  return {
    phase: readonly(phase),
    phaseDetail: readonly(phaseDetail),
    scene,
    state,
    invalidMessages: readonly(invalidMessages),
    log: readonly(log),
    // 사건의 좌표 배열까지 읽기 전용으로 바꾸면 규약 타입과 맞지 않아, 목록만 바꿀 수 없게 내준다.
    combatLog: computed(() => combatLog.value),
    send,
    retry: () => client.retry(),
  }
}
