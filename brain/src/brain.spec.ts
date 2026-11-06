import { describe, expect, it } from 'vitest'
import { sceneDescription } from '@shared/test/fixtures'
import { Brain } from './brain'
import { drone, mechaStatus, RecordingSender, ScriptedModel, settle, stateMessage } from './testing'

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

  it('시험은 장면을 되돌린 뒤 첫 상태에서 두뇌에게 기술을 맡기고, 판의 시작·끝을 판단 기록에 남긴다', async () => {
    const { brain, sender } = setup()
    brain.setScene(sceneDescription())
    brain.onState(STATE)

    expect(brain.startTrials({ type: 'startTrials', scenario: 'skirmish', setups: [{ kind: 'skill', skill: 'engage', evasion: 'guard' }], runs: 1, timeLimitS: 60, startSpreadS: 0 })).toBeNull()
    await settle()
    brain.onState({ ...STATE, simTime: 0.02, scenario: 'skirmish' })
    brain.onState({ ...STATE, simTime: 20, scenario: 'skirmish', units: [drone({ id: 'drone-1', alive: false })] })
    await settle()

    expect(sender.sent).toContainEqual({ type: 'reset', scenario: 'skirmish' })
    expect(brain.status()).toMatchObject({ autonomy: false, skill: { name: 'engage', evasion: 'guard' }, trials: { state: 'done', setups: [{ summary: { cleared: 1 } }] } })
    const trialNotes = brain.log.recent().filter((decision) => decision.kind === 'trial').map((decision) => decision.text)
    expect(trialNotes).toEqual([
      '시험 시작: 반격하는 드론, 1가지 × 1판 (한 판 60초까지)',
      '시험 1판째: 교전 · 방패로 막기',
      expect.stringMatching(/^시험 1판째 끝: 교전 · 방패로 막기 — 다 격파 \(20초, 피해 0, 점수 \d+/),
      '시험 끝 (다 돌림, 1판)',
    ])
  })
})
