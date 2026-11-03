import { onBeforeUnmount, onMounted, readonly, ref, shallowRef } from 'vue'
import type { StateMessage } from './generated/message'
import type { SceneDescription } from './generated/scene'
import type { CommandResult, ConnectionPhase, OutgoingCommand, SimClient } from './simClient'

export interface CommandLogEntry {
  label: string
  at: Date
  result: CommandResult
}

/** 상태는 50Hz로 오지만 글자 표시는 이 간격으로만 바꾼다 (3D는 따로 매번 그린다). */
const DISPLAY_INTERVAL_MS = 100
const LOG_SIZE = 12

export function useSim(client: SimClient) {
  const phase = ref<ConnectionPhase>('loading-scene')
  const phaseDetail = ref<string | undefined>()
  const scene = shallowRef<SceneDescription | null>(null)
  const state = shallowRef<StateMessage | null>(null)
  const invalidMessages = ref(0)
  const log = ref<CommandLogEntry[]>([])
  let lastDisplayed = 0

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
      if (now - lastDisplayed >= DISPLAY_INTERVAL_MS || value.robot.posture !== state.value?.robot.posture) {
        lastDisplayed = now
        state.value = value
      }
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
    send,
    retry: () => client.retry(),
  }
}
