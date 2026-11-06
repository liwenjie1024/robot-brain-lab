import { describe, expect, it } from 'vitest'
import { normalizeOrder, quickPlan } from './quickOrders'

describe('quickPlan', () => {
  it.each([
    ['멈춰!', 'idle'],
    ['그만해', 'idle'],
    ['정지', 'idle'],
    ['물러나', 'retreat'],
    ['물러나라!!', 'retreat'],
    ['후퇴해', 'retreat'],
    ['도망쳐', 'retreat'],
    ['자리 지켜', 'hold'],
    ['대기해요', 'hold'],
    ['공격해!', 'engage'],
    ['공격하세요', 'engage'],
    ['다 잡아', 'engage'],
    ['  싸워라 ~ ', 'engage'],
    ['STOP', 'idle'],
  ])('"%s"는 언어 모델 없이 바로 %s로 알아듣는다', (order, skill) => {
    expect(quickPlan(order)?.steps[0]?.skill).toBe(skill)
  })

  it('공격은 모든 드론을 격파할 때까지 교전한 뒤 자리를 지킨다', () => {
    expect(quickPlan('공격')).toEqual({
      say: expect.any(String),
      retreatBelowHp: 0,
      steps: [
        { skill: 'engage', target: null, evasion: 'dodge', until: 'allDestroyed', value: 0 },
        { skill: 'hold', target: null, evasion: 'dodge', until: 'never', value: 0 },
      ],
    })
  })

  it.each(['드론 1부터 공격해', '체력이 적은 드론부터 잡고 위험하면 물러나', '방패로 막으면서 싸워', '피해', ''])(
    '짧은 명령이 아닌 "%s"는 알아듣지 않는다 (언어 모델이 본다)',
    (order) => {
      expect(quickPlan(order)).toBeNull()
    },
  )

  it('중복: 같은 명령을 여러 번 해도 서로 다른 복사본을 준다 (하나를 고쳐도 다음에 영향이 없다)', () => {
    const first = quickPlan('공격')
    first?.steps.pop()

    expect(quickPlan('공격')?.steps).toHaveLength(2)
  })
})

describe('normalizeOrder', () => {
  it('작은 글자로 바꾸고 띄어쓰기·문장 부호를 뺀다', () => {
    expect(normalizeOrder('  드론 2부터,  잡아! STOP?')).toBe('드론2부터잡아stop')
  })
})
