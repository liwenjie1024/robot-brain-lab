import { computed, onBeforeUnmount, onMounted, type Ref, ref, shallowRef } from 'vue'
import type { Evasion, SkillName } from '@shared/brain/generated/control'
import type { BrainStatus, ControlResult, Decision } from '@shared/brain/generated/status'
import type { BrainClient, BrainPhase } from './brainClient'

const DECISIONS_KEPT = 40

export function useBrain(client: BrainClient) {
  const phase = ref<BrainPhase>('connecting')
  const status = shallowRef<BrainStatus | null>(null)
  const decisions = ref<Decision[]>([])
  const lastError = ref<string | null>(null)
  /** 말로 한 명령·계획 그만두기를 두뇌가 받지 않은 까닭 (명령 칸에 보인다) */
  const orderError = ref<string | null>(null)

  const unsubscribe = [
    client.on('phase', (value) => {
      phase.value = value
      if (value !== 'open') {
        status.value = null
      }
    }),
    client.on('status', (value) => {
      status.value = value
    }),
    client.on('decision', (decision) => {
      if (decisions.value.some((known) => known.seq === decision.seq)) {
        return
      }
      decisions.value = [decision, ...decisions.value].slice(0, DECISIONS_KEPT)
    }),
  ]

  async function apply(result: Promise<ControlResult>, error: Ref<string | null> = lastError): Promise<void> {
    const outcome = await result
    error.value = outcome.accepted ? null : (outcome.reason ?? '두뇌가 지시를 받지 않았습니다')
  }

  onMounted(() => client.connect())
  onBeforeUnmount(() => {
    unsubscribe.forEach((stop) => stop())
    client.close()
  })

  return {
    phase,
    status,
    decisions,
    lastError,
    orderError,
    /** 두뇌가 몸을 조종하고 있음 (사람의 직접 조종을 막는다) */
    driving: computed(() => phase.value === 'open' && status.value?.autonomy === true),
    setAutonomy: (enabled: boolean) => apply(client.send({ type: 'setAutonomy', enabled })),
    setSkill: (skill: SkillName, target: string | null, evasion: Evasion) =>
      apply(client.send(target ? { type: 'setSkill', skill, target, evasion } : { type: 'setSkill', skill, evasion })),
    order: (text: string) => apply(client.send({ type: 'order', text }), orderError),
    cancelPlan: () => apply(client.send({ type: 'cancelPlan' }), orderError),
    retry: () => client.retry(),
  }
}
