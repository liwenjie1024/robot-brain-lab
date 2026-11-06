import { describe, expect, it } from 'vitest'
import { type RunFacts, scoreRun } from './trialScore'

const facts = (overrides: Partial<RunFacts> = {}): RunFacts => ({
  drones: 3,
  kills: 3,
  clearTimeS: 30,
  timeLimitS: 60,
  damageTaken: 100,
  maxHp: 1000,
  ...overrides,
})

describe('scoreRun', () => {
  it('격파 50점 + 빠르기 25점 × 남은 시간 비율 + 버티기 25점 × 남은 체력 비율', () => {
    expect(scoreRun(facts())).toBe(50 + 12.5 + 22.5)
  })

  it('경계값: 피해 없이 바로 다 격파하면 100점, 아무것도 못 하고 파괴되면 0점', () => {
    expect(scoreRun(facts({ clearTimeS: 0, damageTaken: 0 }))).toBe(100)
    expect(scoreRun(facts({ kills: 0, clearTimeS: null, damageTaken: 1000 }))).toBe(0)
  })

  it('다 격파하지 못하면 빠르기 점수가 없고, 격파한 비율만큼 격파 점수를 받는다', () => {
    expect(scoreRun(facts({ kills: 2, clearTimeS: null, damageTaken: 0 }))).toBe(58.3)
  })

  it('경계값: 제한 시간을 넘긴 격파나 최대 체력보다 큰 피해도 0 아래로 깎지 않는다', () => {
    expect(scoreRun(facts({ clearTimeS: 90, damageTaken: 1500 }))).toBe(50)
  })

  it('드론이 없는 장면은 격파 점수를 주지 않는다 (0으로 나누지 않음)', () => {
    expect(scoreRun(facts({ drones: 0, kills: 0, clearTimeS: null, damageTaken: 0 }))).toBe(25)
  })
})
