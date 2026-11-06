import { describe, expect, it } from 'vitest'
import { drone, mechaStatus, perceptionOf } from '../testing'
import { PLAN_FORMAT, planMessages, sceneSummary, SYSTEM_PROMPT } from './prompt'

const PERCEPTION = perceptionOf({
  mecha: mechaStatus({ position: [0, 0, 30.4], hp: 800, energy: 72.6 }),
  units: [drone({ id: 'drone-1', position: [300, 0, 30], armed: true, hp: 20 }), drone({ id: 'drone-2', position: [100, 0, 30] })],
  threats: [{ from: 'drone-1', secondsToFire: 0.8 }],
})

describe('prompt', () => {
  it('장면 요약에는 드론 id·거리·체력·무장과 나를 겨누는지가 가까운 순으로 든다', () => {
    expect(sceneSummary(PERCEPTION)).toEqual({
      self: { hp: 800, maxHp: 1000, energy: 73, altitude: 30, mode: 'flying' },
      drones: [
        { id: 'drone-2', name: '표적 드론 1', distance: 100, armed: false, hp: 60, maxHp: 60, aimingAtMe: false },
        { id: 'drone-1', name: '표적 드론 1', distance: 300, armed: true, hp: 20, maxHp: 60, aimingAtMe: true },
      ],
    })
  })

  it('처음에는 규칙과 장면·명령을, 다시 물을 때는 지난 답과 틀린 까닭을 덧붙인다', () => {
    expect(planMessages('공격해', PERCEPTION).map((message) => message.role)).toEqual(['system', 'user'])

    const retry = planMessages('공격해', PERCEPTION, { answer: '{"say":', problem: '단계 1: hold의 target은 null이어야 합니다' })

    expect(retry.map((message) => message.role)).toEqual(['system', 'user', 'assistant', 'user'])
    expect(retry[0]?.content).toBe(SYSTEM_PROMPT)
    expect(retry[2]?.content).toBe('{"say":')
    expect(retry[3]?.content).toContain('단계 1: hold의 target은 null이어야 합니다')
  })

  it('경계값: 지난 답이 비었으면 빈 답이라고 쓴다', () => {
    expect(planMessages('공격해', PERCEPTION, { answer: '', problem: '전체 must be object' })[2]?.content).toBe('(빈 답)')
  })

  it('언어 모델에 주는 형식은 참조 없이 풀려 있고, 피하기에서 none을 뺐다', () => {
    const text = JSON.stringify(PLAN_FORMAT)

    expect(text).not.toContain('$ref')
    expect(PLAN_FORMAT).toMatchObject({
      required: ['say', 'retreatBelowHp', 'steps'],
      properties: { steps: { items: { properties: { evasion: { enum: ['dodge', 'guard', 'both'] } } } } },
    })
  })
})
