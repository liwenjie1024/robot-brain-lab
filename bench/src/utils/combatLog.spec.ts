import { describe, expect, it } from 'vitest'
import type { ShotMessage } from '@/sim/generated/message'
import { NAMES } from '@/test/fixtures'
import { describeCombatEvent } from './combatLog'

function shot(overrides: Partial<ShotMessage>): ShotMessage {
  return { type: 'shot', simTime: 1, shooter: 'mecha', from: [0, 0, 30], to: [150, 0, 25], ...overrides }
}

describe('describeCombatEvent', () => {
  it.each([
    [shot({ hit: { unit: 'drone-1', damage: 30, blocked: false } }), '기체가 쏨 → 표적 드론 1 맞힘 (체력 -30)', 'success'],
    [shot({}), '기체가 쏨 → 빗나감', 'default'],
    [shot({ shooter: 'drone-2', hit: { unit: 'mecha', damage: 40, blocked: false } }), '표적 드론 2이(가) 쏨 → 기체가 맞음 (체력 -40)', 'error'],
    [shot({ shooter: 'drone-2', hit: { unit: 'mecha', damage: 0, blocked: true } }), '표적 드론 2이(가) 쏨 → 방패로 막음', 'info'],
  ])('사격 결과를 한 줄로 쓴다 (%#)', (event, text, type) => {
    expect(describeCombatEvent(event, NAMES)).toEqual({ text, type })
  })

  it('격파: 드론은 좋은 소식, 기체는 나쁜 소식으로 보인다', () => {
    expect(describeCombatEvent({ type: 'destroyed', simTime: 1, unit: 'drone-1' }, NAMES)).toEqual({
      text: '표적 드론 1 파괴',
      type: 'success',
    })
    expect(describeCombatEvent({ type: 'destroyed', simTime: 1, unit: 'mecha' }, NAMES).type).toBe('error')
  })

  it('이름을 모르는 유닛은 번호로 쓴다', () => {
    expect(describeCombatEvent(shot({ shooter: 'drone-9' }), NAMES).text).toBe('drone-9이(가) 쏨 → 빗나감')
  })
})
