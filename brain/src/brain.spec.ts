import { describe, expect, it } from 'vitest'
import { Brain } from './brain'
import { drone, mechaStatus, RecordingSender, ScriptedModel, stateMessage } from './testing'

function setup() {
  const sender = new RecordingSender()
  const brain = new Brain(sender, new ScriptedModel(), () => 0)
  brain.setSimConnected(true)
  return { sender, brain }
}

const STATE = stateMessage({ simTime: 2, mecha: mechaStatus({ position: [0, 0, 30], heading: 0 }), units: [drone({ id: 'drone-1', position: [400, 0, 30] })] })

describe('Brain', () => {
  it('상태에는 빠른 뇌의 판단과 느린 뇌의 계획·언어 모델이 함께 든다', () => {
    const { brain } = setup()

    expect(brain.status()).toMatchObject({ type: 'brainStatus', skill: { name: 'idle' }, plan: null, planner: { model: 'test-model', available: false } })
  })

  it('계획의 단계가 바뀌면 같은 상태로 빠른 뇌가 바로 새 기술을 따른다', async () => {
    const { brain, sender } = setup()
    await brain.order('공격')
    brain.onState(STATE)
    sender.clear()

    brain.onState({ ...STATE, simTime: 2.02, units: [drone({ id: 'drone-1', alive: false })] })

    expect(brain.status()).toMatchObject({ skill: { name: 'hold' }, plan: { current: 1 } })
    expect(sender.types()).toContain('velocity')
  })

  it('사람이 기술을 직접 고르면 계획을 그만두고 사람이 고른 기술을 한다', async () => {
    const { brain } = setup()
    await brain.order('공격')

    brain.chooseSkill('retreat', null, 'guard')

    expect(brain.status()).toMatchObject({ skill: { name: 'retreat', evasion: 'guard' }, plan: { state: 'cancelled' } })
    expect(brain.log.recent().map((decision) => decision.text)).toContain('계획을 그만둠: 사람이 기술을 직접 고름')
  })

  it('사람이 조종을 가져가면 계획을 그만두고, 다시 맡겨도 계획은 이어지지 않는다', async () => {
    const { brain } = setup()
    await brain.order('공격')

    brain.setAutonomy(false)
    brain.setAutonomy(true)

    expect(brain.status()).toMatchObject({ autonomy: true, plan: { state: 'cancelled' } })
  })
})
