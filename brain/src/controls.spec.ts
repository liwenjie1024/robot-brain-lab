import { describe, expect, it } from 'vitest'
import { sceneDescription } from '@shared/test/fixtures'
import { Brain } from './brain'
import { applyControl } from './controls'
import { RecordingSender, ScriptedModel } from './testing'

function setup() {
  return new Brain(new RecordingSender(), new ScriptedModel(), () => 0)
}

const SETUP = { kind: 'skill', skill: 'engage', evasion: 'dodge' }
const TRIALS = JSON.stringify({ type: 'startTrials', scenario: 'skirmish', setups: [SETUP], runs: 10, timeLimitS: 120, startSpreadS: 10 })

describe('applyControl', () => {
  const targets = new Set(['drone-1'])

  it('기술과 맡기 지시를 받고 번호를 돌려준다', () => {
    const brain = setup()

    expect(applyControl('{"type":"setSkill","id":"s1","skill":"engage","target":"drone-1","evasion":"guard"}', brain, targets)).toEqual({
      type: 'controlResult',
      id: 's1',
      accepted: true,
    })
    expect(applyControl('{"type":"setAutonomy","enabled":true}', brain, targets).accepted).toBe(true)
    expect(brain.status()).toMatchObject({ autonomy: true, skill: { name: 'engage', target: 'drone-1', evasion: 'guard' } })
  })

  it('말로 한 명령을 받으면 바로 답하고, 두뇌가 조종을 맡아 계획을 따른다', () => {
    const brain = setup()

    expect(applyControl('{"type":"order","id":"o1","text":"공격해"}', brain, targets)).toEqual({ type: 'controlResult', id: 'o1', accepted: true })

    expect(brain.status()).toMatchObject({ autonomy: true, skill: { name: 'engage' }, plan: { source: 'quick', state: 'running' } })
  })

  it('계획 그만두기를 받으면 계획을 멈추고, 기체는 지금 기술을 그대로 한다', () => {
    const brain = setup()
    applyControl('{"type":"order","text":"물러나"}', brain, targets)

    expect(applyControl('{"type":"cancelPlan","id":"c1"}', brain, targets)).toEqual({ type: 'controlResult', id: 'c1', accepted: true })

    expect(brain.status()).toMatchObject({ skill: { name: 'retreat' }, plan: { state: 'cancelled' } })
  })

  it('중복: 이미 그만둔 계획을 또 그만두라면 까닭을 붙여 거절한다', () => {
    const brain = setup()
    applyControl('{"type":"order","text":"물러나"}', brain, targets)
    applyControl('{"type":"cancelPlan"}', brain, targets)

    const again = applyControl('{"type":"cancelPlan"}', brain, targets)

    expect(again).toMatchObject({ accepted: false, reason: '그만둘 계획이 없습니다' })
  })

  it.each([
    ['JSON이 아님', '{기술', 'JSON이 아닙니다'],
    ['모르는 기술', '{"type":"setSkill","skill":"dance"}', '지시 모양이 맞지 않습니다'],
    ['모르는 지시', '{"type":"selfDestruct"}', '지시 모양이 맞지 않습니다'],
    ['없는 표적', '{"type":"setSkill","id":"s2","skill":"engage","target":"drone-9"}', '그런 표적이 없습니다: drone-9'],
    ['빈 명령', '{"type":"order","text":""}', '지시 모양이 맞지 않습니다'],
    ['띄어쓰기뿐인 명령', '{"type":"order","text":"   "}', '명령이 비어 있습니다'],
    ['200자를 넘는 명령', JSON.stringify({ type: 'order', text: '가'.repeat(201) }), '지시 모양이 맞지 않습니다'],
    ['계획이 없을 때 그만두기', '{"type":"cancelPlan"}', '그만둘 계획이 없습니다'],
  ])('실패: %s이면 까닭을 붙여 거절한다', (_, text, reason) => {
    const brain = setup()

    const result = applyControl(text, brain, targets)

    expect(result.accepted).toBe(false)
    expect(result.reason).toContain(reason)
  })

  it('시험을 시작하면 시험 멈추기 말고는 받지 않고, 멈춘 뒤에는 다시 받는다', () => {
    const brain = setup()
    brain.setScene(sceneDescription())
    brain.setSimConnected(true)

    expect(applyControl(TRIALS, brain, targets)).toEqual({ type: 'controlResult', accepted: true })
    for (const text of ['{"type":"setSkill","skill":"hold"}', '{"type":"order","text":"공격"}', '{"type":"setAutonomy","enabled":false}', TRIALS]) {
      expect(applyControl(text, brain, targets)).toMatchObject({ accepted: false, reason: '시험 중에는 할 수 없습니다. 시험을 멈춘 뒤 해 주세요' })
    }
    expect(applyControl('{"type":"stopTrials"}', brain, targets).accepted).toBe(true)
    expect(applyControl('{"type":"setSkill","skill":"hold"}', brain, targets).accepted).toBe(true)
  })

  it.each([
    ['비교할 것이 없음', { setups: [] }],
    ['비교할 것 7가지', { setups: Array.from({ length: 7 }, () => SETUP) }],
    ['0판', { runs: 0 }],
    ['11판', { runs: 11 }],
    ['제한 시간 9초', { timeLimitS: 9 }],
    ['제한 시간 121초', { timeLimitS: 121 }],
    ['모르는 비교 방법', { setups: [{ kind: 'dance' }] }],
    ['맡는 때를 앞당김(-1초)', { startSpreadS: -1 }],
    ['맡는 때를 10초 넘게 늦춤', { startSpreadS: 10.5 }],
  ])('경계값·실패: 시험 지시가 %s이면 모양이 맞지 않는다고 거절한다', (_, change) => {
    const brain = setup()

    expect(applyControl(JSON.stringify({ ...JSON.parse(TRIALS), ...change }), brain, targets).reason).toContain('지시 모양이 맞지 않습니다')
  })

  it('실패: 몸에 연결되지 않았거나 돌고 있는 시험이 없으면 시작·멈추기를 까닭과 함께 거절한다', () => {
    const brain = setup()

    expect(applyControl(TRIALS, brain, targets).reason).toContain('몸(시뮬레이터)에 연결되어야')
    expect(applyControl('{"type":"stopTrials"}', brain, targets).reason).toBe('돌고 있는 시험이 없습니다')
  })

  it('경계값: 200자 명령은 받는다', () => {
    const brain = setup()

    expect(applyControl(JSON.stringify({ type: 'order', text: '가'.repeat(200) }), brain, targets).accepted).toBe(true)
  })
})
