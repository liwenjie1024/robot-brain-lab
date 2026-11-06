import { describe, expect, it } from 'vitest'
import type { Plan, PlanStep } from '@shared/brain/generated/plan'
import { checkPlan, checkRetreatBelowHp, checkStep, MAX_STEPS } from './planCheck'

const TARGETS = new Set(['drone-1', 'drone-2'])

const step = (overrides: Partial<PlanStep> = {}): PlanStep => ({
  skill: 'engage',
  target: null,
  evasion: 'dodge',
  until: 'allDestroyed',
  value: 0,
  ...overrides,
})

const plan = (steps: PlanStep[], overrides: Partial<Plan> = {}): unknown => ({ say: '교전하겠습니다.', retreatBelowHp: 0, steps, ...overrides })

describe('checkPlan', () => {
  it('규칙에 맞는 계획을 받는다', () => {
    const value = plan([step({ target: 'drone-2', until: 'targetDestroyed' }), step(), step({ skill: 'hold', until: 'never' })], { retreatBelowHp: 0.3 })

    expect(checkPlan(value, TARGETS)).toEqual({ ok: true, value })
  })

  it.each([
    ['단계 5개', Array.from({ length: MAX_STEPS }, () => step({ until: 'seconds', value: 10 }))],
    ['seconds 1초', [step({ until: 'seconds', value: 1 })]],
    ['seconds 120초', [step({ until: 'seconds', value: 120 })]],
    ['hpBelow 0.01', [step({ until: 'hpBelow', value: 0.01 })]],
    ['hpBelow 0.99', [step({ until: 'hpBelow', value: 0.99 })]],
    ['자리 지키며 hpBelow', [step({ skill: 'hold', until: 'hpBelow', value: 0.5 })]],
    ['물러나며 seconds', [step({ skill: 'retreat', until: 'seconds', value: 10 }), step()]],
  ])('경계값: %s는 받는다', (_, steps) => {
    expect(checkPlan(plan(steps), TARGETS).ok).toBe(true)
  })

  it.each([
    ['retreatBelowHp 0.9', 0.9, true],
    ['retreatBelowHp 0', 0, true],
    ['retreatBelowHp 0.95', 0.95, false],
    ['retreatBelowHp -0.1', -0.1, false],
  ])('경계값: %s', (_, retreatBelowHp, ok) => {
    expect(checkPlan(plan([step()], { retreatBelowHp }), TARGETS).ok).toBe(ok)
  })

  it.each([
    ['단계가 없음', plan([]), '/steps'],
    ['단계 6개', plan(Array.from({ length: MAX_STEPS + 1 }, () => step())), '/steps'],
    ['모르는 기술', plan([{ ...step(), skill: 'dance' } as unknown as PlanStep]), 'allowed values'],
    ['더 붙은 필드', plan([{ ...step(), speed: 3 } as unknown as PlanStep]), 'speed'],
    ['say가 없음', { retreatBelowHp: 0, steps: [step()] }, 'say'],
    ['say가 120자를 넘음', plan([step()], { say: '가'.repeat(121) }), '/say'],
    ['JSON 객체가 아님', '계획', '전체'],
  ])('실패(모양): %s', (_, value, problem) => {
    const checked = checkPlan(value, TARGETS)

    expect(checked.ok).toBe(false)
    expect(!checked.ok && checked.problem).toContain(problem)
  })

  it.each([
    ['engage가 아닌 단계의 target', [step({ skill: 'hold', target: 'drone-1', until: 'never' })], '단계 1: hold의 target은 null'],
    ['장면에 없는 드론', [step({ target: 'drone-9' })], '장면에 없는 드론입니다: drone-9 (있는 드론: drone-1, drone-2)'],
    ['표적 없이 targetDestroyed', [step({ until: 'targetDestroyed' })], 'targetDestroyed는 target을 정한 engage에만'],
    ['seconds 0.5초', [step({ until: 'seconds', value: 0.5 })], 'seconds면 value는 1~120초'],
    ['hpBelow 0', [step({ until: 'hpBelow', value: 0 })], 'hpBelow면 value는 0과 1 사이'],
    ['hpBelow 1', [step({ until: 'hpBelow', value: 1 })], 'hpBelow면 value는 0과 1 사이'],
    ['never에 value', [step({ until: 'never', value: 5 })], 'until이 never이면 value는 0'],
    ['never 뒤의 단계', [step({ skill: 'hold', until: 'never' }), step()], '단계 2: 앞 단계의 until이 never'],
    ['쏘지 않는 기술에 allDestroyed', [step({ skill: 'hold', until: 'allDestroyed' })], 'allDestroyed는 engage에만 씁니다'],
    ['물러나며 hpBelow', [step({ skill: 'retreat', until: 'hpBelow', value: 0.5 })], 'hpBelow는 engage·hold에만'],
    ['멈춰서 hpBelow', [step({ skill: 'idle', until: 'hpBelow', value: 0.5 })], '물러날 체력은 retreatBelowHp로'],
  ])('실패(뜻): %s', (_, steps, problem) => {
    const checked = checkPlan(plan(steps), TARGETS)

    expect(checked.ok).toBe(false)
    expect(!checked.ok && checked.problem).toContain(problem)
  })

  it('살아 있는 드론이 없으면 표적을 정한 단계는 받지 않는다', () => {
    const checked = checkPlan(plan([step({ target: 'drone-1' })]), new Set())

    expect(!checked.ok && checked.problem).toContain('있는 드론: 없음')
  })
})

describe('checkStep', () => {
  it('흘러 온 단계 하나를 앞 단계와 함께 본다', () => {
    expect(checkStep(step(), 0, undefined, TARGETS).ok).toBe(true)
    expect(checkStep(step(), 1, step({ until: 'never' }), TARGETS)).toMatchObject({ ok: false, problem: expect.stringContaining('단계 2') })
  })

  it('경계값: 다섯 번째 단계는 받고 여섯 번째는 받지 않는다', () => {
    expect(checkStep(step(), MAX_STEPS - 1, step(), TARGETS).ok).toBe(true)
    expect(checkStep(step(), MAX_STEPS, step(), TARGETS)).toMatchObject({ ok: false, problem: `단계는 ${MAX_STEPS}개까지입니다` })
  })

  it('실패: 모양이 틀린 단계는 몇 번째인지 붙여 알린다', () => {
    expect(checkStep({ skill: 'engage' }, 2, step(), TARGETS)).toMatchObject({ ok: false, problem: expect.stringMatching(/^단계 3: /) })
  })
})

describe('checkRetreatBelowHp', () => {
  it.each([
    [0, true],
    [0.9, true],
    [0.91, false],
    ['0.3', false],
    [undefined, false],
  ])('%s → %s', (value, ok) => {
    expect(checkRetreatBelowHp(value).ok).toBe(ok)
  })
})
