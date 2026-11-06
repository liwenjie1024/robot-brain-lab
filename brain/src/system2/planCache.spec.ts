import { describe, expect, it } from 'vitest'
import type { Plan } from '@shared/brain/generated/plan'
import { PlanCache, type Situation } from './planCache'

const PLAN: Plan = {
  say: '드론 2부터 잡겠습니다.',
  retreatBelowHp: 0,
  steps: [{ skill: 'engage', target: 'drone-2', evasion: 'dodge', until: 'targetDestroyed', value: 0 }],
}
const SITUATION: Situation = { scenario: 'skirmish', targets: new Set(['drone-1', 'drone-2']) }

describe('PlanCache', () => {
  it('같은 명령·같은 상황이면 기억한 계획을 준다 (띄어쓰기·문장 부호·드론 순서는 달라도 된다)', () => {
    const cache = new PlanCache()
    cache.put('드론 2부터 잡아!', SITUATION, PLAN)

    expect(cache.get('드론2부터  잡아', { scenario: 'skirmish', targets: new Set(['drone-2', 'drone-1']) })).toEqual(PLAN)
  })

  it.each([
    ['다른 명령', '드론 1부터 잡아', SITUATION],
    ['다른 시험 장면', '드론 2부터 잡아', { ...SITUATION, scenario: 'targets' }],
    ['살아 있는 드론이 다름', '드론 2부터 잡아', { ...SITUATION, targets: new Set(['drone-2']) }],
  ])('%s이면 주지 않는다', (_, order, situation) => {
    const cache = new PlanCache()
    cache.put('드론 2부터 잡아', SITUATION, PLAN)

    expect(cache.get(order, situation)).toBeUndefined()
  })

  it('경계값: 가득 차면 가장 오래 안 쓴 것부터 잊는다', () => {
    const cache = new PlanCache(2)
    cache.put('하나', SITUATION, PLAN)
    cache.put('둘', SITUATION, PLAN)
    cache.get('하나', SITUATION)

    cache.put('셋', SITUATION, PLAN)

    expect(cache.get('하나', SITUATION)).toBeDefined()
    expect(cache.get('둘', SITUATION)).toBeUndefined()
    expect(cache.get('셋', SITUATION)).toBeDefined()
  })

  it('중복: 같은 명령을 다시 넣으면 새 계획으로 바꾼다', () => {
    const cache = new PlanCache()
    cache.put('잡아', SITUATION, PLAN)

    cache.put('잡아', SITUATION, { ...PLAN, say: '새 계획' })

    expect(cache.get('잡아', SITUATION)?.say).toBe('새 계획')
  })

  it('꺼낸 계획을 고쳐도 기억한 것은 그대로다', () => {
    const cache = new PlanCache()
    cache.put('잡아', SITUATION, PLAN)

    cache.get('잡아', SITUATION)?.steps.pop()

    expect(cache.get('잡아', SITUATION)?.steps).toHaveLength(1)
  })
})
